#!/usr/bin/env python3
"""
Retry failed flashcard generations.

Notes:
- A "failed run" does not store the exact request payload; retries will generate
  from currently-unused highlights (same as calling /flashcards/generate again).
- Intended to be executed with the project venv Python:
  ./venv/bin/python new_web_app/scripts/retry_failed_flashcards.py --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


def _load_env() -> None:
    # Prefer local .env for CLI use.
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    repo_root = Path(__file__).resolve().parents[2]  # -> medical_quiz_app
    load_dotenv(repo_root / ".env")
    load_dotenv(repo_root / "new_web_app" / ".env")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Retry failed flashcard generations.")
    p.add_argument("--user-id", type=int, default=None, help="Retry only for a single user_id.")
    p.add_argument("--since", type=str, default=None, help="Only consider failed runs on/after ISO timestamp.")
    p.add_argument("--max-users", type=int, default=50, help="Maximum number of users to retry.")
    p.add_argument("--limit", type=int, default=None, help="Highlight fetch limit (default uses router constant).")
    p.add_argument("--max-cards", type=int, default=None, help="Max cards per run (default uses router constant).")
    p.add_argument("--dry-run", action="store_true", help="Do not perform generation; print what would happen.")
    return p.parse_args()


def main() -> int:
    # Ensure repo root is on sys.path so `new_web_app.*` imports work when run from any CWD.
    repo_root = Path(__file__).resolve().parents[2]  # -> medical_quiz_app
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    _load_env()
    args = _parse_args()

    # Import after env load.
    from new_web_app.backend.database import get_db_connection
    from new_web_app.backend.routers.flashcards import (
        ensure_generation_table,
        ensure_usage_table,
        get_unused_highlight_stats,
        has_active_generation,
        mark_generation_status,
        run_flashcard_generation,
        MAX_HIGHLIGHT_LIMIT,
        MAX_FLASHCARD_CARDS,
        MIN_FLASHCARD_QUESTIONS,
        MIN_FLASHCARD_CHARS,
    )

    limit = args.limit if args.limit is not None else MAX_HIGHLIGHT_LIMIT
    max_cards = args.max_cards if args.max_cards is not None else MAX_FLASHCARD_CARDS

    conn = get_db_connection()
    try:
        ensure_generation_table(conn)
        ensure_usage_table(conn)
        cur = conn.cursor()

        params: list[object] = []
        where = "WHERE status='failed'"
        if args.user_id is not None:
            where += " AND user_id=?"
            params.append(args.user_id)
        if args.since:
            where += " AND created_at >= ?"
            params.append(args.since)

        cur.execute(
            f"""
            SELECT user_id, MAX(created_at) AS last_failed
            FROM flashcard_generation_runs
            {where}
            GROUP BY user_id
            ORDER BY last_failed DESC
            LIMIT ?
            """,
            (*params, args.max_users),
        )
        users = [(r["user_id"], r["last_failed"]) for r in cur.fetchall()]
    finally:
        conn.close()

    if not users:
        print("No failed flashcard generation runs found for the given filters.")
        return 0

    print(f"Found {len(users)} user(s) with failed runs.")

    for user_id, last_failed in users:
        stats = get_unused_highlight_stats(user_id)
        active = False
        conn = get_db_connection()
        try:
            ensure_generation_table(conn)
            active = has_active_generation(conn, user_id)
        finally:
            conn.close()

        print(
            f"\nuser_id={user_id} last_failed={last_failed} "
            f"active={active} stats={stats}"
        )

        if active:
            print("  skip: active generation exists")
            continue
        if stats.get("question_count", 0) < MIN_FLASHCARD_QUESTIONS:
            print(f"  skip: not enough questions (<{MIN_FLASHCARD_QUESTIONS})")
            continue
        if stats.get("total_chars", 0) < MIN_FLASHCARD_CHARS:
            print(f"  skip: not enough chars (<{MIN_FLASHCARD_CHARS})")
            continue

        if args.dry_run:
            print(f"  dry-run: would generate (limit={limit}, max_cards={max_cards})")
            continue

        # Create a new run record for this retry.
        conn = get_db_connection()
        try:
            ensure_generation_table(conn)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO flashcard_generation_runs (user_id, status, created_at) VALUES (?, ?, ?) RETURNING id",
                (user_id, "processing", datetime.now().isoformat()),
            )
            inserted = cur.fetchone()
            if not inserted:
                raise RuntimeError("Failed to create flashcard_generation_runs row.")
            try:
                run_id = int(inserted["id"])
            except Exception:
                run_id = int(inserted[0])
            conn.commit()
        finally:
            conn.close()

        try:
            resp = run_flashcard_generation(user_id, limit=limit, max_cards=max_cards)
            print(
                f"  ok: created={resp.created} highlight_count={resp.highlight_count} "
                f"flashcard_ids={len(resp.flashcard_ids)}"
            )
            conn = get_db_connection()
            try:
                mark_generation_status(conn, run_id, "completed")
            finally:
                conn.close()
        except Exception as exc:
            print(f"  failed: {type(exc).__name__}: {exc}")
            conn = get_db_connection()
            try:
                mark_generation_status(conn, run_id, "failed")
            finally:
                conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
