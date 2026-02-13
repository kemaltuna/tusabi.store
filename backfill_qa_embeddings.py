"""
Backfill QA Embeddings Script

Generates embeddings for existing questions based on their `qa:` tags.
Stores in `concept_embeddings` table for semantic deduplication.
"""

import sqlite3
import json
import logging
import sys
import os

sys.path.append(os.getcwd())

from new_web_app.core.gemini_client import GeminiClient
from new_web_app.backend.database import save_concept_embedding, safe_json_parse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def backfill_qa_embeddings(limit=500, dry_run=False):
    conn = sqlite3.connect("shared/data/quiz_v2.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get existing embeddings to avoid re-processing
    c.execute("SELECT concept_text FROM concept_embeddings")
    existing = set(r['concept_text'] for r in c.fetchall())
    print(f"📦 Existing embeddings: {len(existing)}")
    
    # Fetch questions with qa: tags
    c.execute("""
        SELECT id, topic, tags 
        FROM questions 
        WHERE tags LIKE '%qa:%' 
        ORDER BY id DESC 
        LIMIT ?
    """, (limit * 3,))  # Fetch more to account for already-embedded
    rows = c.fetchall()
    
    print(f"🔍 Scanning {len(rows)} questions with qa: tags...")
    
    client = GeminiClient()
    processed = 0
    skipped = 0
    
    for row in rows:
        if processed >= limit:
            break
            
        tags = safe_json_parse(row['tags'], [])
        topic = row['topic']
        
        for tag in tags:
            if tag.startswith("qa:"):
                qa_text = tag.replace("qa:", "")
                
                # Skip if already embedded
                if qa_text in existing:
                    skipped += 1
                    continue
                
                print(f"[Q{row['id']}] Embedding: {qa_text[:60]}...")
                
                if dry_run:
                    processed += 1
                    continue
                
                try:
                    embedding = client.get_text_embedding(qa_text)
                    if embedding:
                        save_concept_embedding(topic, qa_text, embedding)
                        existing.add(qa_text)  # Prevent double-processing
                        processed += 1
                        if processed % 10 == 0:
                            print(f"  ✅ Progress: {processed}/{limit}")
                    else:
                        print(f"  ⚠️ Failed to embed")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                    
    conn.close()
    print(f"\n✅ Done. Processed: {processed}, Skipped (existing): {skipped}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500, help="Max embeddings to generate")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    args = parser.parse_args()
    
    backfill_qa_embeddings(limit=args.limit, dry_run=args.dry_run)
