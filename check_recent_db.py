
import sqlite3
from datetime import datetime, timedelta

def check_recent_questions():
    conn = sqlite3.connect("shared/data/quiz_v2.db")
    c = conn.cursor()
    
    # Check for questions created in the last 60 minutes
    # created_at format is typically ISO string matching python datetime.now()
    # But sqlite text comparison works for ISO dates
    
    cutoff = (datetime.now() - timedelta(minutes=60)).isoformat()
    
    print(f"Checking for questions created after: {cutoff}")
    
    c.execute("SELECT COUNT(*), MAX(created_at) FROM questions WHERE created_at > ?", (cutoff,))
    row = c.fetchone()
    count = row[0]
    last_time = row[1]
    
    print(f"Recent Questions Found: {count}")
    if count > 0:
        print(f"Last Created At: {last_time}")
        
        # Show details of the last one
        c.execute("SELECT id, topic, question_text FROM questions ORDER BY created_at DESC LIMIT 1")
        last_q = c.fetchone()
        print(f"Last Question ID: {last_q[0]}")
        print(f"Last Question Topic: {last_q[1]}")
        print(f"Last Question Text: {last_q[2][:100]}...")
    
    conn.close()

if __name__ == "__main__":
    check_recent_questions()
