#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_PATH = REPO_ROOT / "shared" / "data" / "quiz_v2.db"


def _count_sqlite(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0] or 0)


def _count_pg(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0] or 0)


def _group_counts_sqlite(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(source_material, ''), COALESCE(category, ''), COUNT(*)
        FROM questions
        GROUP BY 1, 2
        """
    )
    out: dict[tuple[str, str], int] = {}
    for src, cat, n in cur.fetchall():
        out[(str(src or ""), str(cat or ""))] = int(n or 0)
    return out


def _group_counts_pg(conn: psycopg.Connection) -> dict[tuple[str, str], int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(source_material, ''), COALESCE(category, ''), COUNT(*)
            FROM questions
            GROUP BY 1, 2
            """
        )
        out: dict[tuple[str, str], int] = {}
        for src, cat, n in cur.fetchall():
            out[(str(src or ""), str(cat or ""))] = int(n or 0)
        return out


def _try_parse_json(field_name: str, raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return None
    if not isinstance(raw, str):
        return f"{field_name}: unexpected type {type(raw).__name__}"
    s = raw.strip()
    if not s:
        return None
    try:
        json.loads(s)
        return None
    except Exception as exc:
        return f"{field_name}: invalid JSON ({exc})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SQLite vs Postgres DB contents (row counts + sanity checks).")
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH), help="Path to quiz_v2.db")
    parser.add_argument(
        "--pg-dsn",
        default=os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL") or "",
        help="Postgres DSN, e.g. postgresql://user:pass@localhost:5432/medquiz",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    pg_dsn = (args.pg_dsn or "").strip()
    if not pg_dsn:
        raise SystemExit("Missing --pg-dsn (or MEDQUIZ_DB_URL/DATABASE_URL).")

    sqlite_conn = sqlite3.connect(str(sqlite_path), timeout=60)
    sqlite_conn.row_factory = sqlite3.Row

    # The canonical table list comes from SQLite to avoid drifting.
    sqlite_tables = [
        r[0]
        for r in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        if r and r[0] and not str(r[0]).startswith("sqlite_")
    ]

    mismatches: list[str] = []
    with psycopg.connect(pg_dsn) as pg:
        for t in sqlite_tables:
            s = _count_sqlite(sqlite_conn, t)
            p = _count_pg(pg, t)
            if s != p:
                mismatches.append(f"table={t} sqlite={s} pg={p}")

        # Compare question distribution by (source_material, category)
        s_dist = _group_counts_sqlite(sqlite_conn)
        p_dist = _group_counts_pg(pg)
        if s_dist != p_dist:
            # Show a small diff to keep output readable.
            all_keys = set(s_dist.keys()) | set(p_dist.keys())
            for k in sorted(all_keys)[:2000]:
                if s_dist.get(k, 0) != p_dist.get(k, 0):
                    mismatches.append(f"questions_group {k!r} sqlite={s_dist.get(k,0)} pg={p_dist.get(k,0)}")
                    if len(mismatches) > 50:
                        mismatches.append("... (truncated)")
                        break

        # Sanity-check JSON-ish fields for a small sample.
        with pg.cursor() as cur:
            cur.execute(
                """
                SELECT id, options, explanation_data, tags
                FROM questions
                ORDER BY id DESC
                LIMIT 50
                """
            )
            for row in cur.fetchall():
                qid = row[0]
                for name in ("options", "explanation_data", "tags"):
                    idx = {"options": 1, "explanation_data": 2, "tags": 3}[name]
                    err = _try_parse_json(name, row[idx])
                    if err:
                        mismatches.append(f"question_id={qid} {err}")
                        if len(mismatches) > 50:
                            mismatches.append("... (truncated)")
                            break
                if len(mismatches) > 50:
                    break

    sqlite_conn.close()

    if mismatches:
        print("❌ Verification failed:")
        for m in mismatches:
            print(" -", m)
        return 2

    print("✅ Verification OK: SQLite and Postgres match (counts + basic sanity checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
