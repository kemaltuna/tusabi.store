import shutil
import os
import sqlite3
import sys

SOURCE_DB = "data/quiz.db"
TARGET_DB = "data/quiz_v2.db"

def clone_database():
    print(f"🔄 Starting Database Clone...")
    print(f"   Source: {SOURCE_DB}")
    print(f"   Target: {TARGET_DB}")

    if not os.path.exists(SOURCE_DB):
        print(f"❌ Error: Source database '{SOURCE_DB}' not found!")
        sys.exit(1)

    if os.path.exists(TARGET_DB):
        print(f"⚠️  Target database '{TARGET_DB}' already exists.")
        choice = input("   Overwrite? (y/N): ")
        if choice.lower() != 'y':
            print("   Operation cancelled.")
            sys.exit(0)

    try:
        # Perform file copy
        shutil.copy2(SOURCE_DB, TARGET_DB)
        print(f"✅ Database copied successfully.")
        
        # Verify Integrity
        conn_src = sqlite3.connect(SOURCE_DB)
        conn_tgt = sqlite3.connect(TARGET_DB)
        
        cursor_src = conn_src.cursor()
        cursor_tgt = conn_tgt.cursor()
        
        # Check Table Counts as a proxy for integrity
        tables = ["questions", "reviews", "users", "user_highlights"]
        
        print("\n🔍 Verifying Data Integrity:")
        all_good = True
        
        for table in tables:
            try:
                cursor_src.execute(f"SELECT COUNT(*) FROM {table}")
                count_src = cursor_src.fetchone()[0]
                
                cursor_tgt.execute(f"SELECT COUNT(*) FROM {table}")
                count_tgt = cursor_tgt.fetchone()[0]
                
                match = "✅ Match" if count_src == count_tgt else "❌ MISMATCH"
                print(f"   - {table}: {count_src} -> {count_tgt} [{match}]")
                
                if count_src != count_tgt:
                    all_good = False
            except sqlite3.OperationalError:
                print(f"   - {table}: Table missing in source (Skipping)")

        conn_src.close()
        conn_tgt.close()

        if all_good:
            print("\n🎉 Clone Success! You may now safely develop on 'quiz_v2.db'.")
        else:
            print("\n⚠️  Clone Integrity Warning! Check mismatches.")

    except Exception as e:
        print(f"\n❌ Error during cloning: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clone_database()
