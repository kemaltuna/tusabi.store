import json
import sqlite3
from pathlib import Path
import sys
import os
import copy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "new_web_app"))

from new_web_app.core.generation_engine import GenerationEngine

DB_PATH = Path(__file__).resolve().parent.parent / "shared" / "data" / "quiz_v2.db"


def load_json_field(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def main(dry_run: bool = True):
    engine = GenerationEngine(dry_run=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, options, correct_answer_index, explanation_data, tags FROM questions")
    rows = cursor.fetchall()

    updates = []

    for row in rows:
        explanation = load_json_field(row["explanation_data"])
        if not explanation or not isinstance(explanation, dict):
            continue

        before = json.dumps(explanation, ensure_ascii=False, sort_keys=True)
        explanation_copy = copy.deepcopy(explanation)

        question_data = {
            "options": load_json_field(row["options"]) or [],
            "correct_answer_index": row["correct_answer_index"],
            "explanation_data": explanation_copy,
            "tags": load_json_field(row["tags"]) or []
        }

        updated = engine._enforce_table_entity_labels(question_data)
        new_explanation = updated.get("explanation_data")
        after = json.dumps(new_explanation, ensure_ascii=False, sort_keys=True)
        if after != before:
            updates.append((json.dumps(new_explanation, ensure_ascii=False), row["id"]))

    if updates and not dry_run:
        cursor.executemany("UPDATE questions SET explanation_data = ? WHERE id = ?", updates)
        conn.commit()

    print(f"{'DRY RUN' if dry_run else 'APPLIED'}: {len(updates)} tables rewritten out of {len(rows)} rows.")
    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Refresh table headers/cells using current enforce_table_entity_labels logic.")
    parser.add_argument("--execute", action="store_true", help="Write changes back to the database.")
    args = parser.parse_args()

    main(dry_run=not args.execute)
