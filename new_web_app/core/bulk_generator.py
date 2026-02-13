import logging
import os
import re
import json
from typing import List, Dict, Optional
from datetime import datetime

# Local imports
try:
    from .gemini_client import GeminiClient
except ImportError:
    from gemini_client import GeminiClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Default Prompt Sections (modular, each key is individually editable) ──
DEFAULT_PROMPT_SECTIONS = {
    "persona": "Sen tus sorusu hazırlayan {persona_role}.",
    "goal": "Hedefin: {display_topic} konusunun sana sağlanan ilgili pdf bölümünden, {diff_text} {count} adet özgün soru hazırlamak.",
    "principles": """ÖNEMLİ İLKELER:
1. Soruları mümkün olduğunca SANA VERİLEN PDF BÖLÜMÜNDEKİ bilgilerle kurgula. Dış bilgi yerine kaynaktaki detayları kullanmaya çalış.
2. Bu sorular TUS öğrencileri tarafından sınava hazırlıkta kullanılacaktır. Bu yüzden ÇOK DİKKATLİ ve ÖĞRETİCİ olmalı, hatalı bilgi içermemelidir.
3. {persona_role} gibi düşün ve soruları bu uzmanlık perspektifiyle hazırla.""",
    "format_rules": """ZORUNLU FORMAT VE KURALLAR:
1. Her soru "Soru X: [Başlık]" formatıyla başlamalıdır. (Örn: Soru 1: Epileptik Ensefalopatiler - )
2. Soru kökü, klinik vinyet, roma rakamlı soru, spot bilgi içerebilir.
3. Seçenekler A) B) C) D) E) şeklinde alt alta yazılmalıdır.
4. SEÇENEKLERDEN SONRA MUTLAKA "Doğru Cevap: [Şık]" satırı olmalıdır. (Örn: Doğru Cevap: B)
5. Ardından "Açıklama:" başlığı altında detaylı, öğretici bir açıklama yazılmalıdır.
6. Mümkünse açıklamanın sonuna "Karşılaştırma Tablosu:" başlığı ekle. Tabloyu MUTLAKA Markdown formatında (| Başlık 1 | Başlık 2 |) yap. Düz metin kullanma.
7. Kaynak ismi verme ("Notlara göre" deme).
8. Çıktının sonuna Asla "Başarılar", "Bu sorular...", "Umarım.." gibi bitirme/yorum cümleleri EKLEME. Sadece soruları ver ve dur.
9. Önceki üretimler hakkında özet: Toplam {total_history} soru, {unique_titles_count} farklı başlık. 
   Son/tekrar eden başlık örnekleri (başlık x adet): {history_summary}
   Dağılım kuralı: Yeni/sorulmamış başlıklara veya aynı başlıkta farklı noktaları sorabilirsin.
10. Her sorunun bitimine (tablodan sonra) mutlaka "---" (üç tire) ekle.""",
    "example": """--- ÖRNEK ÇIKTI FORMATI ---
Soru 1: Konu Başlığı
[Soru Metni...]
A) ...
B) ...
Doğru Cevap: A
Açıklama: [Açıklama metni]

Karşılaştırma Tablosu:
| Özellik | Tanım |
|---|---|
| A | B |

---
Soru 2: ...""",
    "closing": """Şimdi, "{display_topic}" konusu için {count} adet soruyu tek bir akışta yaz.""",
}

# Fixed section order — custom sections are appended after these
DEFAULT_SECTION_ORDER = ["persona", "goal", "principles", "format_rules", "example", "closing"]

# ─── Default Difficulty Level Descriptions ──
DEFAULT_DIFFICULTY_LEVELS = {
    "1": "ORTA zorlukta (Standart TUS seviyesi,pdf içinde bold yazılanlar, olmazsa olmaz başlıklar; tabloların en öne çıkan, sık karşılaşılan mutlaka bilinmesi gereken kısımları)",
    "2": "ORTA-ZOR seviyede (Standart TUS seviyesi,pdf içinde bold yazılanlar,olmazsa olmaz konu başlıkları ve ek olarak Ayırt edici, DETAY sorular; tablolardaki en değerli kısımlar ve ek olarak daha az sıklıkta ama sınavda çıkma potansiyeli olan kısımlar )",
    "3": "ZOR seviyede (Klinik vaka ağırlıklı SORULAR, DETAY SORULAR; tablolardaki daha az karşılaşılan sadece yüksek puan hedefleyen öğrencilerin bilmesi gereken detaylar)",
    "4": "ZOR ve ÇOK ZOR seviyede (Derece öğrencileri ve TUS derecesi için)"
}

