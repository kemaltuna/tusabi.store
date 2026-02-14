#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_PATH = REPO_ROOT / "shared" / "data" / "quiz_v2.db"


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    has_id_sequence: bool = False  # id BIGSERIAL (or similar)


TABLES: list[TableSpec] = [
    TableSpec("users", ("id", "username", "password_hash", "role", "created_at"), has_id_sequence=True),
    TableSpec(
        "questions",
        (
            "id",
            "source_material",
            "topic",
            "question_text",
            "options",
            "correct_answer_index",
            "explanation_data",
            "tags",
            "created_at",
            "category",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "reviews",
        (
            "question_id",
            "user_id",
            "ease_factor",
            "interval",
            "repetitions",
            "next_review_date",
            "last_review_date",
            "last_grade",
            "flags",
        ),
        has_id_sequence=False,
    ),
    TableSpec("sessions", ("token", "user_id", "created_at"), has_id_sequence=False),
    TableSpec(
        "user_sessions",
        (
            "user_id",
            "active_page",
            "active_topic",
            "active_mode",
            "current_card_id",
            "last_updated",
            "active_source",
            "active_category",
        ),
        has_id_sequence=False,
    ),
    TableSpec(
        "user_highlights",
        (
            "id",
            "user_id",
            "question_id",
            "text_content",
            "context_type",
            "word_index",
            "created_at",
            "context_snippet",
            "context_meta",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "question_feedback",
        (
            "id",
            "user_id",
            "question_id",
            "feedback_type",
            "description",
            "resolved",
            "created_at",
            "status",
            "admin_note",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "background_jobs",
        (
            "id",
            "type",
            "status",
            "payload",
            "progress",
            "total_items",
            "worker_id",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
            "generated_count",
            "attempts",
            "max_attempts",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "generation_logs",
        (
            "id",
            "topic",
            "question_count",
            "status",
            "questions_generated",
            "log_message",
            "created_at",
            "completed_at",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "generation_jobs",
        (
            "id",
            "topic",
            "source_material",
            "status",
            "questions_generated",
            "error_message",
            "created_at",
            "updated_at",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "prompt_templates",
        ("id", "name", "sections", "is_default", "created_at", "updated_at"),
        has_id_sequence=True,
    ),
    TableSpec(
        "difficulty_templates",
        ("id", "name", "levels", "is_default", "created_at", "updated_at"),
        has_id_sequence=True,
    ),
    TableSpec(
        "section_favorites",
        ("id", "section_key", "name", "content", "created_at"),
        has_id_sequence=True,
    ),
    TableSpec(
        "question_topic_links",
        ("question_id", "source_material", "category", "topic", "created_at"),
        has_id_sequence=False,
    ),
    TableSpec(
        "concept_embeddings",
        ("id", "topic", "concept_text", "embedding_json", "created_at"),
        has_id_sequence=True,
    ),
    TableSpec(
        "content_requests",
        (
            "id",
            "user_id",
            "request_type",
            "content_path",
            "description",
            "target_topic",
            "status",
            "created_at",
        ),
        has_id_sequence=True,
    ),
    TableSpec(
        "content_feedback",
        (
            "id",
            "question_id",
            "section",
            "selected_text",
            "user_note",
            "status",
            "created_at",
            "user_id",
        ),
        has_id_sequence=True,
    ),
    TableSpec("user_settings", ("key", "value"), has_id_sequence=False),
    TableSpec(
        "visual_explanations",
        (
            "question_id",
            "image_path",
            "prompt",
            "verification_status",
            "user_feedback",
            "created_at",
            "user_request_note",
        ),
        has_id_sequence=False,
    ),
    TableSpec(
        "extended_explanations",
        (
            "question_id",
            "content",
            "created_at",
            "verification_status",
            "user_request_note",
        ),
        has_id_sequence=False,
    ),
    TableSpec(
        "flashcard_highlight_usage",
        ("highlight_id", "user_id", "used_at"),
        has_id_sequence=False,
    ),
    TableSpec(
        "flashcard_generation_runs",
        ("id", "user_id", "status", "created_at", "updated_at"),
        has_id_sequence=True,
    ),
]


def _placeholders(n: int) -> str:
    return ", ".join(["%s"] * n)


def _fetch_sqlite_rows(conn: sqlite3.Connection, table: TableSpec) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cols = ", ".join(table.columns)
    cur.execute(f"SELECT {cols} FROM {table.name}")
    return cur.fetchall()


def _coerce_row(table: str, row: Sequence[Any]) -> tuple[Any, ...]:
    # SQLite user_highlights.user_id is TEXT; we store it as BIGINT in Postgres.
    if table == "user_highlights":
        row = list(row)
        # columns: id, user_id, ...
        if row[1] is not None:
            try:
                row[1] = int(row[1])
            except Exception:
                row[1] = None
        return tuple(row)
    return tuple(row)


def _truncate_all(pg: psycopg.Connection, tables: Iterable[TableSpec]) -> None:
    with pg.cursor() as cur:
        # Reverse order to satisfy FKs with CASCADE
        names = [t.name for t in tables]
        cur.execute("TRUNCATE TABLE " + ", ".join(names) + " CASCADE")
    pg.commit()


def _copy_table(pg: psycopg.Connection, sqlite_conn: sqlite3.Connection, table: TableSpec, *, on_conflict_do_nothing: bool) -> int:
    rows = _fetch_sqlite_rows(sqlite_conn, table)
    if not rows:
        return 0

    cols = ", ".join(table.columns)
    insert_sql = f"INSERT INTO {table.name} ({cols}) VALUES ({_placeholders(len(table.columns))})"
    if on_conflict_do_nothing:
        insert_sql += " ON CONFLICT DO NOTHING"

    batch = []
    with pg.cursor() as cur:
        for r in rows:
            # sqlite3.Row supports index access
            values = _coerce_row(table.name, tuple(r))
            batch.append(values)
        cur.executemany(insert_sql, batch)
    pg.commit()
    return len(rows)


def _set_sequences(pg: psycopg.Connection, tables: Iterable[TableSpec]) -> None:
    with pg.cursor() as cur:
        for t in tables:
            if not t.has_id_sequence:
                continue
            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t.name}")
            max_id = int(cur.fetchone()[0] or 0)
            # Ensure nextval() will return max_id+1
            cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)",
                (t.name, "id", max_id),
            )
    pg.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate quiz_v2.db (SQLite) to Postgres.")
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH), help="Path to quiz_v2.db")
    parser.add_argument(
        "--pg-dsn",
        default=os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL") or "",
        help="Postgres DSN, e.g. postgresql://user:pass@localhost:5432/medquiz",
    )
    parser.add_argument("--truncate", action="store_true", help="Truncate destination tables before import.")
    parser.add_argument("--no-conflict-ignore", action="store_true", help="Do not use ON CONFLICT DO NOTHING.")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    pg_dsn = (args.pg_dsn or "").strip()
    if not pg_dsn:
        raise SystemExit("Missing --pg-dsn (or MEDQUIZ_DB_URL/DATABASE_URL).")

    sqlite_conn = sqlite3.connect(str(sqlite_path), timeout=60)
    sqlite_conn.row_factory = sqlite3.Row

    with psycopg.connect(pg_dsn) as pg:
        if args.truncate:
            _truncate_all(pg, TABLES)

        total = 0
        for t in TABLES:
            n = _copy_table(pg, sqlite_conn, t, on_conflict_do_nothing=not args.no_conflict_ignore)
            total += n
            print(f"- {t.name}: {n} rows")

        _set_sequences(pg, TABLES)

    sqlite_conn.close()
    print(f"✅ Migration complete. Total rows copied (sum over tables): {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

