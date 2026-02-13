import sqlite3
import json
from datetime import datetime

DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"
BACKUP_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/backup_jan20_22_questions.json"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Select all questions from Jan 20-22
    c.execute("""
        SELECT * FROM questions 
        WHERE date(created_at) IN ('2026-01-20', '2026-01-21', '2026-01-22')
    """)
    rows = c.fetchall()
    
    print(f"Found {len(rows)} questions to backup and delete.")
    
    if len(rows) == 0:
        print("No questions found. Exiting.")
        conn.close()
        return
    
    # 2. Convert to list of dicts for JSON
    questions = []
    for row in rows:
        q = dict(row)
        # Convert datetime objects to strings if needed
        for key, val in q.items():
            if isinstance(val, datetime):
                q[key] = val.isoformat()
        questions.append(q)
    
    # 3. Write backup JSON
    with open(BACKUP_PATH, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"Backup saved to: {BACKUP_PATH}")
    
    # 4. Delete from DB
    c.execute("""
        DELETE FROM questions 
        WHERE date(created_at) IN ('2026-01-20', '2026-01-21', '2026-01-22')
    """)
    deleted_count = c.rowcount
    conn.commit()
    print(f"Deleted {deleted_count} questions from database.")
    
    conn.close()
    print("Done!")

if __name__ == "__main__":
    main()
