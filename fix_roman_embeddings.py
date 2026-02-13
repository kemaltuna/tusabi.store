
import sqlite3
import json
import logging
import re
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from new_web_app.backend.database import (
    _expand_roman_answer_text, 
    _extract_correct_answer_text, 
    safe_json_parse,
    save_concept_embedding,
    _extract_concept_tag
)
from new_web_app.core.gemini_client import GeminiClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fix_roman_embeddings():
    conn = sqlite3.connect("shared/data/quiz_v2.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Fetch all questions
    c.execute("SELECT id, topic, question_text, options, correct_answer_index, tags FROM questions")
    rows = c.fetchall()
    
    print(f"🔍 Scanning {len(rows)} questions for raw Roman Numeral answers...")
    
    client = GeminiClient()
    fixed_count = 0
    
    for row in rows:
        qid = row['id']
        question_text = row['question_text']
        options = safe_json_parse(row['options'], [])
        correct_idx = row['correct_answer_index']
        tags = safe_json_parse(row['tags'], [])
        topic = row['topic']
        
        # Get raw answer text
        raw_answer = _extract_correct_answer_text(options, correct_idx)
        if not raw_answer:
            continue
            
        # Check if it looks like a Roman combination (e.g. "I ve II", "Yalnız I")
        # Regex: start/end with roman numerals or simple connectors
        is_roman_style = re.search(r"\b(I|II|III|IV|V)\b", raw_answer) and len(raw_answer) < 30
        
        if is_roman_style:
            # Try to expand
            expanded = _expand_roman_answer_text(question_text, raw_answer)
            
            # If expanded is different and longer, it means we found the content
            if expanded and expanded != raw_answer and len(expanded) > len(raw_answer):
                print(f"\n[Q{qid}] Found Roman Answer: '{raw_answer}'")
                print(f"    -> Expanded: '{expanded}'")
                
                # Check if we need to regenerate embedding for this "Expanded Answer"
                # The user asked: "detect and re-run embedding"
                # In our system, we embed 'concept' primarily. But if deduplication uses Answer, we might need to Embed the ANSWER?
                # Actually, our deduplicator uses `check_duplicate_hybrid` which embeds the CONCEPT.
                # However, `build_qa_signature` uses the answer.
                
                # If the Concept ITSELF was generic (e.g. "Hypokalemia"), the differentiator is the Answer.
                # If we want to support "Semantic Answer Matching", we should embed the ANSWER text too?
                # Currently we store `concept_embeddings` (Topic -> Concept).
                # Maybe the user means the 'concept' extracted was just "I ve II"? No, unlikely.
                
                # Let's assume the user wants us to ensure the 'qa_signature' or deduplication logic has the FULL text.
                # BUT, the user said "Questions have embeddings". 
                # If they mean `concept_embeddings` table, we should check if any concept there is "I ve II".
                
                fixed_count += 1
                
                # Fix: We don't verify embedding here because Questions don't have embeddings column. 
                # But we can verify if a concept embedding exists for the *Expanded Answer* if we treat it as a concept? 
                # Probably not.
                
                # Logic: The user likely wants to Ensure that FUTURE logic sees the expanded text.
                # Since `_expand_roman_answer_text` is dynamic in `database.py`, simply having it fixed there (which I verified it is) might be enough.
                # BUT, if the question "options" text ITSELF is "I ve II", we don't change that (it's what the user sees).
                # The expansion happens in `build_qa_signature`.
                
                # So the query is: Does the system *currently* have embeddings for these?
                # Our system embeds CONCEPTS. Let's check if there are any GARBAGE concepts in `concept_embeddings` like "I ve II".
                
    # Check for garbage concepts in embeddings table
    print("\n🔍 Checking `concept_embeddings` for Roman Numeral garbage...")
    c.execute("SELECT id, topic, concept_text FROM concept_embeddings")
    emb_rows = c.fetchall()
    garbage_count = 0
    for r in emb_rows:
        txt = r['concept_text']
        if re.fullmatch(r"^(I|II|III|IV|V|ve|veya|Yalnız|Yalniz|Sadece|\s)+$", txt, re.IGNORECASE):
             print(f"🗑️ Garbage Concept Embedding Found: [{r['id']}] {txt}")
             garbage_count += 1
             # We should probably delete these?
             
    print(f"\nSummary: Found {fixed_count} questions with Roman answers that CAN be expanded.")
    print(f"Summary: Found {garbage_count} garbage embeddings in DB.")
    
    conn.close()

if __name__ == "__main__":
    fix_roman_embeddings()
