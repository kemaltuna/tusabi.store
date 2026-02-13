#!/usr/bin/env python3
"""
Backfill question_topic_links for existing questions.

Steps:
1. Ensure every question is linked to its own `questions.topic`.
2. Expand merged-topic questions to their underlying topics using:
   - shared/data/merged_topic_groups.json
   - background_jobs payload all_topics/main_header/topic metadata
"""

import argparse
import json
import sqlite3
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "shared" / "data" / "quiz_v2.db"
MERGED_GROUPS_PATH = PROJECT_ROOT / "shared" / "data" / "merged_topic_groups.json"


def _clean_topic(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def _dedupe_topics(values) -> list[str]:
    raw = values if isinstance(values, list) else [values]
    out: list[str] = []
    seen = set()
    for value in raw:
        topic = _clean_topic(value)
        if not topic or topic in seen:
            continue
        seen.add(topic)
        out.append(topic)
    return out


def ensure_question_topic_links_table(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS question_topic_links (
            question_id INTEGER NOT NULL,
            source_material TEXT,
            category TEXT,
            topic TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (question_id, topic)
        )
        """
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_qtl_scope_topic "
        "ON question_topic_links (source_material, category, topic, question_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_qtl_topic "
        "ON question_topic_links (topic, question_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_qtl_question "
        "ON question_topic_links (question_id)"
    )


def seed_direct_topic_links(conn: sqlite3.Connection) -> int:
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO question_topic_links (question_id, source_material, category, topic)
        SELECT id, source_material, category, TRIM(topic)
        FROM questions
        WHERE topic IS NOT NULL AND TRIM(topic) != ''
        """
    )
    return c.rowcount if c.rowcount and c.rowcount > 0 else 0


def _build_group_map_from_merged_file() -> dict[tuple[str, str, str], set[str]]:
    mapping: dict[tuple[str, str, str], set[str]] = {}
    if not MERGED_GROUPS_PATH.exists():
        return mapping

    try:
        data = json.loads(MERGED_GROUPS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return mapping

    if not isinstance(data, list):
        return mapping

    for item in data:
        if not isinstance(item, dict):
            continue
        source = _clean_topic(item.get("source_material"))
        category = _clean_topic(item.get("main_header"))
        merged_topic = _clean_topic(item.get("merged_topic"))
        topics = _dedupe_topics(item.get("topics", []))
        if not source or not category or not merged_topic or not topics:
            continue
        key = (source, category, merged_topic)
        mapping.setdefault(key, set()).update(topics)

    return mapping


def _build_group_map_from_background_jobs(conn: sqlite3.Connection) -> dict[tuple[str, str, str], set[str]]:
    mapping: dict[tuple[str, str, str], set[str]] = {}
    c = conn.cursor()
    try:
        c.execute("SELECT payload FROM background_jobs WHERE payload IS NOT NULL")
    except Exception:
        return mapping

    for row in c.fetchall():
        payload_raw = row[0]
        if not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        source = _clean_topic(payload.get("source_material"))
        category = _clean_topic(payload.get("category") or payload.get("main_header"))
        merged_topic = _clean_topic(payload.get("topic"))
        topics = _dedupe_topics(payload.get("all_topics", []))
        if not source or not category or not merged_topic or not topics:
            continue

        key = (source, category, merged_topic)
        mapping.setdefault(key, set()).update(topics)

    return mapping


def expand_merged_topic_links(conn: sqlite3.Connection) -> tuple[int, int]:
    merged_map = _build_group_map_from_merged_file()
    job_map = _build_group_map_from_background_jobs(conn)

    # Merge both maps
    for key, topics in job_map.items():
        merged_map.setdefault(key, set()).update(topics)

    c = conn.cursor()
    linked_questions = 0
    inserted_links = 0

    for (source, category, merged_topic), topics in merged_map.items():
        topic_list = sorted(_dedupe_topics(list(topics)))
        if not topic_list:
            continue

        c.execute(
            """
            SELECT id
            FROM questions
            WHERE source_material = ? AND category = ? AND topic = ?
            """,
            (source, category, merged_topic)
        )
        question_ids = [row[0] for row in c.fetchall()]
        if not question_ids:
            continue

        linked_questions += len(question_ids)
        for question_id in question_ids:
            for topic in topic_list:
                c.execute(
                    """
                    INSERT OR IGNORE INTO question_topic_links
                    (question_id, source_material, category, topic)
                    VALUES (?, ?, ?, ?)
                    """,
                    (question_id, source, category, topic)
                )
                if c.rowcount and c.rowcount > 0:
                    inserted_links += c.rowcount

    return linked_questions, inserted_links


def main():
    parser = argparse.ArgumentParser(description="Backfill question_topic_links table.")
    parser.add_argument("--dry-run", action="store_true", help="Execute then rollback.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        if args.dry_run:
            conn.execute("BEGIN")

        ensure_question_topic_links_table(conn)
        direct_added = seed_direct_topic_links(conn)
        merged_questions, merged_added = expand_merged_topic_links(conn)

        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM question_topic_links")
        total_links = c.fetchone()[0]

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

        mode = "DRY-RUN" if args.dry_run else "APPLIED"
        print(
            f"[{mode}] direct_added={direct_added}, merged_questions={merged_questions}, "
            f"merged_added={merged_added}, total_links={total_links}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

