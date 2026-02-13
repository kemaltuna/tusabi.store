import logging
import time
import json
import re
import os
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from .generation_engine import GenerationEngine
from core.deduplicator import check_duplicate_hybrid
from .gemini_client import GeminiClient
from backend import database

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_ROOT = PROJECT_ROOT / "shared"

def _resolve_pdf_path(path_value: str) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return str(path) if path.exists() else None
    for base in (PROJECT_ROOT, SHARED_ROOT):
        candidate = (base / path).resolve()
        if candidate.exists():
            return str(candidate)
    return None

def _normalize_concept_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()) if text else ""

def _is_specific_concept(text: str) -> bool:
    if not text:
        return False
    words = re.findall(r"\w+", text)
    return len(words) >= 8 or len(text) >= 80

def _strip_part_suffix(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s*\(\s*part\s*\d+\s*\)\s*$", "", text, flags=re.IGNORECASE).strip()

def _is_premerged_pdf(path_value: str) -> bool:
    if not path_value:
        return False
    try:
        path = Path(path_value)
    except Exception:
        return False
    name = path.name.lower()
    return "temp_chunks" in str(path) or "chunk" in name or "merged" in name

def _fetch_existing_concepts(source_material: str, category: str) -> list:
    if not source_material or not category:
        return []
    base_category = _strip_part_suffix(category)
    like_pattern = f"{base_category}%"
    conn = database.get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT tags FROM questions WHERE source_material = ? AND category LIKE ?",
            (source_material, like_pattern)
        )
        concepts = set()
        for row in c.fetchall():
            tags_raw = row[0]
            if not tags_raw:
                continue
            try:
                tags = json.loads(tags_raw)
            except Exception:
                continue
            for tag in tags:
                if isinstance(tag, str) and tag.startswith("concept:"):
                    concept_text = tag.replace("concept:", "").strip()
                    if concept_text:
                        concepts.add(concept_text)
        return sorted(concepts)
    finally:
        conn.close()

def _add_unique_concepts(raw, seen, existing_norm):
    unique = []
    reasons = {}
    for item in raw or []:
        concept = ""
        reason = ""
        if isinstance(item, dict):
            concept = str(item.get("concept", "")).strip()
            reason = str(item.get("reason", "")).strip()
        elif isinstance(item, str):
            concept = item.strip()
        else:
            continue
        if not concept:
            continue
        key = _normalize_concept_text(concept)
        if not key or key in seen or key in existing_norm:
            continue
        seen.add(key)
        unique.append(concept)
        if reason:
            reasons[concept] = reason
    return unique, reasons

def _sanitize_topic_list(topics) -> list[str]:
    values = topics if isinstance(topics, list) else [topics]
    clean: list[str] = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        topic = re.sub(r"\s+", " ", value.strip())
        if not topic or topic in seen:
            continue
        seen.add(topic)
        clean.append(topic)
    return clean

def run_generation_batch(payload):
    """Run generation synchronously without background queue tracking."""
    return _process_generation_batch(payload, job_id=None, persist_progress=False)

import threading

JOB_LOCK = threading.Lock()

def process_generation_batch_job(job_id, payload):
    """Worker-friendly entrypoint: no artificial delay, no extra locking."""
    return _process_generation_batch(payload, job_id=job_id, persist_progress=True)

def process_generation_batch(job_id, payload):
    """Queue-compatible wrapper. Enforces sequential execution."""
    with JOB_LOCK:
        return process_generation_batch_job(job_id, payload)

