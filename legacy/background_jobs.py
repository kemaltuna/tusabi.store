import logging
import time
from datetime import datetime
from generation_engine import GenerationEngine
from gemini_client import GeminiClient
import database

def process_generation_batch(job_id, payload):
    """
    Executes a 'generation_batch' job.
    Payload: { 'file_content': str, 'topic': str, 'source_material': str, 'count': int, 'difficulty': int }
    """
    import threading
    
    conn = database.get_db_connection()
    c = conn.cursor()
    
    try:
        topic_label = payload.get('topic')
        # Default fallback changed to ASCII key to match taxonomy
        source_material = payload.get('source_material', 'Kucuk_Stajlar')
        count = payload.get('count', 10)
        difficulty = payload.get('difficulty', 3)
        file_content = payload.get('file_content')
        source_pdf = payload.get('source_pdf') # New PDF Support
        all_topics = payload.get('all_topics', [topic_label]) # Fallback to single if not present
        main_header = payload.get('main_header') # Strict Scope Category
        
        # 0. Background Merging Logic
        source_pdfs_list = payload.get('source_pdfs_list')
        if source_pdfs_list and isinstance(source_pdfs_list, list) and len(source_pdfs_list) > 0:
             try:
                 logging.info(f"🔄 [Job {job_id}] Merging {len(source_pdfs_list)} PDFs in background...")
                 import fitz
                 import os
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
                     
                     merged_filename = f"bg_merged_{job_id}_{int(time.time())}.pdf"
                     merged_path = os.path.abspath(os.path.join("temp_merges", merged_filename))
                     merged_doc.save(merged_path)
                     merged_doc.close()
                     
                     source_pdf = merged_path # Override source_pdf with merged one
                     logging.info(f"✅ [Job {job_id}] Background Merge Complete: {source_pdf}")
                 else:
                     logging.error(f"❌ [Job {job_id}] No valid PDFs found to merge.")
                     
             except Exception as e:
                 logging.error(f"❌ [Job {job_id}] Background Merge Error: {e}")

        
        logging.info(f"🚀 [Job {job_id}] processing batch for '{topic_label}'")
        
        # Safety Check: Missing File Content OR Source PDF
        if not file_content and not source_pdf:
            error_msg = f"❌ [Job {job_id}] Aborted: Both 'file_content' and 'source_pdf' are missing."
            logging.error(error_msg)
            c.execute("UPDATE background_jobs SET status = 'failed', error_message = ? WHERE id = ?", (error_msg, job_id))
            conn.commit()
            return

        # Initialize
        engine = GenerationEngine(provider="gemini")
        client = GeminiClient()
        
        # 1. Update status to Running (if not already)
        # (JobManager sets it to processing, we just update progress)
        
        # 1b. Upload PDF if present
        uploaded_file_ref = None
        if source_pdf:
             logging.info(f"📤 [Job {job_id}] Uploading PDF: {source_pdf}")
             try:
                 uploaded_file_ref = client.upload_file(source_pdf)
             except Exception as e:
                 error_msg = f"❌ [Job {job_id}] PDF Upload Failed: {e}"
                 logging.error(error_msg)
                 c.execute("UPDATE background_jobs SET status = 'failed', error_message = ? WHERE id = ?", (error_msg, job_id))
                 conn.commit()
                 return
        
        # 2. Extract Concepts
        logging.info(f"📋 [Job {job_id}] Extracting concepts...")
        
        # Pass PDF ref if available, else text
        if source_pdf:
             concepts = client.extract_concepts("", topic_label, count=count, media_file=uploaded_file_ref)
        else:
             concepts = client.extract_concepts(file_content, topic_label, count=count)
        
        if not concepts:
            logging.error(f"❌ [Job {job_id}] No concepts found.")
            c.execute("UPDATE background_jobs SET status = 'failed', error_message = 'No concepts extracted' WHERE id = ?", (job_id,))
            conn.commit()
            return

        logging.info(f"✅ [Job {job_id}] Extracted {len(concepts)} concepts.")
        
        # Update Total Items in DB
        c.execute("UPDATE background_jobs SET total_items = ? WHERE id = ?", (len(concepts), job_id))
        conn.commit()
        
        # 3. Generation Loop (Parallelized)
        logging.info(f"⚡ [Job {job_id}] Starting Parallel Generation (3 workers)...")
        
        # We use a dedicated inner executor for this job's tasks, 
        # OR we could just run sequentially since the JobManager already governs overall concurrency.
        # Given "3 concurrent threads per job" from the Handoff doc, let's keep the internal parallelism 
        # to speed up THIS job.
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        generated_count = 0
        failed_count = 0
        
        def process_concept_wrapper(index, concept_text):
            try:
                # Pre-Generation Deduplication (Optimistic Check)
                if database.check_concept_exists(concept_text, topic_label):
                    logging.info(f"⏩ [Job {job_id}] Skipping duplicate: {concept_text}")
                    return True # Count as success (skipped)
                
                logging.info(f"⚙️ [Job {job_id}] {index+1}/{len(concepts)}: {concept_text}")
                q_data = engine.generate_question(
                    concept=concept_text,
                    topic=topic_label,
                    source_material=source_material,
                    difficulty=difficulty,
                    evidence_override=file_content,
                    all_topics=all_topics,
                    source_pdf=source_pdf, # Pass the PDF path
                    category=main_header # Pass Strict Scope Category
                )
                if q_data:
                    if "tags" not in q_data: q_data["tags"] = []
                    q_data["tags"].extend(["admin_generated", "auto_background"])
                    
                    # Capture Result ID
                    result_id = database.add_question(q_data)
                    
                    if result_id:
                        return True
                    else:
                        logging.error(f"❌ [Job {job_id}] DB Insert Failed for concept: {concept_text}")
                        return False
                else:
                    return False
            except Exception as ex:
                logging.error(f"⚠️ [Job {job_id}] Error: {concept_text} -> {ex}")
                return False

        # Execute in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_concept = {executor.submit(process_concept_wrapper, i, c): c for i, c in enumerate(concepts)}
            
            for future in as_completed(future_to_concept):
                try:
                    success = future.result()
                    if success:
                        generated_count += 1
                    else:
                        failed_count += 1
                    
                    # Update Progress in DB
                    current_progress = generated_count + failed_count
                    if current_progress % 1 == 0: # Update every item for granular progress
                        # Re-open connection for thread safety if needed, but here we are in main thread
                        # SQLite connections aren't thread safe, but we are in the main loop of this function.
                        # The threads just output result to future.
                         c.execute("UPDATE background_jobs SET progress = ?, updated_at = ? WHERE id = ?", 
                                  (current_progress, datetime.now(), job_id))
                         conn.commit()
                    
                except Exception as exc:
                    logging.error(f"Worker Exception: {exc}")
                    failed_count += 1
        
        # 4. Finalize
        final_status = "completed"
        final_msg = f"Generated: {generated_count}, Failed: {failed_count}"
        
        c.execute('''
            UPDATE background_jobs 
            SET status = ?, error_message = ?, completed_at = ?, progress = total_items 
            WHERE id = ?
        ''', (final_status, final_msg, datetime.now(), job_id))
        conn.commit()
        
        logging.info(f"🎉 [Job {job_id}] Finished: {final_msg}")

    except Exception as e:
        logging.error(f"❌ [Job {job_id}] Crash: {e}")
        c.execute("UPDATE background_jobs SET status = 'failed', error_message = ? WHERE id = ?", (str(e), job_id))
        conn.commit()
        raise e
    finally:
        conn.close()