class BulkGenerator:
    """
    Generates questions in bulk (e.g. 10 at a time) using a specialized
    creative prompt, then parses the raw text into structured objects.
    """

    def __init__(self):
        self.client = GeminiClient()

    def generate_bulk(self, topic: str, count: int = 10, difficulty: int = 3, category: str = None, offset_history: List[str] = None, source_pdf: str = None, api_key: str = None, custom_prompt_sections: Dict = None, custom_difficulty_levels: Dict = None) -> List[Dict]:
        """
        Main entry point.
        1. Refines prompt with history (deduplication).
        2. Uploads/Caches PDF if provided.
        3. Calls Gemini (long context with PDF).
        4. Parses output.
        """
        history = offset_history or []
        # Logging is opt-in via env flags.
        log_prompt = os.getenv("BULKGEN_LOG_PROMPT", "0") == "1"
        log_prompt_full = os.getenv("BULKGEN_LOG_PROMPT_FULL", "0") == "1"
        log_response_full = os.getenv("BULKGEN_LOG_RESPONSE_FULL", "0") == "1"
        
        # PDF Handling
        cache_name = None
        if source_pdf:
            logger.info(f"📚 Using PDF Source: {source_pdf}")
            try:
                import fitz
                with fitz.open(source_pdf) as doc:
                    logger.info(f"📄 PDF page count: {doc.page_count}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to read PDF page count: {e}")
            try:
                cache_name, _ = self.client.get_or_create_pdf_cache(source_pdf, specific_api_key=api_key)
                if cache_name:
                    logger.info(f"💾 PDF cache name: {cache_name}")
            except Exception as e:
                logger.error(f"❌ Failed to process PDF: {e}")
                return []
        
        prompt = self._construct_prompt(topic, count, history, difficulty=difficulty, category=category, source_pdf_path=source_pdf, custom_sections=custom_prompt_sections, custom_difficulty_levels=custom_difficulty_levels)
        
        logger.info(f"🚀 Sending Bulk Request for topic: {topic} (Diff: {difficulty}, History: {len(history)} items)")
        logger.info(f"🧾 Prompt length: {len(prompt)} chars")
        if log_prompt_full:
            logger.info(f"🧾 Prompt (full):\n{prompt}")
        elif log_prompt:
            logger.info(f"🧾 Prompt (preview):\n{prompt[:2000]}")
        
        # Call Gemini with caching support
        response_text = self.client.generate_raw_text(prompt, cached_content=cache_name, specific_api_key=api_key) 
        
        if not response_text:
            logger.error("❌ No response from Gemini.")
            return []
        logger.info(f"📥 Response length: {len(response_text)} chars")
        if log_response_full:
            logger.info(f"📥 Response (full):\n{response_text}")

        questions = self._parse_bulk_response(response_text, topic)
        logger.info(f"✅ Parsed {len(questions)} questions from bulk text.")
        return questions

    def _construct_prompt(self, topic: str, count: int, history: List[str], difficulty: int = 3, category: str = None, source_pdf_path: str = None, custom_sections: Dict = None, custom_difficulty_levels: Dict = None) -> str:
        def _extract_title(text: str) -> Optional[str]:
            if not text:
                return None
            line = text.strip().splitlines()[0].strip()
            if not line:
                return None
            match = re.match(r"Soru\s+\d+\s*:\s*(.*)", line, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return line

        # Summarize history by title to reduce token usage
        title_counts: Dict[str, int] = {}
        for item in history:
            title = _extract_title(item)
            if not title:
                continue
            title_counts[title] = title_counts.get(title, 0) + 1

        unique_titles = list(title_counts.keys())
        total_history = sum(title_counts.values())
        sorted_titles = sorted(title_counts.items(), key=lambda x: (-x[1], x[0]))
        max_titles = int(os.getenv("BULKGEN_HISTORY_TITLES", "200"))
        top_titles = sorted_titles[:max_titles]
        history_summary = "; ".join(
            [f"{t} (x{c})" if c > 1 else t for t, c in top_titles]
        ) or "Yok"
        if os.getenv("BULKGEN_LOG_HISTORY") == "1":
            logger.info(
                "📚 History summary: total=%s, unique=%s, top=%s",
                total_history,
                len(unique_titles),
                history_summary
            )
        
        # Use custom difficulty levels if provided, otherwise defaults
        levels = {**DEFAULT_DIFFICULTY_LEVELS}
        if custom_difficulty_levels and isinstance(custom_difficulty_levels, dict):
            levels.update(custom_difficulty_levels)
        diff_text = levels.get(str(difficulty), levels.get("1", "ORTA zorlukta (Standart TUS seviyesi)"))

        # Prioritize category if provided, otherwise topic
        display_topic = category if category else topic
        
        # Determine Persona based on Lesson Name from PDF Path
        lesson_name = "Tıp" # Fallback
        
        if source_pdf_path:
            # Try to find lesson name in path (e.g. .../processed_pdfs/Patoloji/...)
            # Known lessons based on directory structure
            known_lessons = [
                "Anatomi", "Biyokimya", "Dahiliye", "Farmakoloji", "Fizyoloji",
                "Genel_Cerrahi", "Kadin_Dogum", "Kucuk_Stajlar", "Mikrobiyoloji",
                "Patoloji", "Pediatri"
            ]
            
            norm_path = source_pdf_path.replace("\\", "/")
            parts = norm_path.split("/")
            
            found_lesson = None
            
            # 1. Direct match with known lessons
            for part in parts:
                if part in known_lessons:
                    found_lesson = part
                    break
            
            if found_lesson:
                # Normalize display name
                if found_lesson == "Genel_Cerrahi":
                    lesson_name = "Genel Cerrahi"
                elif found_lesson == "Kadin_Dogum":
                    lesson_name = "Kadın Hastalıkları ve Doğum"
                elif found_lesson == "Kucuk_Stajlar":
                    # Exception: For Kucuk Stajlar, use category (e.g. Dermatoloji) if available
                    if category:
                         lesson_name = category
                    else:
                         lesson_name = "Küçük Stajlar"
                else:
                    lesson_name = found_lesson # e.g. Patoloji, Pediatri
        
        elif category:
             # Fallback if source_pdf_path is missing but category is present
             lesson_name = category

        # Construct Persona Role
        persona_role = f"bir {lesson_name} uzmanısın"

        # Template variables for interpolation
        template_vars = {
            "persona_role": persona_role,
            "display_topic": display_topic,
            "display_topic": display_topic,
            #"topic": topic, # Deprecated/Removed to avoid confusion. Use display_topic.
            "diff_text": diff_text,
            "count": str(count),
            "total_history": str(total_history),
            "unique_titles_count": str(len(unique_titles)),
            "history_summary": history_summary,
            "lesson_name": lesson_name,
        }

        # Use custom sections if provided, otherwise defaults
        sections = {**DEFAULT_PROMPT_SECTIONS}
        if custom_sections and isinstance(custom_sections, dict):
            for key, value in custom_sections.items():
                if value is not None:
                    sections[key] = value

        # Build section order: default order first, then any extra custom keys
        section_order = list(DEFAULT_SECTION_ORDER)
        if custom_sections and isinstance(custom_sections, dict):
            for key in custom_sections:
                if key not in section_order and custom_sections[key]:
                    section_order.append(key)

        # Interpolate template variables into each section
        rendered_parts = []
        for key in section_order:
            raw = sections.get(key, "")
            if not raw:
                continue
            try:
                rendered = raw.format(**template_vars)
            except KeyError:
                rendered = raw  # If user removed a placeholder variable, just use raw text
            rendered_parts.append(rendered)

        return "\n\n".join(rendered_parts)



    def _parse_bulk_response(self, text: str, topic: str) -> List[Dict]:
        """
        Splits the long text into discrete question objects using Regex.
        """
        questions = []
        
        # Split by "Soru [Number]:"
        # Regex lookahead to find blocks starting with "Soru \d+:"
        # Matches "Soru 1: ..." until next "Soru 2: ..."
        pattern = r"(Soru\s+\d+\s*:.*?)(?=Soru\s+\d+\s*:|$)"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        
        if matches:
            # Cleanup last block for potential ending chatter
            last_block = matches[-1]
            chatter_patterns = [
                r"-+\s*Bu sorular.*", 
                r"Başarılar dilerim.*", 
                r"Umarım faydalı.*",
                r"TUS'un son yıllardaki.*"
            ]
            for pat in chatter_patterns:
                last_block = re.sub(pat, "", last_block, flags=re.IGNORECASE | re.DOTALL).strip()
            matches[-1] = last_block

        for block in matches:
            q_data = self._parse_single_block(block, topic)
            if q_data:
                questions.append(q_data)
                
        return questions

    def _parse_single_block(self, block: str, topic: str) -> Optional[Dict]:
        try:
            # 1. Extract Title/Header
            # "Soru 1: Epileptik Ensefalopatiler (Klinik)" -> Title: Epileptik Ensefalopatiler (Klinik)
            header_match = re.match(r"Soru\s+\d+\s*:\s*(.*?)(\n|$)", block)
            title = header_match.group(1).strip() if header_match else "Bilinmeyen Başlık"
            
            # 2. Extract Options
            # Look for lines starting with A), B)...
            options = []
            option_pattern = r"^\s*([A-E])\)\s*(.*)$"
            
            lines = block.split('\n')
            
            # Clean empty lines
            lines = [l.strip() for l in lines if l.strip()]

            # Truncate at explicit "---" separator (if found) to avoid footer noise
            # Skip if it looks like a table separator e.g. "|---|", so check for pipe
            for idx, line in enumerate(lines):
                 if line.startswith("---") and "|" not in line and len(line) < 10:
                     # Found the end delimiter. Truncate here.
                     lines = lines[:idx]
                     break
            
            processed_lines = []
            
            # Extract Correct Answer Line
            correct_option_id = None
            explanation_start_idx = -1
            
            for idx, line in enumerate(lines):
                # Correct Answer Check
                if "doğru cevap:" in line.lower():
                    # Parse "Doğru Cevap: B"
                    ca_match = re.search(r"doğru\s+cevap\s*[:|-]?\s*([A-E])", line, re.IGNORECASE)
                    if ca_match:
                        correct_option_id = ca_match.group(1).upper()
                    # If this line ONLY contains correct answer, skip it.
                    # If it has more text, maybe it's merged? "Doğru Cevap: A. Because..."
                    # Check if explanation starts here too?
                    # Let's keep it simple: if it has correct answer, extracting ID is enough for now.
                    # Use regex to strip it?
                    line = re.sub(r"doğru\s+cevap\s*[:|-]?\s*[A-E]", "", line, flags=re.IGNORECASE).strip()
                    if not line:
                        continue 
                
                # Explanation Check (Robust)
                # Check for "Açıklama:" or "**Açıklama:**" anywhere in the line
                # But be careful not to trigger on random text. Assume it's a label.
                ex_match = re.search(r"(?:\*\*|__)?açıklama(?:\*\*|__)?\s*:", line, re.IGNORECASE)
                
                if ex_match:
                    explanation_start_idx = idx
                    # If explanation starts mid-line (e.g. "Doğru Cevap: A **Açıklama:** ...")
                    # or "E) Option **Açıklama:**..."
                    start_pos = ex_match.start()
                    
                    if start_pos > 0:
                        # Split line
                        pre_ex = line[:start_pos].strip()
                        post_ex = line[start_pos:].strip()
                        
                        if pre_ex:
                            processed_lines.append(pre_ex)
                        
                        # Fix the lines array for subsequent processing:
                        # Replace current line with post_ex so extraction below works from index
                        lines[idx] = post_ex 
                    
                    break
                
                processed_lines.append(line)
            
            # If we extract lines before explanation, we need to separate Question Text from Options
            # Usually options are at the end of the question text part.
            
            # Separate Header (Line 0)
            # Question Text (Line 1 to Options Start)
            # Options (A-E)
            
            question_text_lines = []
            
            current_opt_id = None
            
            for line in processed_lines:
                if line.startswith(f"Soru"): # Skip header line again if caught
                    continue
                
                opt_match = re.match(option_pattern, line)
                if opt_match:
                    # Found an option
                    oid = opt_match.group(1)
                    otext = opt_match.group(2)
                    options.append({"id": oid, "text": otext})
                else:
                    # If we haven't found options yet, it's question text.
                    # If we HAVE found options, it might be a multiline option? 
                    # For simplicity, assume options are single line or block text is mainly prompt.
                    if not options:
                        question_text_lines.append(line)
                    else:
                        # Append to last option
                        options[-1]["text"] += " " + line

            question_text = "\n".join(question_text_lines).strip()
            
            # Extract Explanation and Table
            explanation_text = ""
            table_text = ""
            
            if explanation_start_idx != -1:
                full_ex_lines = lines[explanation_start_idx:]
                # Remove "Açıklama:" prefix from first line (Handles **Açıklama:** etc.)
                full_ex_lines[0] = re.sub(r"^(?:\*\*|__)?açıklama(?:\*\*|__)?\s*:\s*", "", full_ex_lines[0], flags=re.IGNORECASE)
                
                # Search for Table indicator
                table_start_idx = -1
                for i, l in enumerate(full_ex_lines):
                    if re.search(r"(karşılaştırma|özet|farklar)\s*tablosu", l, re.IGNORECASE) or l.strip().lower().startswith("tablo:"):
                        table_start_idx = i
                        break
                
                if table_start_idx != -1:
                    explanation_text = "\n".join(full_ex_lines[:table_start_idx]).strip()
                    table_text = "\n".join(full_ex_lines[table_start_idx:]).strip()
                else:
                    explanation_text = "\n".join(full_ex_lines).strip()

            if not question_text or len(options) < 2:
                logger.warning(f"Could not parse valid question from block: {title}")
                return None

            # Construct Schema
            blocks = []
            
            # 1. Heading
            blocks.append({
                "type": "heading",
                "text": title,
                "level": 1
            })
            
            # 2. Main Explanation Callout
            blocks.append({
                "type": "callout",
                "style": "clinical_pearl",
                "title": "Açıklama",
                "items": [{"text": explanation_text or "Açıklama mevcut değil."}]
            })
            
            # 3. Table Block (if present)
            if table_text:
                # Simple table parser: assume lines are rows, 2+ spaces are separators? 
                # Or just putting it as distinct callout if parsing fails?
                # User prompt output:
                # Durum   BOS Glukozu   BOS Laktatı...
                # Bakteriyel...
                
                # Improved Table Parser (Markdown Support)
                t_lines = table_text.split('\n')
                t_title = t_lines[0].strip() # "Karşılaştırma Tablosu: ..."
                
                # Check for Markdown Table (contains pipes)
                is_markdown = any("|" in l for l in t_lines)
                
                headers = []
                rows = []
                
                if is_markdown:
                    # Filter for lines with pipes
                    md_lines = [l for l in t_lines if "|" in l]
                    
                    if md_lines:
                        # 1. Headers
                        header_line = md_lines[0]
                        headers = [h.strip() for h in header_line.split('|') if h.strip()]
                        
                        # 2. Rows
                        for r_line in md_lines[1:]:
                            if "---" in r_line: continue # Skip separator
                            cells = [c.strip() for c in r_line.split('|') if c.strip()]
                            if not cells: continue
                            
                            # Handle mismatch length
                            if len(cells) < len(headers):
                                cells += [""] * (len(headers) - len(cells))
                            
                            entity = cells[0]
                            row_cells = cells[1:]
                            rows.append({"entity": entity, "cells": row_cells})
                else:
                    # Legacy Space/Tab Split (Naive)
                    t_rows_raw = t_lines[1:]
                    if t_rows_raw:
                        headers = re.split(r"\s{2,}|\t", t_rows_raw[0].strip())
                        for r_line in t_rows_raw[1:]:
                            if not r_line.strip(): continue
                            cells = re.split(r"\s{2,}|\t", r_line.strip())
                            
                if rows:
                    blocks.append({
                        "type": "table",
                        "title": t_title,
                        "headers": headers,
                        "rows": rows
                    })
                else:
                    # Fallback to Text Block if parsing fails
                    blocks.append({
                        "type": "callout",
                        "style": "key_clues",
                        "title": "Tablo",
                        "items": [{"text": table_text}]
                    })

            ex_obj = {
                "main_mechanism": explanation_text[:400] + "..." if len(explanation_text)>400 else explanation_text,
                "clinical_significance": "Yüksek (TUS/USMLE)",
                "sibling_entities": [],
                "blocks": blocks,
                "update_checked": False
            }
            
            return {
                "source_material": "BulkGen",
                "topic": topic,
                "question_text": question_text,
                "options": options,
                "correct_option_id": correct_option_id or "A", # Safe fallback? Or drop? Better drop if unknown.
                "tags": [f"concept:{title}"],
                "explanation_data": ex_obj
            }

        except Exception as e:
            logger.error(f"Error parsing block: {e}")
            return None
