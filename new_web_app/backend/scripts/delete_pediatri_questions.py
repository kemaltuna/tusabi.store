
import sqlite3
import os

DB_PATH = "/home/yusuf-kemal-tuna/medical_quiz_app/shared/data/quiz_v2.db"

def delete_pediatri_questions():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # 1. Identify Target Questions
        query = """
            SELECT id FROM questions 
            WHERE (source_material = 'Pediatri' OR category = 'Pediatri')
            AND (
                topic = 'Büyüme ve Gelişme' 
                OR topic = 'Genetik' 
                OR topic LIKE 'Pediatrik Kardiyoloji%'
            )
        """
        c.execute(query)
        rows = c.fetchall()
        question_ids = [row[0] for row in rows]
        
        count = len(question_ids)
        print(f"Found {count} questions to delete.")

        if count == 0:
            print("No questions found matching the criteria.")
            return

        # Prepare for deletion
        placeholders = ','.join(['?'] * count)
        
        # 2. Delete Associated Reviews
        print("Deleting associated reviews...")
        c.execute(f"DELETE FROM reviews WHERE question_id IN ({placeholders})", question_ids)
        reviews_deleted = c.rowcount
        print(f"Deleted {reviews_deleted} reviews.")

        # 3. Delete Questions
        print("Deleting questions...")
        c.execute(f"DELETE FROM questions WHERE id IN ({placeholders})", question_ids)
        questions_deleted = c.rowcount
        print(f"Deleted {questions_deleted} questions.")

        conn.commit()
        print("Deletion successful.")

    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    delete_pediatri_questions()
