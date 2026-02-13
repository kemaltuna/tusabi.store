#!/usr/bin/env python3
"""
Block-Based Question Generation Engine (PROD-SAFE)

Simplified 3-stage pipeline (Gemini-only for questions):
1. Draft (PDF-backed, single-correct enforcement in prompt)
2. Explanation/Blocks (self-corrects, adds siblings/traps/mini-DDX/table)
3. Validation & Repair (schema enforcement, optional auto-fix)
"""

import os
import json
import time
import argparse
import logging
import re
from typing import Optional

# Local imports
try:
    from .gemini_client import GeminiClient, DISCIPLINE_FOCUS_PROFILES
    from .schema_validator import validate_llm_output
    from .medquiz_library import get_library
    from backend import database
except ImportError:
    from gemini_client import GeminiClient, DISCIPLINE_FOCUS_PROFILES
    from schema_validator import validate_llm_output
    from medquiz_library import get_library
    try:
        from backend import database
    except ImportError:
        import sys
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
        import database

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class GenerationEngine:
    SOURCE_REF_PATTERNS = [
        re.compile(r"\bkaynak\b", re.IGNORECASE),
        re.compile(r"\bkaynakta\b", re.IGNORECASE),
        re.compile(r"\bkaynaktaki\b", re.IGNORECASE),
        re.compile(r"\bkaynaktan\b", re.IGNORECASE),
        re.compile(r"\bkaynağa\b", re.IGNORECASE),
        re.compile(r"\bkaynak\s+tablo\w*\b", re.IGNORECASE),
        re.compile(r"\bmetin\b", re.IGNORECASE),
        re.compile(r"\bmetinde\b", re.IGNORECASE),
        re.compile(r"\bmetindeki\b", re.IGNORECASE),
        re.compile(r"\bmetinden\b", re.IGNORECASE),
        re.compile(r"\b(yukarıdaki|aşağıdaki)?\s*tablo(ya|da|daki|ya göre)\b", re.IGNORECASE),
    ]

    def __init__(self, dry_run: bool = False, provider: str = "gemini"):
        self.dry_run = dry_run
        requested = provider.lower() if provider else "gemini"
        if requested != "gemini":
            print(f"⚠️ Provider '{requested}' not supported for question generation. Falling back to Gemini.")
        self.provider = "gemini"
        print("🤖 Using Provider: Google Gemini")
        self.client = GeminiClient()

        # Retriever disabled (legacy preprocessed_chunks not used)
        self.retriever = None
        # try:
        #      self.retriever = SimpleEvidenceRetriever(base_path="preprocessed_chunks")
        # except:
        #      print("⚠️ Retriever not initialized (Optional mode)")

    def generate_question(
        self,
        concept: str,
        topic: str,
        source_material: str = "Küçük Stajlar",
        difficulty: int = 3,
        evidence_override: Optional[str] = None,
        all_topics: list = None,
        source_pdf: Optional[str] = None,
        main_header: Optional[str] = None,
        category: Optional[str] = None,
        api_key: Optional[str] = None,
        pdf_cache_name: Optional[str] = None,
        uploaded_file: Optional[object] = None,
    ) -> dict:
        logging.info(f"\n🎯 Generating: {concept} ({topic})")
        
        main_evidence = ""
        update_evidence = ""
        combined_evidence = ""
        evidence_scope = {}
        uploaded_file = None

        # --- Stage 1: PDF Cache or Evidence Override ---
        if source_pdf:
            logging.info(f"📚 [1/3] Using PDF Source: {source_pdf}")
            if not pdf_cache_name or not uploaded_file:
                pdf_cache_name, uploaded_file = self.client.get_or_create_pdf_cache(
                    source_pdf,
                    specific_api_key=api_key
                )
            evidence_scope = {
                "source": "PDF_CHAPTER",
                "filename": os.path.basename(source_pdf),
                "multimodal": True,
                "cached": bool(pdf_cache_name),
                "cache_name": pdf_cache_name,
            }
        elif evidence_override:
            logging.info("📚 [1/3] Using Provided Evidence Override...")
            main_evidence = evidence_override
            combined_evidence = main_evidence
            evidence_scope = {"source": "OVERRIDE", "chunks": 1, "filtered": False}
        else:
            print("❌ Error: source_pdf is required (retriever/text extraction disabled).")
            return None

        # --- Synchronization Check ---
        if not all_topics or len(all_topics) <= 1:
            print(f"🔄 [Sync] Fetching latest topics for source: {source_material}")
            try:
                lib = get_library()
                found_topics = [t['topic'] for t in lib.get_topics(source_material)]
                if found_topics:
                    all_topics = found_topics
                    print(f"   ✅ Fetched {len(all_topics)} topics from Library.")
            except Exception as e:
                print(f"   ⚠️ Failed to fetch library topics: {e}")

        # Infer Discipline for Discipline-Specific Prompting
        discipline = None
        # Normalization map
        discipline_map = {
            "farmakoloji": "Farmakoloji",
            "patoloji": "Patoloji",
            "anatomi": "Anatomi",
            "biyokimya": "Biyokimya",
            "mikrobiyoloji": "Mikrobiyoloji",
            "dahiliye": "Dahiliye",
            "pediatri": "Pediatri",
            "cerrahi": "Genel_Cerrahi",
            "kadın": "Kadin_Dogum",
            "kadin": "Kadin_Dogum",
            "k.doğum": "Kadin_Dogum",
            "jinekoloji": "Kadin_Dogum",
            "obstetrik": "Kadin_Dogum",
            "fizyoloji": "Fizyoloji",
            "küçük": "Kucuk_Stajlar",
            "kucuk": "Kucuk_Stajlar",
            "dermatoloji": "Kucuk_Stajlar",
            "deri": "Kucuk_Stajlar",
            "nöroloji": "Kucuk_Stajlar",
            "kbb": "Kucuk_Stajlar",
            "göz": "Kucuk_Stajlar",
            "psikiyatri": "Kucuk_Stajlar",
            "üroloji": "Kucuk_Stajlar",
            "ftr": "Kucuk_Stajlar"
        }
        
        search_text = (f"{source_material} {topic}").lower()
        for key, value in discipline_map.items():
            if key in search_text:
                discipline = value
                break
        
        if not discipline and source_material:
            source_norm = database.normalize_text(source_material)
            profile_map = {database.normalize_text(k): k for k in DISCIPLINE_FOCUS_PROFILES.keys()}
            if source_norm in profile_map:
                discipline = profile_map[source_norm]

        if discipline:
            print(f"🎯 Discipline Detected: {discipline}")

        def strip_source_references(text: str) -> str:
            if not isinstance(text, str) or not text:
                return text
            patterns = [
                r"(,?\s*)?\b(kaynak|metin|kitap)\s*metin(de|de)?\s*(belirtildiği|belirtilen|yazdığı|geçtiği)\s*gibi\b",
                r"(,?\s*)?\b(kaynak|metin|kitap)(ta|da)?\s*(belirtildiği|belirtilen|yazdığı|geçtiği)\s*gibi\b",
                r"(,?\s*)?\b(kaynak|metin|kitap)\s*metin(de|de)?\s*göre\b",
                r"(,?\s*)?\b(kaynak|metin|kitap)(a|e)?\s*göre\b",
                r"(,?\s*)?\b(kaynak|metin|kitap)\s*(ifadesine|bilgisine)\s*göre\b",
            ]
            cleaned = text
            for pattern in patterns:
                cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            cleaned = cleaned.replace(" ,", ",").replace(" .", ".").replace(" ;", ";").replace(" :", ":")
            return cleaned

        def evidence_supports_topic(evidence_text: str) -> bool:
            if not evidence_text:
                return False
            normalized_evidence = database.normalize_text(evidence_text)
            tokens = set(database.normalize_text(topic).split())
            tokens.update(database.normalize_text(concept).split())
            if main_header:
                tokens.update(database.normalize_text(main_header).split())
            if category:
                tokens.update(database.normalize_text(category).split())
            tokens = {t for t in tokens if len(t) >= 3}
            if not tokens:
                return False
            if any(t in normalized_evidence for t in tokens):
                return True
            return False

        # --- Stage 1: Draft ---
        print("📝 [1/3] Drafting Question...")
        draft_start = time.time()
        
        # Pass uploaded_file if present
        draft = self.client.draft_question(
            concept,
            combined_evidence,
            topic,
            strict=True,
            media_file=uploaded_file,
            cached_content=pdf_cache_name,
            discipline=discipline,
            specific_api_key=api_key
        )
        
        draft_elapsed = time.time() - draft_start
        logging.info("📝 Draft completed in %.2fs", draft_elapsed)
        print(f"📝 Draft completed in {draft_elapsed:.2f}s")
        if not isinstance(draft, dict) or not draft:
            print("❌ Draft is empty or invalid.")
            return None

        # P0 Logic: Insufficient Evidence Check
        if draft.get("insufficient_evidence"):
            if source_pdf:
                logging.warning("⚠️ Insufficient evidence flagged but PDF source is present; continuing.")
                draft["insufficient_evidence"] = False
                draft.pop("reason", None)
            else:
                if evidence_supports_topic(combined_evidence):
                    print(f"⚠️ Insufficient Evidence flagged. Retrying with relaxed gate: {draft.get('reason')}")
                    logging.warning("⚠️ Insufficient evidence flagged; retrying relaxed gate. reason=%s", (draft.get("reason") or "")[:200])
                    draft = self.client.draft_question(
                        concept,
                        combined_evidence,
                        topic,
                        strict=False,
                        media_file=uploaded_file,
                        cached_content=pdf_cache_name,
                        discipline=discipline,
                        specific_api_key=api_key
                    )
                    if draft.get("insufficient_evidence"):
                        print(f"⚠️ STOPPING: Insufficient Evidence. Reason: {draft.get('reason')}")
                        logging.warning("⚠️ Stopping: insufficient evidence after retry. reason=%s", (draft.get("reason") or "")[:200])
                        return None
                else:
                    print(f"⚠️ STOPPING: Insufficient Evidence. Reason: {draft.get('reason')}")
                    logging.warning("⚠️ Stopping: insufficient evidence. reason=%s", (draft.get("reason") or "")[:200])
                    return None

        required_keys = ["question_text", "options", "correct_option_id"]
        if any(k not in draft for k in required_keys):
            print(f"❌ Draft missing required fields: {draft.keys()}")
            return None

        def _summarize_revision(before: dict, after: dict) -> str:
            summary = []
            if not isinstance(before, dict) or not isinstance(after, dict):
                return "revision_summary=unavailable"
            if before.get("question_text") != after.get("question_text"):
                summary.append("question_text_changed")
            if before.get("correct_option_id") != after.get("correct_option_id"):
                summary.append(f"correct_option_id:{before.get('correct_option_id')}->{after.get('correct_option_id')}")
            before_opts = {
                opt.get("id"): opt.get("text")
                for opt in (before.get("options") or [])
                if isinstance(opt, dict)
            }
            after_opts = {
                opt.get("id"): opt.get("text")
                for opt in (after.get("options") or [])
                if isinstance(opt, dict)
            }
            changed_opts = [
                opt_id for opt_id in before_opts.keys()
                if after_opts.get(opt_id) != before_opts.get(opt_id)
            ]
            if changed_opts:
                summary.append(f"options_changed={','.join(changed_opts)}")
            return "revision_summary=" + ("; ".join(summary) if summary else "no_changes")

        # Remove meta references to source text from question/options.
        draft["question_text"] = strip_source_references(draft.get("question_text"))
        if isinstance(draft.get("options"), list):
            for opt in draft["options"]:
                if isinstance(opt, dict) and "text" in opt:
                    opt["text"] = strip_source_references(opt.get("text"))

        print(f"   Draft: {draft['question_text'][:60]}...")
        logging.info(f"📝 Draft ready: concept={concept} correct={draft.get('correct_option_id')}")
        updates_applied = []
        critique = {"sibling_suggestions": []}
        siblings = []

        # --- Stage 2: Explanation Generation ---
        print("🧠 [2/3] Generating Deep Blocks...")
        stage4_start = time.time()
        
        # Difficulty to Student Level Mapping
        student_level = "beginner" if difficulty <= 2 else "advanced"
        
        explanation_json = self.client.generate_explanation_blocks(
            draft=draft, 
            critique=critique, 
            updates=updates_applied, 
            evidence=combined_evidence,
            source_material=source_material,
            topic=topic,
            media_file=uploaded_file,
            cached_content=pdf_cache_name,
            discipline=discipline,
            student_level=student_level,
            specific_api_key=api_key
        )
        stage4_elapsed = time.time() - stage4_start
        logging.info("🧠 Stage 2 completed in %.2fs", stage4_elapsed)
        print(f"🧠 Stage 2 completed in {stage4_elapsed:.2f}s")
        
        # Assemble preliminary object
        # Explanation stage may revise the question if it conflicts with evidence.
        candidate_data = explanation_json
        if not isinstance(candidate_data, dict):
            print("❌ Explanation output is invalid.")
            logging.warning("❌ Explanation output invalid (non-dict).")
            return None

        # If explanation omitted core fields, fall back to draft (do NOT overwrite valid revisions).
        if not candidate_data.get("question_text"):
            candidate_data["question_text"] = draft.get("question_text")
        if not candidate_data.get("options"):
            candidate_data["options"] = draft.get("options")
        if not candidate_data.get("correct_option_id"):
            candidate_data["correct_option_id"] = draft.get("correct_option_id")

        # Log if explanation revised the question structure.
        if (
            candidate_data.get("question_text") != draft.get("question_text")
            or candidate_data.get("options") != draft.get("options")
            or candidate_data.get("correct_option_id") != draft.get("correct_option_id")
        ):
            print("🛠️ Explanation revised question to align with evidence.")
            logging.info("🛠️ Explanation revised question (%s)", _summarize_revision(draft, candidate_data))
        # candidate_data['concept_tag'] = draft.get('concept_tag') # Removed to fix Schema forbidden extra field
        
        if 'explanation' not in candidate_data:
             candidate_data['explanation'] = {}

        if not isinstance(candidate_data.get('explanation'), dict):
             candidate_data['explanation'] = {}

        # Ensure tags exist and include a concept tag
        tags = candidate_data.get('tags')
        if isinstance(tags, str):
            tags = database.safe_json_parse(tags, [])
        if not isinstance(tags, list):
            tags = []
        concept_tag = draft.get("concept_tag") or f"concept:{concept}"
        if concept_tag and not any(t.startswith("concept:") for t in tags):
            tags.append(concept_tag)
        candidate_data['tags'] = tags

        # Fill missing explanation fields when possible
        if not candidate_data['explanation'].get("main_mechanism"):
            if draft.get("brief_explanation"):
                candidate_data['explanation']["main_mechanism"] = draft.get("brief_explanation")
        if not candidate_data['explanation'].get("clinical_significance"):
            if draft.get("brief_explanation"):
                candidate_data['explanation']["clinical_significance"] = draft.get("brief_explanation")
        if not candidate_data['explanation'].get("sibling_entities"):
            fallback = []
            if isinstance(candidate_data.get("options"), list):
                for opt in candidate_data.get("options", []):
                    if isinstance(opt, dict) and opt.get("id") != candidate_data.get("correct_option_id"):
                        text = opt.get("text")
                        if text:
                            fallback.append(text)
                    if len(fallback) >= 2:
                        break
            if len(fallback) < 2 and siblings:
                fallback.extend([s for s in siblings if s])
            if len(fallback) >= 2:
                candidate_data['explanation']["sibling_entities"] = fallback[:2]

        # Optional table refinement for meta-labeled headers.
        explanation_blocks = candidate_data.get("explanation", {}).get("blocks")
        if isinstance(explanation_blocks, list):
            for block in explanation_blocks:
                if not isinstance(block, dict) or block.get("type") != "table":
                    continue
                headers = block.get("headers") or []
                header_text = " ".join([str(h).lower() for h in headers])
                if (
                    "cevap" in header_text
                    or "çeldirici" in header_text
                    or "celdirici" in header_text
                    or "doğru" in header_text
                    or "dogru" in header_text
                    or "ayırıcı" in header_text
                    or "ayirici" in header_text
                ):
                    if hasattr(self.client, "refine_table_block"):
                        correct_text = None
                        if isinstance(candidate_data.get("options"), list):
                            for opt in candidate_data.get("options", []):
                                if isinstance(opt, dict) and opt.get("id") == candidate_data.get("correct_option_id"):
                                    correct_text = opt.get("text")
                                    break
                        refine_context = {
                            "question_text": candidate_data.get("question_text"),
                            "correct_answer": correct_text,
                            "siblings": candidate_data.get("explanation", {}).get("sibling_entities") or [],
                            "source_material": source_material,
                            "topic": topic,
                        }
                        refined = self.client.refine_table_block(block, refine_context)
                        if isinstance(refined, dict) and refined.get("headers") and refined.get("rows"):
                            refined["type"] = "table"
                            refined["headers"] = self._clean_table_headers(refined.get("headers") or [])
                            block.update(refined)
                    break
                else:
                    if isinstance(headers, list):
                        block["headers"] = self._clean_table_headers(headers)
             
        # P0 Fix: Deterministic Updates Flags
        # Set by engine based on actual retrieval results, not LLM hallucination
        candidate_data['explanation']['update_checked'] = False
        candidate_data['explanation']['updates_applied'] = updates_applied
        
        # Topic Assignment: Always use the explicitly requested topic from the job payload
        # Note: "Intelligent Multi-Topic Association" feature was REMOVED.
        # It used LLM to pick topics from a global list, causing cross-category misassignment.
        target_topic = topic
        print(f"📌 [Enforced] Using target topic: {topic}")
        
        # New Traceability Fields
        candidate_data['topic'] = target_topic  # Picked topic
        candidate_data['source_material'] = source_material  # P0 Fix: Force source to match User Request
        candidate_data['requested_topic'] = topic
        candidate_data['requested_source_material'] = source_material
        candidate_data['generated_topic_predicted'] = None
        candidate_data['topic_gate_passed'] = True
        candidate_data['evidence_scope'] = evidence_scope

        # Normalize roman numeral stems to render line-by-line
        candidate_data["question_text"] = self._normalize_roman_numeral_stem(candidate_data.get("question_text"))

        # --- Stage 3: Validation & Repair ---
        print("✅ [3/3] Validating Schema...")
        try:
            validated = validate_llm_output(candidate_data)
            print("   Schema Valid! 🎉")
            logging.info("✅ Schema validation passed.")
        except ValueError as e:
            print(f"⚠️ Schema Error: {e}")
            logging.warning("⚠️ Schema validation error: %s", str(e)[:300])
            print("🔧 Attempting Auto-Repair (1 Pass Only)...")
            try:
                # Feed the error back to the model
                repaired_json = self.client.repair_json(json.dumps(candidate_data), str(e))
                validated = validate_llm_output(repaired_json)
                print("   Repair Successful! 🔧✅")
                logging.info("🔧 JSON repair succeeded.")
            except Exception as repair_error:
                print(f"❌ Repair Failed: {repair_error}")
                logging.error("❌ JSON repair failed: %s", repair_error)
                if self.dry_run:
                    return candidate_data # Return raw data in dry run for debugging
                return None # Skip persistence if validation fails

        # Validate and convert
        final_dict = validated.to_db_dict()

        # Ensure table columns explicitly anchor to correct vs sibling entities.
        final_dict = self._enforce_table_entity_labels(final_dict)
        final_dict = self._strip_source_refs_in_obj(final_dict)
        
        # Explicitly set metadata (ensure overrides user request)
        final_dict["source_material"] = source_material
        final_dict["category"] = category or main_header
        
        # Tags for tracking
        if final_dict.get("tags") is None: final_dict["tags"] = []
        if isinstance(final_dict["tags"], str): pass # Should probably parse if str, but to_db_dict handles format usually
        
        if main_header and isinstance(final_dict["tags"], list):
             tag_str = f"header:{main_header}"
             if tag_str not in final_dict["tags"]:
                 final_dict["tags"].append(tag_str)

        return final_dict

    def _enforce_table_entity_labels(self, data: dict) -> dict:
        explanation = data.get("explanation_data")
        if not isinstance(explanation, dict):
            return data
        blocks = explanation.get("blocks")
        if not isinstance(blocks, list):
            return data

        options = data.get("options") or []
        correct_idx = data.get("correct_answer_index")
        correct_text = None
        if isinstance(correct_idx, int) and 0 <= correct_idx < len(options):
            opt = options[correct_idx]
            if isinstance(opt, dict):
                correct_text = opt.get("text")
            else:
                correct_text = str(opt)
        siblings = explanation.get("sibling_entities") or []

        def strip_entity_prefix(cell: str, names: list[str]) -> str:
            if not cell:
                return cell
            cleaned = cell
            for name in names:
                if not name:
                    continue
                pattern = rf"^\\s*{re.escape(name)}\\s*[:\\-–]\\s*"
                if re.match(pattern, cleaned, flags=re.IGNORECASE):
                    cleaned = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE).strip()
            return cleaned

        name_list = [n for n in [correct_text] + siblings if n]
        if not name_list:
            return data

        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "table":
                continue
            rows = block.get("rows") or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                cells = row.get("cells")
                if not isinstance(cells, list):
                    continue
                row["cells"] = [strip_entity_prefix(str(cell), name_list) for cell in cells]
            block["rows"] = rows
        explanation["blocks"] = blocks
        data["explanation_data"] = explanation
        return data

    def _strip_source_refs(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text
        cleaned = text
        for pattern in self.SOURCE_REF_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
        return cleaned.strip()

    def _normalize_roman_numeral_stem(self, text: str) -> str:
        """Ensure I–IV statements in roman-combination questions appear on separate lines."""
        if not text or not isinstance(text, str):
            return text
        if not re.search(r"\bI\.\s", text):
            return text
        # Apply only to likely roman-combination stems
        if not re.search(r"(hangileri|yukarıdakilerden|asagidakilerden|aşağıdakilerden|ifadelerden)", text, re.IGNORECASE):
            return text
        # Insert newline before roman numeral items if not already at line start
        return re.sub(r"(?<!\n)\s+(?=(I|II|III|IV)\.\s)", "\n", text)

    def _strip_source_refs_in_obj(self, obj):
        if isinstance(obj, str):
            return self._strip_source_refs(obj)
        if isinstance(obj, list):
            return [self._strip_source_refs_in_obj(item) for item in obj]
        if isinstance(obj, dict):
            return {key: self._strip_source_refs_in_obj(value) for key, value in obj.items()}
        return obj

    def _clean_table_headers(self, headers: list) -> list:
        cleaned = []
        for header in headers or []:
            text = str(header)
            text = re.sub(r"\\((?i:doğru\\s*cevap|celdirici|çeldirici)[^)]*\\)", "", text).strip()
            text = re.sub(r"(?i)\\bdoğru\\s*cevap\\b", "", text).strip()
            text = re.sub(r"(?i)\\b(celdirici|çeldirici)\\b", "", text).strip()
            text = re.sub(r"\\s{2,}", " ", text)
            text = text.strip(" -–:")
            cleaned.append(text or str(header))
        return cleaned

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
            logging.info(f"💾 Saved Question ID: {qid}")
        except Exception as e:
            print(f"❌ Database Error: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concept", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--source", default="Küçük Stajlar")
    parser.add_argument("--source-pdf", dest="source_pdf", help="Path to source PDF")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = GenerationEngine(dry_run=args.dry_run)
    try:
        q = engine.generate_question(
            args.concept,
            args.topic,
            source_material=args.source,
            source_pdf=args.source_pdf
        )
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
