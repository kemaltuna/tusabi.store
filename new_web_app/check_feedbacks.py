import sqlite3
import os
import sys

# Path to DB
DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"

def view_feedbacks():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = """
    SELECT 
        f.id,
        f.feedback_type,
        f.description,
        f.created_at,
        q.question_text,
        q.topic,
        q.source_material,
        f.resolved
    FROM question_feedback f
    LEFT JOIN questions q ON f.question_id = q.id
    ORDER BY f.created_at DESC
    """

    try:
        c.execute(query)
        rows = c.fetchall()

        if not rows:
            print("No feedbacks found.")
            return

        print(f"Found {len(rows)} feedbacks:\n")
        print("-" * 80)
        for row in rows:
            print(f"ID: {row['id']} | Resolved: {row['resolved']}")
            print(f"Type: {row['feedback_type']}")
            print(f"Date: {row['created_at']}")
            print(f"Topic: {row['topic']} ({row['source_material']})")
            print(f"Question: {row['question_text'][:100]}..." if row['question_text'] else "Question not found")
            print(f"Feedback: {row['description']}")
            print("-" * 80)

    except Exception as e:
        print(f"Error fetching feedbacks: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    view_feedbacks()