def _process_generation_batch(payload, job_id=None, persist_progress=True):
    """
    Executes a 'generation_batch' job.
    Payload: { 'topic': str, 'source_material': str, 'count': int, 'difficulty': int, 'source_pdf': str }
    """
    conn = database.get_db_connection() if persist_progress else None
    c = conn.cursor() if conn else None

    def _job_update(sql, params=()):
        if not persist_progress or c is None:
            return
        c.execute(sql, params)
        conn.commit()

    def _job_fetchone(sql, params=()):
        if not persist_progress or c is None:
            return None
        c.execute(sql, params)
        return c.fetchone()
    
    try:
        topic_label = payload.get('topic')
        job_tag = job_id if job_id is not None else "direct"
        # Default fallback changed to ASCII key to match taxonomy
        # Note: job_type is not defined in this scope, assuming it's meant to be added elsewhere or is a placeholder.
        logging.info(f"⚙️ Processing Job {job_id}: generation_batch") 

        # Ensure UI can show a real "processing" state even when the job runner
        # claimed the job without touching the payload processor.
        if persist_progress and job_id is not None:
            _job_update(
                "UPDATE background_jobs SET status = 'processing', updated_at = ? WHERE id = ?",
                (datetime.now(), job_id),
            )
        
        # Extract payload variables
        count = payload.get("count", 10)
        # topic_label is already extracted above, but re-extracting as per instruction
        topic_label = payload.get("topic") 
        source_material = payload.get("source_material", 'Kucuk_Stajlar') # Retain original default
        difficulty = payload.get("difficulty", 3) # Retain original default
        file_content = payload.get('file_content') # Deprecated (text extraction removed)
        source_pdf = payload.get("source_pdf")
        main_header = payload.get('main_header') # Strict Scope Context
        
        # Important: Deduplication needs category
        category = payload.get("category")
        if not category and main_header:
             # Fallback: Use main_header as category (typical in this app)
             category = main_header
        
        all_topics = payload.get('all_topics', [topic_label]) # Fallback to single if not present
        
        # 0. Background Merging Logic
        source_pdfs_list = payload.get('source_pdfs_list')
        if source_pdf:
            resolved_source_pdf = _resolve_pdf_path(source_pdf)
            if resolved_source_pdf:
                source_pdf = resolved_source_pdf
            else:
                logging.warning(f"⚠️ [Job {job_id}] source_pdf not found: {source_pdf}")

        resolved_pdfs_list = []
        if source_pdfs_list:
            for p in source_pdfs_list:
                resolved = _resolve_pdf_path(p)
                if resolved:
                    resolved_pdfs_list.append(resolved)
                else:
                    logging.warning(f"⚠️ [Job {job_id}] Missing PDF during merge: {p}")
            source_pdfs_list = resolved_pdfs_list

        if source_pdfs_list and not source_pdf:
            source_pdf = source_pdfs_list[0]
            logging.info(f"🔧 [Job {job_id}] Using fallback source_pdf from merge list: {source_pdf}")

        if not source_pdf:
            try:
                from backend.helpers import find_pdf_for_topic
                pdf_rel = find_pdf_for_topic(topic_label)
                if not pdf_rel and main_header:
                    pdf_rel = find_pdf_for_topic(main_header)
                resolved = _resolve_pdf_path(pdf_rel) if pdf_rel else None
                if resolved:
                    source_pdf = resolved
                    logging.info(f"🔧 [Job {job_id}] Resolved source_pdf from manifest: {source_pdf}")
            except Exception as exc:
                logging.warning(f"⚠️ [Job {job_id}] Failed to resolve source_pdf from manifest: {exc}")

        if (
            source_pdfs_list
            and isinstance(source_pdfs_list, list)
            and len(source_pdfs_list) > 0
            and not _is_premerged_pdf(source_pdf)
        ):
            try:
                logging.info(f"🔄 [Job {job_id}] Merging {len(source_pdfs_list)} PDFs in background...")
                import fitz
                merged_doc = fitz.open()
                merge_count = 0

                for p in source_pdfs_list:
                    if os.path.exists(p):
                        with fitz.open(p) as doc:
                            merged_doc.insert_pdf(doc)
                            merge_count += 1
                    else:
                        logging.warning(f"⚠️ [Job {job_id}] Missing PDF during merge: {p}")

                if merge_count > 0:
                    if not os.path.exists("temp_merges"):
                        os.makedirs("temp_merges", exist_ok=True)

                    merged_filename = f"bg_merged_{job_tag}_{int(time.time())}.pdf"
                    merged_path = os.path.abspath(os.path.join("temp_merges", merged_filename))
                    merged_doc.save(merged_path)
                    merged_doc.close()

                    source_pdf = merged_path  # Override source_pdf with merged one
                    logging.info(f"✅ [Job {job_id}] Background Merge Complete: {source_pdf}")
                else:
                    logging.error(f"❌ [Job {job_id}] No valid PDFs found to merge.")
            except Exception as e:
                logging.error(f"❌ [Job {job_id}] Background Merge Error: {e}")
        elif source_pdfs_list and _is_premerged_pdf(source_pdf):
            logging.info(f"✅ [Job {job_id}] Using pre-merged PDF: {source_pdf}")

        
        logging.info(f"🚀 [Job {job_id}] processing batch for '{topic_label}'")
        
        if file_content:
            logging.info(f"⚠️ [Job {job_id}] Ignoring deprecated file_content (text extraction removed).")
            file_content = None

        # Safety Check: Source PDF is required (text extraction removed)
        if not source_pdf:
            error_msg = f"❌ [Job {job_id}] Aborted: 'source_pdf' is required (text extraction removed)."
            logging.error(error_msg)
            _job_update(
                "UPDATE background_jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                (error_msg, datetime.now(), job_id),
            )
            return {"success": False, "error": error_msg}

        # Initialize Bulk Generator
        from .bulk_generator import BulkGenerator
        gen = BulkGenerator()
        
        logging.info(f"🚀 [Job {job_id}] Starting Bulk Generation for '{topic_label}' ({count} questions)...")
        
        # Get Sticky Key
        client = GeminiClient()
        sticky_key = client.get_sticky_key()
        
        # Fetch History for Deduplication
        # Prefer topic-scoped history (all_topics/chunk topics), fallback to category scope.
        history_titles = []
        history_categories = []
        if main_header:
            history_categories.append(main_header)
        if category and category not in history_categories:
            history_categories.append(category)

        generation_topics = _sanitize_topic_list(all_topics)
        if topic_label and topic_label not in generation_topics:
            generation_topics.append(topic_label)

        topic_history_enabled = os.getenv("TOPIC_SCOPED_HISTORY", "1") == "1"
        topic_history_limit = int(os.getenv("TOPIC_HISTORY_FETCH_LIMIT", "300"))
        category_history_limit = int(os.getenv("CATEGORY_HISTORY_FETCH_LIMIT", "100"))
        history_scope_used = "none"

        try:
            if topic_history_enabled and generation_topics:
                history_titles = database.get_recent_concepts_by_topic_scope(
                    source_material=source_material,
                    topics=generation_topics,
                    category=category or main_header,
                    limit=topic_history_limit
                )
                if history_titles:
                    history_scope_used = "topic"

            if not history_titles and history_categories:
                history_titles = database.get_recent_concepts_by_category_scope(
                    categories=history_categories,
                    source_material=source_material,
                    limit=category_history_limit
                )
                if history_titles:
                    history_scope_used = "category_fallback"

            logging.info(
                f"📜 [Job {job_id}] Found {len(history_titles)} previous question titles for context "
                f"(scope={history_scope_used}, topics={len(generation_topics)}, "
                f"categories={history_categories})."
            )
        except Exception as e:
            logging.warning(f"⚠️ [Job {job_id}] Failed to fetch history: {e}")

        # Call Generator
        try:
            custom_prompt_sections = payload.get("custom_prompt_sections")
            custom_difficulty_levels = payload.get("custom_difficulty_levels")
            questions = gen.generate_bulk(
                topic=topic_label,
                count=count,
                difficulty=difficulty,
                category=category,
                offset_history=history_titles, 
                source_pdf=source_pdf,
                api_key=sticky_key,
                custom_prompt_sections=custom_prompt_sections,
                custom_difficulty_levels=custom_difficulty_levels
            )
        except Exception as e:
            error_msg = f"❌ [Job {job_id}] Bulk Generation Error: {e}"
            logging.error(error_msg)
            _job_update(
                "UPDATE background_jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                (error_msg, datetime.now(), job_id),
            )
            raise e

        if not questions:
            error_msg = f"❌ [Job {job_id}] No questions generated."
            logging.error(error_msg)
            _job_update(
                "UPDATE background_jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                (error_msg, datetime.now(), job_id),
            )
            return {"success": False, "error": error_msg}

        logging.info(f"💾 [Job {job_id}] Saving {len(questions)} questions to DB...")
        
        saved_count = 0
        try:
            for q in questions:
                # Add metadata
                q["source_material"] = source_material
                q["category"] = category
                q["topic_links"] = generation_topics
                if "tags" not in q: q["tags"] = []
                q["tags"].extend(["admin_generated", "bulk_auto"])
                
                # Check hybrid deduplication
                # We use the generated question text + correct answer as the signature
                correct_id = q.get("correct_option_id")
                correct_text = ""
                correct_idx = -1
                
                # Calculate correct_answer_index
                opts = q.get("options", [])
                for i, o in enumerate(opts):
                    if o.get("id") == correct_id:
                        correct_text = o.get("text", "")
                        correct_idx = i
                        break
                
                q["correct_answer_index"] = correct_idx
                
                # Skipping complex dedup check for speed - purely relying on topic history if implemented later
                # Or re-enable check_duplicate_hybrid if desired. User said "sadece karmaşık... olmayacak".
                # Let's save.
                
                try:
                    result_id = database.add_question(q)
                    if result_id:
                        saved_count += 1
                except Exception as save_err:
                    logging.error(f"⚠️ [Job {job_id}] Save error: {save_err}")
                    
        except Exception as e:
            logging.error(f"❌ [Job {job_id}] Save Loop Error: {e}")

        # Finalize
        success = saved_count > 0
        final_status = "completed" if success else "failed"
        final_msg = f"Bulk Generated: {saved_count}/{count} requested."
        
        _job_update(
            '''
            UPDATE background_jobs 
            SET status = ?, error_message = ?, completed_at = ?, updated_at = ?, progress = ?, total_items = ?, generated_count = ?
            WHERE id = ?
            ''',
            (final_status, final_msg, datetime.now(), datetime.now(), saved_count, count, saved_count, job_id)
        )
        
        logging.info(f"🎉 [Job {job_id}] Finished: {final_msg}")
        return {
            "success": success,
            "generated_count": saved_count,
            "target_count": count,
            "message": final_msg
        }

    except Exception as e:
        logging.error(f"❌ [Job {job_id}] Crash: {e}")
        _job_update(
            "UPDATE background_jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
            (str(e), datetime.now(), job_id),
        )
        raise e
    finally:
        if conn:
            conn.close()
