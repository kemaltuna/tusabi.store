import sqlite3
import json

DB_PATH = "shared/data/quiz_v2.db"

with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT id, explanation_data FROM questions")
    printed = 0
    for question_id, raw in cursor:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for block in data.get("blocks", []):
            if block.get("type") != "table":
                continue
            headers = block.get("headers", [])
            if any("Tanı" in header for header in headers):
                print(question_id, headers)
                printed += 1
    print(f"Total tables with 'Tanı' in headers: {printed}")
