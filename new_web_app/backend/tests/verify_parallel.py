
import sys
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# Add ROOT to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.routers import admin
from backend.database import get_db_connection
from backend.helpers import get_manifest_map

def test_parallel_execution():
    print("🚀 Testing Parallel Generation Logic...")
    
    # 1. Setup Dummy Job
    conn = get_db_connection()
    c = conn.cursor()
    topic = "Akut Böbrek Yetmezliği" # Use a topic we know exists or generic
    # Actually need a topic that resolves to a PDF.
    # From Helpers test: "Hematoloji" -> "04_HEMATOLOJİ.pdf"?
    # Let's try to query helpers to get a valid topic.
    # from helpers import get_manifest_map (Used global import)
    m = get_manifest_map()
    if not m:
        # Try to scan manually if map empty (maybe caching issue in script env)
        print("⚠️ Manifest map empty, scanning...")
        # (Scanning logic skipped, assuming standard topics exist)
        pass
    
    # Pick a random topic if exists
    if m:
        topic = list(m.keys())[0]
    
    print(f"🎯 Using Topic: {topic}")
    
    c.execute(
        "INSERT INTO generation_jobs (topic, source_material, status, questions_generated, created_at) "
        "VALUES (?, ?, 'pending', 0, ?) RETURNING id",
        (topic, "Test Source", datetime.now().isoformat()),
    )
    inserted = c.fetchone()
    job_id = int(inserted["id"]) if inserted else None
    conn.commit()
    conn.close()
    
    print(f"   Job ID: {job_id}")
    
    # 2. Run Generation (Blocking)
    # We call the admin function directly.
    # It will spawn threads.
    try:
        admin.run_generation_job(job_id, topic, "Test Source", count=2, difficulty=3)
    except Exception as e:
        print(f"❌ Execution failed: {e}")
        return
        
    # 3. Verify Result
    conn = get_db_connection()
    row = conn.execute("SELECT status, questions_generated, error_message FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    
    print(f"✅ Job Finished.")
    print(f"   Status: {row['status']}")
    print(f"   Generated: {row['questions_generated']}")
    print(f"   Error: {row['error_message']}")

if __name__ == "__main__":
    test_parallel_execution()
