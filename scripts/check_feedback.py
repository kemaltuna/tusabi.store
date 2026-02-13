import sqlite3
import os
import pandas as pd
from tabulate import tabulate

DB_PATH = "shared/data/quiz_v2.db"

def check_feedback():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    
    # Read feedback with context (optional: join with questions to get question text)
    query = '''
        SELECT 
            f.id,
            f.created_at,
            f.feedback_type,
            f.description,
            f.user_id,
            f.question_id,
            q.topic,
            q.source_material
        FROM question_feedback f
        LEFT JOIN questions q ON f.question_id = q.id
        ORDER BY f.created_at DESC
    '''
    
    try:
        df = pd.read_sql_query(query, conn)
        if df.empty:
            print("No feedback found.")
        else:
            print(f"\nFound {len(df)} feedback items:\n")
            # Format display
            print(tabulate(df, headers='keys', tablefmt='psql', showindex=False))
            
            # Summary by type
            print("\nSummary by Type:")
            print(df['feedback_type'].value_counts())
            
    except Exception as e:
        print(f"Error reading feedback: {e}")
        
    conn.close()

if __name__ == "__main__":
    check_feedback()
