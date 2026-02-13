import json
import sqlite3
from pathlib import Path

import sys
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "new_web_app"))

from new_web_app.backend import database

DB_PATH = PROJECT_ROOT / "shared" / "data" / "quiz_v2.db"


def backfill_qa_tags(dry_run: bool = True) -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT id, question_text, options, correct_answer_index, tags FROM questions")
    rows = c.fetchall()

    updated = 0
    skipped = 0

    for row in rows:
        tags = database.safe_json_parse(row["tags"], [])
        qa_tag = database.build_qa_tag(
            row["question_text"],
            row["options"],
            row["correct_answer_index"],
            tags
        )

        if not qa_tag:
            skipped += 1
            continue

        if qa_tag in tags:
            skipped += 1
            continue

        tags.append(qa_tag)
        updated += 1

        if not dry_run:
            c.execute(
                "UPDATE questions SET tags = ? WHERE id = ?",
                (json.dumps(tags, ensure_ascii=False), row["id"])
            )

    if not dry_run:
        conn.commit()

    conn.close()

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"{mode}: updated={updated}, skipped={skipped}, total={len(rows)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        backfill_qa_tags(dry_run=False)
    else:
        backfill_qa_tags(dry_run=True)
