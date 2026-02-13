import sqlite3
import os

DB_PATH = "shared/data/quiz_v2.db"

def init_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Creating question_feedback table...")
    c.execute('''
        CREATE TABLE IF NOT EXISTS question_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question_id INTEGER,
            feedback_type TEXT,
            description TEXT,
            resolved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    init_db()
