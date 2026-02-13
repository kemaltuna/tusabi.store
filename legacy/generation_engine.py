#!/usr/bin/env python3
"""
Block-Based Question Generation Engine (PROD-SAFE)

Orchestrates the 5-stage pipeline:
1. Retrieval (Main + Update)
2. Draft (Fast Model) - Creates question skeleton
2b. Reconcile (Update Logic) - Checks if update evidence overrides main
3. Critique (Reasoning Model) - Validates logic & suggests comparison siblings
4. Explanation (Deep Model) - Generates block-based structured content
5. Validation & Repair - Enforces Pydantic schema
"""

import os
import sys
import json
import time
import argparse
from typing import Optional

# Local imports
import database
from evidence_retriever import SimpleEvidenceRetriever
from gemini_client import GeminiClient
from openai_client import OpenAIClient
from schema_validator import validate_llm_output
from utils.medquiz_library import get_library

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class GenerationEngine:
    def __init__(self, dry_run: bool = False, provider: str = "gemini"):
        self.dry_run = dry_run
        self.provider = provider.lower()
        
        if self.provider == "openai":
            print("🤖 Using Provider: OpenAI (ChatGPT)")
            self.client = OpenAIClient()
        else:
            print("🤖 Using Provider: Google Gemini")
            self.client = GeminiClient()
            
        # Retriever disabled by default or optional
        self.retriever = None
        try:
             self.retriever = SimpleEvidenceRetriever(base_path="preprocessed_chunks")
        except:
             print("⚠️ Retriever not initialized (Optional mode)")

    def generate_question(self, concept: str, topic: str, source_material: str = "Küçük Stajlar", difficulty: int = 3, evidence_override: str = None, all_topics: list = None, source_pdf: str = None, category: str = None) -> dict:
        """
        Orchestrates the generation pipeline.
        
        Args:
            concept (str): The specific concept/term to generate a question about
            topic (str): The broader topic label (e.g. "Acute Kidney Injury")
            source_material (str): The source book/lecture (e.g. "Dahiliye")
            difficulty (int): 1-5
            evidence_override (str): Optional raw text to use instead of retrieval
            all_topics (list): Optional list of all selected topics for filtering/selection
            source_pdf (str): Optional path to source PDF for multimodal (or direct) processing
            category (str): Optional Main Header / Category for strict scoping
        """
        print(f"\n🚀 [Engine] Starting generation for: '{concept}'")
        print(f"   Topic: {topic} | Source: {source_material} | Category: {category}")
        
        main_evidence = ""
        update_evidence = ""
        combined_evidence = ""
        evidence_scope = {}
        uploaded_file = None

        # --- Stage 1: Retrieval or File Upload ---
        if source_pdf:
            print(f"📚 [1/5] Using PDF Source: {source_pdf}")
            # Upload PDF
            uploaded_file = self.client.upload_file(source_pdf)
            # We don't have text evidence yet, so main_evidence remains empty/minimal
            # The model sees the file directly.
            evidence_scope = {
                "source": "PDF_CHAPTER",
                "filename": os.path.basename(source_pdf),
                "multimodal": True
            }
        elif evidence_override:
            print("📚 [1/5] Processing Provided Evidence Override...")
            # P0 Fix: Even with override, we should filter if it's too big
            # Bumped limit to 150k chars (Largest file is ~98k) to avoid brittle snippeting
            if self.retriever and len(evidence_override) > 150000:
                print("   🔍 Snippetting large override content...")
                keywords = [concept] + concept.replace('-', ' ').replace('_', ' ').split()
                keywords = list(set([k for k in keywords if len(k) > 2]))
                # Search using the retriever's logic
                snippets = self.retriever._keyword_search(evidence_override, keywords)
                if snippets:
                    main_evidence = "\n\n---\n\n".join(snippets)
                else:
                    # Still fallback to head if no keywords, but maybe more than before
                    main_evidence = evidence_override[:10000]
            else:
                main_evidence = evidence_override
            
            combined_evidence = main_evidence
            # Mock scope for later
            evidence_scope = {"source": "OVERRIDE", "chunks": 1, "filtered": (len(evidence_override) > 10000)}
        elif self.retriever:
            print("📚 [1/5] Retrieving Evidence...")
            # STRICT SCOPING: Pass source_material and topic to retriever
            evidence_pack = self.retriever.get_evidence_pack(concept, topic, source_material=source_material)
            main_evidence = evidence_pack.get_main_text()
            update_evidence = evidence_pack.get_update_text()
            combined_evidence = main_evidence + "\n\n" + update_evidence
            
            if not evidence_pack.main_evidence:
                print(f"⚠️ No evidence found for {concept}, skipping.")
                return None
            
            evidence_scope = {
                "source": source_material,
                "topic": topic,
                "main_chunks": len(evidence_pack.main_evidence),
                "update_chunks": len(evidence_pack.update_evidence)
            }
        else:
            print("❌ Error: No Evidence provided and Retriever is disabled.")
            return None

        # --- Synchronization Check & Topic Normalization ---
        # 1. Fetch ALL topics for this source from the Library regardless of what was passed
        try:
            lib = get_library()
            library_topics = [t['topic'] for t in lib.get_topics(source_material)]
            if library_topics:
                print(f"🔄 [Sync] Loaded {len(library_topics)} canonical topics for {source_material}")
                
                # 2. Try to map the incoming 'topic' (which might be a simple PDF title) to a canonical one
                #    STRICT SCOPING: Pass source and main_header to limit search
                normalized_topic = database.normalize_topic_name(database.get_db_connection(), topic, source_material=source_material, main_header=category)
                
                # Double check against the list we just loaded
                if normalized_topic in library_topics:
                    if normalized_topic != topic:
                        print(f"   ✨ Topic Auto-Correction: '{topic}' -> '{normalized_topic}'")
                        topic = normalized_topic  # OVERWRITE request topic with canonical one
                
                # 3. Update all_topics to be the full library list if it's small/empty
                if not all_topics or len(all_topics) <= 1:
                    all_topics = library_topics
            else:
                 print(f"   ⚠️ No library topics found for source: {source_material}")

        except Exception as e:
            print(f"   ⚠️ Failed to sync with library topics: {e}")

        # --- Stage 2: Draft ---
        # --- Stage 2: Draft (With Deduplication Loop) ---
        print("📝 [2/5] Drafting Question (With Deduplication Check)...")
        
        # Fetch existing questions context once
        existing_questions_ctx = []
        try:
            # SCOPE LOGIC (User Request):
            # Default: Check entire Category (Main Header)
            # Exception: Specific Massive volumes -> Check Topic (Subheader) only
            
            check_by_topic = False
            # Check against the 3 specific massive folders defined by user
            if source_pdf:
                # Normalize path for check
                pdf_path_str = str(source_pdf).replace("\\", "/") 
                massive_folders = [
                    "output_kadin_dogum_f1", 
                    "output_kadin_dogum_f2", 
                    "output_dahiliye_f2"
                ]
                if any(folder in pdf_path_str for folder in massive_folders):
                     check_by_topic = True
            
            if check_by_topic:
                print(f"   Context Scope: Narrow (Topic-only) for massive volume file")
                existing_questions_ctx = database.get_questions_for_duplicate_check(
                    topic=topic, 
                    source_material=source_material, 
                    limit=2000 # High limit for massive topic
                )
            else:
                print(f"   Context Scope: Broad (Category/Main Header)")
                existing_questions_ctx = database.get_questions_for_duplicate_check(
                    topic=None, # IGNORE TOPIC
                    source_material=source_material, 
                    category=category,
                    limit=2000 # High limit for full category
                )
                
            print(f"   Context: Found {len(existing_questions_ctx)} existing questions for duplicate check.")
        except Exception as e:
            print(f"   ⚠️ Failed to fetch existing questions: {e}")

        draft = None
        retry_count = 0
        max_retries = 2
        
        while retry_count <= max_retries:
            # Pass uploaded_file if present
            draft = self.client.draft_question(concept, combined_evidence, topic, media_file=uploaded_file)
            
            # P0 Logic: Insufficient Evidence Check
            if draft.get("insufficient_evidence"):
                print(f"⚠️ STOPPING: Insufficient Evidence. Reason: {draft.get('reason')}")
                return None

            print(f"   Draft [{retry_count+1}/{max_retries+1}]: {draft['question_text'][:60]}...")
            
            # DUPLICATE CHECK
            if existing_questions_ctx:
                dup_result = self.client.check_for_duplicates(draft, existing_questions_ctx)
                if dup_result.get("is_duplicate"):
                    print(f"   ⚠️ DUPLICATE DETECTED (Similar to ID: {dup_result.get('similar_to_id')})")
                    print(f"   Reason: {dup_result.get('reason')}")
                    retry_count += 1
                    if retry_count <= max_retries:
                        print("   🔄 Retrying generation...")
                        continue
                    else:
                        print("   ❌ Max retries reached. Using last draft despite duplicate warning.")
                else:
                    print("   ✅ Duplicate Check Passed.")
                    break
            else:
                 break # No existing questions, skip check

        
        # NEW GATING STEP: Topic Alignment Check
        print("🛡️ [2.5/5] Checking Topic Alignment (Optimized: Warning Only)...")
        gate_result = self.client.check_topic_alignment(
            draft['question_text'], 
            # Need to get correct option text from id
            next((o['text'] for o in draft['options'] if o['id'] == draft['correct_option_id']), "Unknown"),
            target_topic=topic
        )
        
        # P0 Fix: Do NOT abort on topic drift. User provided the content, so trust the content.
        # Just log it for analytics.
        if not gate_result.get('topic_match', False):
             print(f"⚠️ TOPIC DRIFT DETECTED: Draft drifted to {gate_result.get('predicted_topic')}")
             print(f"   Reason: {gate_result.get('reason')}")
             # return None # Hard Abort DISABLED
        else:
             print(f"   Topic Gate Passed! Predicted: {gate_result.get('predicted_topic')}")
        
        time.sleep(1)
        
        # --- Stage 2b: Reconcile Updates ---
        print("🔄 [2b/5] Reconciling Updates...")
        updates_applied = []
        if update_evidence and not uploaded_file: # Only if using retrieved text
            updates_applied = self.client.reconcile_updates(main_evidence, update_evidence)
            if updates_applied:
                print(f"   Updates Found: {len(updates_applied)} applied.")
                # Gating: Check for unresolved conflicts
                for update in updates_applied:
                    if update.get('priority') == 'unresolved_conflict':
                        print(f"⚠️ STOPPING: Unresolved conflict detected in {update.get('source_file')}")
                        print(f"   Reason: {update.get('change_summary')}")
                        return None # Abort generation - Conflict is real safety issue
            else:
                print("   No conflicting updates found.")
        else:
            print("   No update evidence present (or using PDF source).")
        time.sleep(1)

        # --- Stage 3: Critique ---
        print("🔍 [3/5] Critiquing & Planning...")
        # Critique uses DRAFT content primarily. 
        # TODO: If we want critique to see the PDF, we need to pass it. 
        # But 'critique_question' currently assumes text evidence. 
        # We pass empty evidence if it's PDF, relying on the draft's coherence.
        critique = self.client.critique_question(draft, combined_evidence)
        siblings = critique.get("sibling_suggestions", [])
        print(f"   Siblings Suggestion: {siblings}")
        time.sleep(1)

        # --- Stage 4: Explanation Generation ---
        print("🧠 [4/5] Generating Deep Blocks...")
        explanation_json = self.client.generate_explanation_blocks(
            draft=draft, 
            critique=critique, 
            updates=updates_applied, 
            evidence=combined_evidence,
            source_material=source_material,
            topic=topic,
            media_file=uploaded_file
        )
        
        # Assemble preliminary object
        # P0 Fix: Prevent "question drift". 
        # Source of truth for Question/Options/CorrectID is the DRAFT.
        # Explanation stage provides blocks & reasoning, but should not override the question structure.
        
        candidate_data = explanation_json 
        
        # Merge Draft Fields (Force Overwrite)
        candidate_data['question_text'] = draft.get('question_text')
        candidate_data['options'] = draft.get('options')
        candidate_data['correct_option_id'] = draft.get('correct_option_id')
        candidate_data['correct_option_id'] = draft.get('correct_option_id')
        
        # FIX: Restore concept_tag by adding it to tags list
        # We don't verify against schema here (validate_llm_output does), but we ensure it's in the tags list
        concept_tag_draft = draft.get('concept_tag')
        if concept_tag_draft:
             if 'tags' not in candidate_data: candidate_data['tags'] = []
             if concept_tag_draft not in candidate_data['tags']:
                 candidate_data['tags'].append(concept_tag_draft)

        
        if 'explanation' not in candidate_data:
             candidate_data['explanation'] = {}
             
        # P0 Fix: Deterministic Updates Flags
        # Set by engine based on actual retrieval results, not LLM hallucination
        candidate_data['explanation']['update_checked'] = bool(update_evidence)
        candidate_data['explanation']['updates_applied'] = updates_applied
        
        # New Feature: Intelligent Multi-Topic Association
        target_topic = topic
        
        # P0 Fix: Do NOT auto-associate if it's a "Chunk" topic 
        # because the user explicitly wants it in that chunk.
        is_chunk = topic.startswith("Chunk:")
        
        # Optimization: If we already enforced a library topic at the start, 
        # treat it as "Enforced" and skip the extra LLM call.
        is_library_enforced = (all_topics and topic in all_topics)
        
        if all_topics and len(all_topics) > 1 and not is_chunk and not is_library_enforced:
            print(f"🧐 [Intelligent Selection] Picking best topic from {len(all_topics)} candidates...")
            best_topic = self.client.select_best_topic(candidate_data['question_text'], all_topics)
            if best_topic in all_topics:
                print(f"   🎯 Selected: {best_topic}")
                target_topic = best_topic
            else:
                print(f"   ⚠️ Selection failed or returned invalid topic: {best_topic}. Falling back to default: {topic}")
        elif is_chunk:
            print(f"📌 [Enforced] Using explicit Chunk topic: {topic}")
        elif is_library_enforced:
            print(f"📌 [Enforced] Using strict Library topic: {topic}")
        else:
            print(f"📌 [Enforced] Using target topic: {topic}")
        
        # New Traceability Fields
        candidate_data['topic'] = target_topic  # Picked topic
        candidate_data['source_material'] = source_material  # P0 Fix: Force source to match User Request
        candidate_data['requested_topic'] = topic
        candidate_data['requested_source_material'] = source_material
        candidate_data['category'] = category # Persist category
        candidate_data['generated_topic_predicted'] = gate_result.get('predicted_topic')
        candidate_data['topic_gate_passed'] = gate_result.get('topic_match')
        candidate_data['evidence_scope'] = evidence_scope

        # --- Stage 5: Validation & Repair ---
        print("✅ [5/5] Validating Schema...")
        try:
            validated = validate_llm_output(candidate_data)
            print("   Schema Valid! 🎉")
        except ValueError as e:
            print(f"⚠️ Schema Error: {e}")
            print("🔧 Attempting Auto-Repair (1 Pass Only)...")
            try:
                # Feed the error back to the model
                repaired_json = self.client.repair_json(json.dumps(candidate_data), str(e))
                validated = validate_llm_output(repaired_json)
                print("   Repair Successful! 🔧✅")
            except Exception as repair_error:
                print(f"❌ Repair Failed: {repair_error}")
                if self.dry_run:
                    return candidate_data # Return raw data in dry run for debugging
                return None # Skip persistence if validation fails

        return validated.to_db_dict()

    def persist_question(self, question_data: dict):
        if self.dry_run:
            print("🔒 Dry Run - Not saving to DB.")
            return
        
        if not question_data:
            print("❌ No valid data to save.")
            return

        try:
            # question_data is already formatted for DB by to_db_dict()
            qid = database.add_question(question_data)
            print(f"💾 Saved Question ID: {qid}")
        except Exception as e:
            print(f"❌ Database Error: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concept", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--source", default="Küçük Stajlar")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = GenerationEngine(dry_run=args.dry_run)
    try:
        q = engine.generate_question(args.concept, args.topic, source_material=args.source)
        if q:
            engine.persist_question(q)
            # Preview blocks
            print("\nPreview Blocks:")
            if "explanation_data" in q and "blocks" in q["explanation_data"]:
                for b in q['explanation_data']['blocks']:
                    print(f"- [{b['type']}] {b.get('title', '')}")
                
    except Exception as e:
        print(f"\n❌ Pipeline Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
