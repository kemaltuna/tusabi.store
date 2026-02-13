
import sqlite3
import json
import os
from datetime import datetime

# Paths
BASE_DIR = "/home/yusuf-kemal-tuna/medical_quiz_app"
DB_PATH = os.path.join(BASE_DIR, "shared/data/quiz_v2.db")
BACKUP_PATH = os.path.join(BASE_DIR, "shared/data/legacy_questions_2.json")

def archive_and_clear():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    print(f"🔌 Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        # 1. Fetch all questions
        print("📥 Fetching all questions...")
        c.execute("SELECT * FROM questions")
        rows = c.fetchall()
        
        all_questions = [dict(row) for row in rows]
        print(f"✅ Found {len(all_questions)} questions.")

        if not all_questions:
            print("⚠️ No questions found. Quitting without deletion.")
            return

        # 2. Write to backup file
        print(f"💾 Saving to {BACKUP_PATH}...")
        with open(BACKUP_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_questions, f, ensure_ascii=False, indent=2)
        
        print("✅ Backup completed successfully.")

        # 3. Verify backup file exists and has content
        if not os.path.exists(BACKUP_PATH) or os.path.getsize(BACKUP_PATH) == 0:
            print("❌ Backup file creation failed! Aborting deletion.")
            return

        # 4. Delete questions and reviews
        print("🗑️  Deleting all questions and reviews from database...")
        c.execute("DELETE FROM reviews") # Delete dependent reviews first (though no foreign key constraint enforced usually in sqlite default, good practice)
        c.execute("DELETE FROM questions")
        
        conn.commit()
        print("✅ Database cleared.")
        
        # Verify empty
        c.execute("SELECT COUNT(*) FROM questions")
        count = c.fetchone()[0]
        print(f"🧐 Remaining questions count: {count} (Should be 0)")

    except Exception as e:
        print(f"❌ Error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    archive_and_clear()
