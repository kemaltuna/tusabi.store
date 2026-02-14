#!/usr/bin/env python3
"""
Cleanup orphan rows in the database.

Policy (requested):
- If a question no longer exists, any dependent rows (highlights, feedback, etc.)
  should also not exist.

This script is safe-by-default:
- Dry-run prints counts.
- Use --execute to apply changes.

Supported engines:
- Postgres (recommended). SQLite is not supported by this script on purpose to
  avoid accidental cleanup of the legacy db file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = REPO_ROOT / "reports"


ORPHAN_QUERIES: Dict[str, str] = {
    # References questions(id)
    "reviews": """
        SELECT COUNT(*)
        FROM reviews r
        LEFT JOIN questions q ON q.id = r.question_id
        WHERE q.id IS NULL
    """,
    "question_feedback": """
        SELECT COUNT(*)
        FROM question_feedback f
        LEFT JOIN questions q ON q.id = f.question_id
        WHERE f.question_id IS NOT NULL AND q.id IS NULL
    """,
    "content_feedback": """
        SELECT COUNT(*)
        FROM content_feedback cf
        LEFT JOIN questions q ON q.id = cf.question_id
        WHERE cf.question_id IS NOT NULL AND q.id IS NULL
    """,
    "extended_explanations": """
        SELECT COUNT(*)
        FROM extended_explanations ee
        LEFT JOIN questions q ON q.id = ee.question_id
        WHERE ee.question_id IS NOT NULL AND q.id IS NULL
    """,
    "visual_explanations": """
        SELECT COUNT(*)
        FROM visual_explanations ve
        LEFT JOIN questions q ON q.id = ve.question_id
        WHERE ve.question_id IS NOT NULL AND q.id IS NULL
    """,
    "question_topic_links": """
        SELECT COUNT(*)
        FROM question_topic_links l
        LEFT JOIN questions q ON q.id = l.question_id
        WHERE q.id IS NULL
    """,
    "user_highlights": """
        SELECT COUNT(*)
        FROM user_highlights h
        LEFT JOIN questions q ON q.id = h.question_id
        WHERE h.question_id IS NOT NULL AND q.id IS NULL
    """,
    # References user_highlights(id)
    "flashcard_highlight_usage": """
        SELECT COUNT(*)
        FROM flashcard_highlight_usage u
        LEFT JOIN user_highlights h ON h.id = u.highlight_id
        WHERE h.id IS NULL
    """,
    # user_sessions.current_card_id references questions(id) (best-effort hygiene)
    "user_sessions_current_card": """
        SELECT COUNT(*)
        FROM user_sessions s
        LEFT JOIN questions q ON q.id = s.current_card_id
        WHERE s.current_card_id IS NOT NULL AND q.id IS NULL
    """,
}


DELETE_STATEMENTS: Dict[str, str] = {
    # Delete highlight rows whose parent question is missing.
    "user_highlights": """
        DELETE FROM user_highlights h
        WHERE h.question_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = h.question_id
          )
    """,
    # Then delete usage rows that now point to missing highlights.
    "flashcard_highlight_usage": """
        DELETE FROM flashcard_highlight_usage u
        WHERE NOT EXISTS (
            SELECT 1 FROM user_highlights h WHERE h.id = u.highlight_id
        )
    """,
    "reviews": """
        DELETE FROM reviews r
        WHERE NOT EXISTS (
            SELECT 1 FROM questions q WHERE q.id = r.question_id
        )
    """,
    "question_feedback": """
        DELETE FROM question_feedback f
        WHERE f.question_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = f.question_id
          )
    """,
    "content_feedback": """
        DELETE FROM content_feedback cf
        WHERE cf.question_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = cf.question_id
          )
    """,
    "extended_explanations": """
        DELETE FROM extended_explanations ee
        WHERE ee.question_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = ee.question_id
          )
    """,
    "visual_explanations": """
        DELETE FROM visual_explanations ve
        WHERE ve.question_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = ve.question_id
          )
    """,
    "question_topic_links": """
        DELETE FROM question_topic_links l
        WHERE NOT EXISTS (
            SELECT 1 FROM questions q WHERE q.id = l.question_id
        )
    """,
    # Best-effort: clear session pointer if card was deleted.
    "user_sessions_current_card": """
        UPDATE user_sessions s
        SET current_card_id = NULL
        WHERE s.current_card_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM questions q WHERE q.id = s.current_card_id
          )
    """,
}


def _require_postgres_dsn(dsn: str) -> None:
    lowered = (dsn or "").strip().lower()
    if not (lowered.startswith("postgres://") or lowered.startswith("postgresql://")):
        raise SystemExit(
            "This cleanup script only supports Postgres. "
            "Set MEDQUIZ_DB_URL/DATABASE_URL to a postgres:// DSN."
        )


def _fetch_count(cur: Any, sql: str) -> int:
    cur.execute(sql)
    row = cur.fetchone()
    if not row:
        return 0
    if isinstance(row, dict):
        return int(list(row.values())[0] or 0)
    return int(row[0] or 0)


def collect_orphan_counts(conn: Any) -> Dict[str, int]:
    cur = conn.cursor()
    counts: Dict[str, int] = {}
    for name, sql in ORPHAN_QUERIES.items():
        counts[name] = _fetch_count(cur, sql)
    return counts


def apply_cleanup(conn: Any) -> Dict[str, int]:
    cur = conn.cursor()
    affected: Dict[str, int] = {}
    for name, sql in DELETE_STATEMENTS.items():
        cur.execute(sql)
        affected[name] = int(getattr(cur, "rowcount", 0) or 0)
    return affected


def write_report(payload: Dict[str, Any], *, timestamp: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"orphan_cleanup_{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Cleanup orphan rows (Postgres only).")
    ap.add_argument(
        "--dsn",
        default=os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL") or "",
        help="Postgres DSN. Defaults to MEDQUIZ_DB_URL/DATABASE_URL.",
    )
    ap.add_argument("--execute", action="store_true", help="Apply cleanup (otherwise dry-run).")
    args = ap.parse_args()

    if not args.dsn:
        raise SystemExit("Missing --dsn (or MEDQUIZ_DB_URL/DATABASE_URL).")
    _require_postgres_dsn(args.dsn)

    import psycopg

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    with psycopg.connect(args.dsn) as conn:
        before = collect_orphan_counts(conn)
        total_before = sum(before.values())

        if not args.execute:
            report = write_report(
                {
                    "timestamp": timestamp,
                    "mode": "dry_run",
                    "before": before,
                    "before_total": total_before,
                },
                timestamp=timestamp,
            )
            print(json.dumps(before, ensure_ascii=False, indent=2))
            print(f"\nDry-run report: {report}")
            return

        affected = apply_cleanup(conn)
        conn.commit()

        after = collect_orphan_counts(conn)
        total_after = sum(after.values())

        report = write_report(
            {
                "timestamp": timestamp,
                "mode": "execute",
                "before": before,
                "after": after,
                "deleted_or_updated": affected,
                "before_total": total_before,
                "after_total": total_after,
            },
            timestamp=timestamp,
        )
        print(json.dumps({"before": before, "after": after, "affected": affected}, ensure_ascii=False, indent=2))
        print(f"\nExecute report: {report}")


if __name__ == "__main__":
    main()
