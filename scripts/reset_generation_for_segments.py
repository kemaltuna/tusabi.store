#!/usr/bin/env python3
"""
Reset question generation for selected library segments.

What it does (per segment: source_material + main_header):
- Deletes questions in `questions` (and related rows in dependent tables) for that category.
- Resets matching `background_jobs` (type=generation_batch) back to `pending` so they re-run.

Notes:
- The job worker uses SQLite and may be running concurrently. This script uses a busy timeout
  and keeps transactions small.
- Optionally toggles `generation_paused.flag` during the operation (does not stop a currently
  processing job; it only prevents claiming new ones).
"""

from __future__ import annotations

import argparse
import contextlib
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent  # -> medical_quiz_app
DEFAULT_DB_PATH = PROJECT_ROOT / "shared" / "data" / "quiz_v2.db"
PAUSE_FLAG_PATH = PROJECT_ROOT / "generation_paused.flag"


@dataclass(frozen=True)
class Segment:
    source_material: str
    main_header: str


def _chunked(values: list[int], chunk_size: int = 900) -> Iterable[list[int]]:
    for i in range(0, len(values), chunk_size):
        yield values[i : i + chunk_size]


def _now_ts() -> str:
    # Matches the general format used elsewhere in the app.
    return datetime.now().isoformat(sep=" ", timespec="microseconds")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def _parse_segment(raw: str) -> Segment:
    if "|" not in raw:
        raise argparse.ArgumentTypeError("Segment must be in the form SOURCE_MATERIAL|MAIN_HEADER")
    left, right = raw.split("|", 1)
    source_material = left.strip()
    main_header = right.strip()
    if not source_material or not main_header:
        raise argparse.ArgumentTypeError("Segment must be in the form SOURCE_MATERIAL|MAIN_HEADER")
    return Segment(source_material=source_material, main_header=main_header)


@contextlib.contextmanager
def _maybe_pause_generation(enabled: bool):
    if not enabled:
        yield
        return

    existed = PAUSE_FLAG_PATH.exists()
    if not existed:
        PAUSE_FLAG_PATH.write_text("paused by reset_generation_for_segments.py\n", encoding="ascii")
    try:
        yield
    finally:
        if not existed:
            try:
                PAUSE_FLAG_PATH.unlink(missing_ok=True)
            except Exception:
                # Best-effort; don't hide the main outcome.
                pass


