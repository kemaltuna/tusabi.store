
import sqlite3
import os

DB_PATH = "shared/data/quiz_v2.db"

def clean_processing_jobs():
    if not os.path.exists(DB_PATH):
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Also clean 'processing' as they are dead after restart
        c.execute("DELETE FROM background_jobs WHERE status = 'processing'")
        deleted = c.rowcount
        print(f"✅ Deleted {deleted} 'processing' (zombie) jobs.")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clean_processing_jobs()
