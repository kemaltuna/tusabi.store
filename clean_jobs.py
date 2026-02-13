
import sqlite3
import os

DB_PATH = "shared/data/quiz_v2.db"

def clean_jobs():
    if not os.path.exists(DB_PATH):
        print(f"❌ DB not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Count before
        c.execute("SELECT status, COUNT(*) FROM background_jobs GROUP BY status")
        print("Before Cleanup:", c.fetchall())

        # Delete pending/running (or mark as cancelled? User said "sil" (delete/remove))
        # Safest is to delete them or mark them failed. 
        # User said "bekleyen jobları sil" -> Delete pending/running.
        c.execute("DELETE FROM background_jobs WHERE status IN ('pending', 'running')")
        deleted = c.rowcount
        print(f"✅ Deleted {deleted} stale jobs.")
        
        conn.commit()
        
        # Count after
        c.execute("SELECT status, COUNT(*) FROM background_jobs GROUP BY status")
        print("After Cleanup:", c.fetchall())
        
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clean_jobs()