def _fetch_int(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _fetch_ids(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[int]:
    return [int(r[0]) for r in conn.execute(sql, params).fetchall()]


def _delete_where_in(conn: sqlite3.Connection, table: str, column: str, ids: list[int]) -> int:
    if not ids:
        return 0
    total = 0
    for chunk in _chunked(ids):
        placeholders = ",".join(["?"] * len(chunk))
        cur = conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", chunk)
        total += int(cur.rowcount or 0)
    return total


def _reset_segment(
    conn: sqlite3.Connection,
    segment: Segment,
    *,
    dry_run: bool,
    reset_jobs: bool,
) -> dict:
    category_like = f"{segment.main_header}%"

    question_ids = _fetch_ids(
        conn,
        "SELECT id FROM questions WHERE source_material = ? AND category LIKE ?",
        (segment.source_material, category_like),
    )

    highlight_ids: list[int] = []
    if question_ids:
        placeholders = ",".join(["?"] * len(question_ids))
        highlight_ids = _fetch_ids(
            conn,
            f"SELECT id FROM user_highlights WHERE question_id IN ({placeholders})",
            tuple(question_ids),
        )

    job_status_counts = conn.execute(
        """
        SELECT status, COUNT(*)
        FROM background_jobs
        WHERE type = 'generation_batch'
          AND json_extract(payload, '$.source_material') = ?
          AND COALESCE(json_extract(payload, '$.main_header'), json_extract(payload, '$.category')) = ?
        GROUP BY status
        ORDER BY COUNT(*) DESC
        """,
        (segment.source_material, segment.main_header),
    ).fetchall()
    jobs_total = sum(int(r[1]) for r in job_status_counts)

    summary = {
        "segment": {"source_material": segment.source_material, "main_header": segment.main_header},
        "questions": {"matched": len(question_ids)},
        "highlights": {"matched": len(highlight_ids)},
        "jobs": {"matched": jobs_total, "by_status": {str(r[0]): int(r[1]) for r in job_status_counts}},
        "deleted": {},
        "jobs_reset": 0,
    }

    if dry_run:
        return summary

    # Keep the write-lock window short.
    conn.execute("BEGIN IMMEDIATE")
    try:
        deleted = {}

        # Delete dependent rows first.
        deleted["flashcard_highlight_usage"] = _delete_where_in(
            conn, "flashcard_highlight_usage", "highlight_id", highlight_ids
        )
        deleted["user_highlights"] = _delete_where_in(conn, "user_highlights", "id", highlight_ids)

        deleted["reviews"] = _delete_where_in(conn, "reviews", "question_id", question_ids)
        deleted["question_feedback"] = _delete_where_in(conn, "question_feedback", "question_id", question_ids)
        deleted["content_feedback"] = _delete_where_in(conn, "content_feedback", "question_id", question_ids)
        deleted["extended_explanations"] = _delete_where_in(conn, "extended_explanations", "question_id", question_ids)
        deleted["visual_explanations"] = _delete_where_in(conn, "visual_explanations", "question_id", question_ids)
        deleted["question_topic_links"] = _delete_where_in(conn, "question_topic_links", "question_id", question_ids)

        deleted["questions"] = _delete_where_in(conn, "questions", "id", question_ids)

    # Reset jobs back to pending (do not touch processing jobs).
        cur = None
        if reset_jobs:
            cur = conn.execute(
                """
                UPDATE background_jobs
                SET status = 'pending',
                    progress = 0,
                    -- Helps the UI show an accurate target immediately after reset.
                    total_items = COALESCE(CAST(json_extract(payload, '$.count') AS INTEGER), 0),
                    worker_id = NULL,
                    error_message = NULL,
                    updated_at = ?,
                    completed_at = NULL,
                    generated_count = 0,
                    attempts = 0
                WHERE type = 'generation_batch'
                  AND json_extract(payload, '$.source_material') = ?
                  AND COALESCE(json_extract(payload, '$.main_header'), json_extract(payload, '$.category')) = ?
                  AND status <> 'processing'
                """,
                (_now_ts(), segment.source_material, segment.main_header),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    summary["deleted"] = deleted
    summary["jobs_reset"] = int(cur.rowcount or 0) if cur is not None else 0
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Reset questions + generation jobs for selected segments.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to quiz_v2.db")
    parser.add_argument(
        "--segment",
        action="append",
        type=_parse_segment,
        help="Repeatable: SOURCE_MATERIAL|MAIN_HEADER",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would change, but do nothing.")
    parser.add_argument(
        "--delete-only",
        action="store_true",
        help="Only delete matching questions (and dependent rows). Do NOT reset jobs.",
    )
    parser.add_argument(
        "--pause-generation",
        action="store_true",
        help="Temporarily create generation_paused.flag while resetting.",
    )

    args = parser.parse_args(argv)

    segments: list[Segment] = args.segment or [
        # Defaults: the segments recently fixed in this repo.
        Segment(source_material="Farmakoloji", main_header="OTAKO\u0130DLER"),
        Segment(source_material="Kucuk_Stajlar", main_header="Kulak-Burun-Bo\u011faz Hastal\u0131klar\u0131"),
    ]

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    results = []
    with _maybe_pause_generation(bool(args.pause_generation)):
        conn = _connect(args.db)
        try:
            for seg in segments:
                results.append(
                    _reset_segment(
                        conn,
                        seg,
                        dry_run=bool(args.dry_run),
                        reset_jobs=(not bool(args.delete_only)),
                    )
                )
        finally:
            conn.close()

    # Human-readable, stable output (no emojis).
    for r in results:
        seg = r["segment"]
        print(f"Segment: {seg['source_material']} | {seg['main_header']}")
        print(f"- questions matched: {r['questions']['matched']}")
        print(f"- highlights matched: {r['highlights']['matched']}")
        print(f"- jobs matched: {r['jobs']['matched']}")
        for k, v in r["jobs"]["by_status"].items():
            print(f"  - jobs[{k}]: {v}")
        if "deleted" in r and r["deleted"]:
            print("- deleted rows:")
            for k, v in r["deleted"].items():
                print(f"  - {k}: {v}")
        if not args.dry_run:
            if args.delete_only:
                print("- jobs reset to pending: (skipped; --delete-only)")
            else:
                print(f"- jobs reset to pending: {r['jobs_reset']}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
