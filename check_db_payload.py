import sqlite3
import json
import os

DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"

def main():
    if not os.path.exists(DB_PATH):
        print("DB not found")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get last 5 jobs
    c.execute("SELECT id, type, payload, status FROM background_jobs WHERE type='generation_batch' ORDER BY id DESC LIMIT 5")
    rows = c.fetchall()
    
    print(f"Found {len(rows)} jobs in DB")
    for row in rows:
        job_id = row[0]
        payload_str = row[2]
        try:
            payload = json.loads(payload_str)
            source_pdf = payload.get("source_pdf")
            topic = payload.get("topic")
            print(f"\nJob {job_id}:")
            print(f"  Topic: {topic}")
            print(f"  Source PDF: {source_pdf}")
        except:
            print(f"Job {job_id}: Failed to parse payload")

    conn.close()

if __name__ == "__main__":
    main()
