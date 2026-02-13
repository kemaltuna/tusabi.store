
import sqlite3
import json
import os

DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"

def inspect_latest_question():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, question_text, explanation_data FROM questions ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    
    if row:
        print(f"ID: {row[0]}")
        print(f"Question: {row[1][:50]}...")
        print("Explanation Data:")
        try:
            print(json.dumps(json.loads(row[2]), indent=2, ensure_ascii=False))
        except:
            print(row[2])
    else:
        print("No questions found.")

if __name__ == "__main__":
    inspect_latest_question()
