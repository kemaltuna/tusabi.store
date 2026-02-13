import difflib
import logging
import json
import math
from typing import List, Optional
from backend.database import get_topic_concepts_data, get_category_concepts_data, save_concept_embedding

def cosine_similarity(v1, v2):
    """Compute cosine similarity between two vectors."""
    if not v1 or not v2:
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
        
    return dot_product / (norm_a * norm_b)

def check_duplicate_hybrid(
    new_concept: str, 
    topic: str, 
    gemini_client,  # GeminiClient instance
    category: Optional[str] = None,
    source_material: Optional[str] = None,
    threshold_fuzzy: float = 0.90, 
    threshold_semantic: float = 0.85,
    new_answer: Optional[str] = None  # NEW: Answer text for QA-based embedding
) -> bool:
    """
    Checks for duplicates using a 3-layer hybrid approach.
    
    Now uses "Concept + Answer" (QA signature) for semantic comparison to allow
    different questions about the same concept (e.g., treatment vs side effects).
    
    Scope:
    - If category and source_material are provided, checks duplicates across the ENTIRE Category.
    - Otherwise, checks only within the specific Topic.
    """
    
    # Build QA signature for embedding (if answer provided)
    if new_answer:
        # Caller is expected to provide the full formatted signature
        qa_signature = new_answer
    else:
        qa_signature = new_concept  # Fallback to old behavior
    
    # 1. Fetch Existing Data (Topic vs Category Scope)
    # Now returns QA strings from qa: tags
    if category and source_material:
        logging.info(f"🔎 Checking duplicate in Category scope: {category} ({source_material})")
        existing_concepts = get_category_concepts_data(source_material, category)
    else:
        logging.info(f"🔎 Checking duplicate in Topic scope: {topic}")
        existing_concepts = get_topic_concepts_data(topic)
    
    if not existing_concepts:
        return False
        
    concepts_to_embed = []
    
    qa_signature_lower = qa_signature.lower()
    
    # 2. Check Fuzzy & Exact (on full QA signature)
    for record in existing_concepts:
        existing_text = record['concept']  # Now this is the full QA string
        existing_lower = existing_text.lower()
        
        # Exact
        if existing_lower == qa_signature_lower:
            logging.info(f"🛑 Duplicate found (Exact): '{qa_signature[:50]}...'")
            return True
            
        # Fuzzy
        ratio = difflib.SequenceMatcher(None, qa_signature_lower, existing_lower).ratio()
        if ratio > threshold_fuzzy:
            logging.info(f"🛑 Duplicate found (Fuzzy {ratio:.2f}): '{qa_signature[:50]}...'")
            return True
        
        # Collect for semantic check if missing embedding
        if record['embedding'] is None:
            concepts_to_embed.append(record['concept'])

    # 3. Semantic Check
    # Embed the full QA signature (not just concept)
    try:
        logging.info(f"Generating embedding for QA: {qa_signature[:60]}...")
        new_embedding = gemini_client.get_text_embedding(qa_signature)
        if not new_embedding:
            logging.warning("⚠️ Could not generate embedding for QA signature. Skipping semantic check.")
            return False

        # Store embedding for the QA signature to improve future checks
        try:
            save_concept_embedding(topic, qa_signature, new_embedding)
        except Exception as e:
            logging.warning(f"⚠️ Failed to save embedding for QA '{qa_signature[:50]}': {e}")
            
        # Check against existing VALID embeddings
        for record in existing_concepts:
            if record['embedding']:
                sim = cosine_similarity(new_embedding, record['embedding'])
                if sim > threshold_semantic:
                    logging.info(f"🛑 Duplicate found (Semantic {sim:.2f}): QA match")
                    return True
        
        # 4. Lazy Backfill (Optional / Best Effort)
        # DISABLE runtime backfill to prevent 429 quota errors during parallel generation
        max_backfill = 0 
        count = 0
        
        if concepts_to_embed:
            logging.info(f"Lazy backfill: Generating embeddings for {len(concepts_to_embed)} existing QA signatures (limit {max_backfill})...")
        
        for old_qa in concepts_to_embed:
            if count >= max_backfill:
                break
            
            # Generate
            emb = gemini_client.get_text_embedding(old_qa)
            if emb:
                # Save to DB for next time
                save_concept_embedding(topic, old_qa, emb)
                # Check similarity NOW
                sim = cosine_similarity(new_embedding, emb)
                if sim > threshold_semantic:
                    logging.info(f"🛑 Duplicate found (Semantic/Backfill {sim:.2f}): QA match")
                    return True
                count += 1
                
    except Exception as e:
        logging.error(f"Semantic duplicate check error: {e}")
        
    return False

