
import sqlite3
from datetime import datetime

DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Job 101216 ran ~19:30 to 19:55
start_time = "2026-01-18 19:30:00"
end_time = "2026-01-18 19:56:00"

print(f"Checking questions created between {start_time} and {end_time}...")

query = '''
    SELECT count(q.id) as cnt
    FROM questions q
    JOIN reviews r ON q.id = r.question_id
    WHERE r.user_id = 1
      AND r.next_review_date BETWEEN ? AND ?
'''
c.execute(query, (start_time, end_time))
row = c.fetchone()
print(f"🔢 Total Questions Added: {row['cnt']}")

# Also show start/end IDs
c.execute('''
    SELECT min(q.id) as min_id, max(q.id) as max_id
    FROM questions q
    JOIN reviews r ON q.id = r.question_id
    WHERE r.user_id = 1
      AND r.next_review_date BETWEEN ? AND ?
''', (start_time, end_time))
stats = c.fetchone()
print(f"🆔 ID Range: {stats['min_id']} -> {stats['max_id']} (Diff: {stats['max_id'] - stats['min_id'] + 1 if stats['max_id'] else 0})")
