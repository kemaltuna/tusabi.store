import sys
import os
import time
import logging

sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/new_web_app")
from dotenv import load_dotenv
load_dotenv("/home/yusuf-kemal-tuna/medical_quiz_app/.env")

from backend import database
from core.gemini_client import GeminiClient
from core.deduplicator import save_concept_embedding

def backfill():
    conn = database.get_db_connection()
    c = conn.cursor()
    
    # Get all concept tags from questions
    c.execute("SELECT tags, explanation_data, correct_answer_index, options, question_text, source_material, category FROM questions")
    rows = c.fetchall()
    
    
    client = GeminiClient()
    count = 0
    updated = 0
    
    print(f"Checking {len(rows)} questions for missing embeddings...")
    
    for row in rows:
        tags_raw, explanation_data, correct_idx, options_raw, q_text, source, category = row
        
        # We need to construct the signature "Answer: ... | Question: ..."
        # Extract correct answer text
        try:
            import json
            options = json.loads(options_raw) if options_raw else []
            correct_text = ""
            if 0 <= correct_idx < len(options):
                opt = options[correct_idx]
                correct_text = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            
            signature = f"Answer: {correct_text} | Question: {q_text}"
            
            # Use topic/category
            topic = category # Fallback
            
            # Check if embedding exists for this EXACT signature
            c.execute("SELECT 1 FROM concept_embeddings WHERE concept_text = ?", (signature,))
            if c.fetchone():
                print(f"Skipping (Already exists): {signature[:50]}...")
                continue

            # Check if concept (old style) exists? 
            # If so, we might want to update it to new signature? 
            # Yes, save_concept_embedding does INSERT OR REPLACE.
            
            # Rate limit protection (Increased to avoid 429)
            time.sleep(2.0) 
            
            emb = client.get_text_embedding(signature)
            if emb:
                # This will overwrite if primary key matches (concept, topic)
                # If signature changed (added Answer: ...), it's a new row?
                # The table PK is usually (topic, concept).
                # If "concept" column holds the signature string, then a new signature = new row.
                # Old signature (just concept text) remains as a zombie row or valid alias.
                save_concept_embedding(topic, signature, emb)
                updated += 1
                if updated % 10 == 0:
                    print(f"Updated {updated} embeddings...")
            
        except Exception as e:
            print(f"Error processing row: {e}")
            
    print(f"Backfill complete. Updated {updated} signatures.")

if __name__ == "__main__":
    backfill()
