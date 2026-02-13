import argparse
import sys
import os
import logging
from typing import List

# Add parent dir to path to find new_web_app modules if running from scripts dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from new_web_app.core.bulk_generator import BulkGenerator
from new_web_app.backend import database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BulkRunner")

def get_history(topic: str) -> List[str]:
    """Fetch existing question titles for topic to avoid duplicates."""
    # This requires database.py to support fetching by topic/tags or just scanning all.
    # For now, let's try a simple search if available, or just fetch recent.
    # Database module might not have a clean 'get_titles_by_topic'.
    # We'll skip complex history fetching for this MVP script or assume empty.
    return [] 

def save_questions(questions: List[dict]):
    success_count = 0
    for q in questions:
        try:
            # Add metadata required by DB schema if missing
            if "correct_answer_index" not in q:
                # Calculate index from ID
                opts = q.get("options", [])
                cid = q.get("correct_option_id")
                idx = -1
                for i, o in enumerate(opts):
                    if o.get("id") == cid:
                        idx = i
                        break
                q["correct_answer_index"] = idx

            # Ensure explanation data is nested correctly
            # BulkGenerator already formats it as 'explanation' dict.
            # database.add_question expects dict with flexible fields.
            # But wait, schema validation might run inside database.add_question?
            # No, database.py usually valid_llm_output is optional or done before.
            # Let's check database.py add_question.
            
            # Map 'explanation' to 'explanation_data' if DB expects it
            if "explanation" in q:
                q["explanation_data"] = q.pop("explanation")
            
            qid = database.add_question(q)
            logger.info(f"✅ Saved Question ID: {qid}")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ Failed to save question: {e}")
            
    return success_count

def main():
    parser = argparse.ArgumentParser(description="Bulk Question Generator (Pro Mode)")
    parser.add_argument("--topic", required=True, help="Topic to generate questions for")
    parser.add_argument("--count", type=int, default=10, help="Number of questions")
    parser.add_argument("--source-pdf", dest="source_pdf", help="Absolute path to source PDF")
    
    args = parser.parse_args()
    
    gen = BulkGenerator()
    
    print(f"🚀 Starting Bulk Generation for: {args.topic} ({args.count} questions)")
    if args.source_pdf:
        print(f"📚 Using PDF: {args.source_pdf}")

    history = get_history(args.topic)
    
    questions = gen.generate_bulk(args.topic, count=args.count, offset_history=history, source_pdf=args.source_pdf)
    
    if not questions:
        print("❌ No questions generated.")
        return
        
    print(f"📝 Parsed {len(questions)} questions. Saving to DB...")
    saved = save_questions(questions)
    print(f"🎉 Completed. Saved {saved}/{len(questions)} questions.")

if __name__ == "__main__":
    main()
