"""
DeepSeek API Client for Block-Based Question Generation
"""

import os
import json
import re
from typing import Optional, Dict, Any, List

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import time
import random
import logging
import openai
from openai import OpenAI
from .gemini_client import (
    construct_system_prompt_draft,
    construct_system_prompt_blocks,
    SYSTEM_PROMPT_CRITIQUE,
    SYSTEM_PROMPT_RECONCILE,
    SYSTEM_PROMPT_TABLE_REFINE,
    SYSTEM_PROMPT_REPAIR,
    DISCIPLINE_FOCUS_PROFILES
)
from .rate_limiter import RateLimiter

class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not found. Please add it to your .env file.")
        
        # DeepSeek uses OpenAI Client with custom base URL
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=120.0
        )
        
        # Load Reference Examples
        self.reference_examples = self._load_reference_examples()
        
        # Models
        self.default_model = "deepseek-chat"      # V3 (fast, capable)
        self.reasoning_model = "deepseek-reasoner" # R1 (reasoning expert)
        
    def _load_reference_examples(self) -> dict:
        try:
            with open("reference_examples.json", "r") as f:
                return json.load(f)
        except:
            return {}

    def _get_examples_text(self, topic: str) -> str:
        """Retrieves formatted examples based on the topic/subject."""
        # Reuse logic from OpenAIClient (or abstract it, but duplicating for safety/speed now)
        key = "Pathology (Temel)" # Default
        if "Patoloji" in topic: key = "Pathology (Temel)"
        elif "Dahiliye" in topic: key = "Internal Medicine (Dahiliye - Klinik)"
        elif "Pediatri" in topic: key = "Pediatrics (Pediatri - Klinik)"
        elif "Cerrahi" in topic: key = "General Surgery (Genel Cerrahi - Klinik)"
        elif "Kadin" in topic or "Kadın" in topic: key = "Obstetrics & Gynecology (Kadın Doğum - Klinik)"
        elif "Mikrobiyoloji" in topic: key = "Microbiology (Temel)"
        elif "Farmakoloji" in topic: key = "Pharmacology (Temel)"
        elif "Biyokimya" in topic: key = "Biochemistry (Temel)"
        elif "Fizyoloji" in topic: key = "Physiology (Temel)"
        elif "Anatomi" in topic: key = "Anatomy (Temel)"
        elif "Stajlar" in topic: key = "Minor Internships (Küçük Stajlar - Klinik)"
        
        examples = self.reference_examples.get(key, [])
        if not examples:
            return ""
            
        # Format explicitly
        out = []
        for i, ex in enumerate(examples[:2]): # Match Gemini example count
            out.append(f"ÖRNEK {i+1}:")
            out.append(f"Soru: {ex.get('question', '')}")
            out.append(f"Seçenekler: {json.dumps(ex.get('options', []))}")
            out.append("---")
            
        return "\n".join(out)

    def _safe_json_load(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return {}
        # Remove markdown code blocks if present
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        text = text.replace("\x00", "")
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                parsed, _ = decoder.raw_decode(text[match.start():])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        # Simple fallback
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end])
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass
        logging.warning(f"⚠️ JSON Parse Error: {text[:200]}...")
        return {}

    def _call_api(self, system_prompt: str, user_prompt: str, model: str = None, json_mode: bool = True) -> dict:
        model = model or self.default_model
        max_retries = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 1. Wait for Rate Limit Slot
                RateLimiter.wait_for_slot()
                
                kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.7
                }
                if json_mode:
                    # DeepSeek supports json_object type
                    kwargs["response_format"] = {"type": "json_object"}
                    
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                return self._safe_json_load(content)
                
            except openai.RateLimitError as e:
                logging.warning(f"⚠️ DeepSeek Rate Limit (429): {e}. Attempt {attempt+1}/{max_retries}")
                # Trigger Circuit Breaker logic
                RateLimiter.trigger_circuit_breaker(duration=30 + (attempt * 10))
                # Jitter sleep already happens in wait_for_slot next loop, but we can do extra here
                time.sleep(random.uniform(1, 3))
                
            except openai.APIConnectionError as e:
                logging.warning(f"⚠️ DeepSeek Connection Error: {e}. Retrying...")
                time.sleep(random.uniform(2, 5))
                
            except openai.APIStatusError as e:
                 logging.error(f"⚠️ DeepSeek Status Error: {e.status_code} - {e.message}")
                 if e.status_code >= 500:
                     time.sleep(random.uniform(2, 5)) # Retry on server errors
                 else:
                     return {} # Give up on 400s
            except Exception as e:
                print(f"⚠️ DeepSeek Unexpected Error: {e}")
                return {}
        
        return {}

    def draft_question(self, concept: str, evidence: str, topic: str, strict: bool = True, **kwargs) -> dict:
        discipline = kwargs.get("discipline")
        examples_text = self._get_examples_text(topic)
        system_prompt = construct_system_prompt_draft(examples_text, discipline)
        user_prompt = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK:\n{evidence}"
        if not strict:
            user_prompt += (
                "\n\nZORUNLU KURAL (RELAXED): "
                "KAYNAK boş değilse 'insufficient_evidence' döndürme. "
                "Metindeki en az bir bilgiyle kısa/spot bir soru üret."
            )
        # Upgrade to Reasoner (R1) for Pro-level drafting behavior
        return self._call_api(system_prompt, user_prompt, model=self.reasoning_model)

    def critique_question(self, draft: dict, evidence: str, topic_verification_result: dict = None, **kwargs) -> dict:
        topic_feedback_str = ""
        if topic_verification_result:
            matched = topic_verification_result.get("topic_match", True)
            feedback = topic_verification_result.get("feedback_for_critique", "No specific feedback.")
            predicted = topic_verification_result.get("predicted_topic", "Unknown")
            
            topic_feedback_str = f"""
            TOPIC ALIGNMENT REPORT:
            - Match: {matched}
            - Predicted Topic: {predicted}
            - FEEDBACK: "{feedback}"
            
            INSTRUCTION FROM TOPIC ANALYST:
            If 'Match' is False, you MUST REVISE the question to align with the target topic or fix the drift. 
            Use the FEEDBACK provided.
            """

        user_prompt = f"SORU: {json.dumps(draft, ensure_ascii=False)}\n\n{topic_feedback_str}\n\nKAYNAK:\n{evidence}"
        return self._call_api(SYSTEM_PROMPT_CRITIQUE, user_prompt)

    def reconcile_updates(self, main_evidence: str, update_evidence: str) -> list:
        if not update_evidence: return []
        user_prompt = f"MAIN:\n{main_evidence}\nUPDATES:\n{update_evidence}"
        resp = self._call_api(SYSTEM_PROMPT_RECONCILE, user_prompt)
        return resp.get("updates_applied", [])

    def refine_table_block(self, table_block: dict, context: dict) -> dict:
        payload = {
            "context": context,
            "table": table_block,
        }
        user_prompt = f"GİRİŞ:\n{json.dumps(payload, ensure_ascii=False)}"
        resp = self._call_api(SYSTEM_PROMPT_TABLE_REFINE, user_prompt)
        return resp if isinstance(resp, dict) else {}

    def check_topic_alignment(self, question_text: str = None, correct_option: str = None, target_topic: str = None, draft: dict = None, evidence: str = "", **kwargs) -> dict:
        if draft and isinstance(draft, dict):
            question_text = question_text or draft.get("question_text", "")
            correct_option = correct_option or next(
                (o.get("text") for o in draft.get("options", []) if isinstance(o, dict) and o.get("id") == draft.get("correct_option_id")),
                "Unknown"
            )
        evidence_text = evidence or ""
        gate_prompt = f"""
        YOU ARE A TOPIC ALIGNMENT + CORRECTION SPECIALIST.

        TARGET TOPIC: {target_topic}

        DRAFT (JSON):
        {json.dumps(draft if isinstance(draft, dict) else {{"question_text": question_text, "correct_option": correct_option}}, ensure_ascii=False)}

        EVIDENCE (may be empty):
        {evidence_text if evidence_text else "NO_TEXT_EVIDENCE"}

        TASKS:
        1) Decide if the draft belongs to the TARGET TOPIC.
        2) If the stem/options are wrong or drifted, REVISE within the same context.
        3) ABORT KULLANMA. Her zaman revise veya accept dön.

        RULES FOR REVISION:
        - Keep 5 options (A-E) and a single correct answer.
        - Keep the style and clinical context.
        - Prefer using the evidence; if evidence is partial, narrow the question instead of aborting.
        - If minor issues but single correct answer exists, you may ACCEPT.
        - Preserve concept_tag / brief_explanation if present.

        OUTPUT JSON:
        {{
            "topic_match": true/false,
            "predicted_topic": "string",
            "reason": "short explanation",
            "action": "accept|revise|abort",
            "revised_draft": {{...}}  # only if action == "revise"
        }}
        """
        return self._call_api("You are a topic alignment specialist.", gate_prompt, model="deepseek-chat")

    def diagnose_abort(
        self,
        stage: str,
        draft: dict,
        evidence: str,
        target_topic: str = None,
        concept: str = None,
        payload: dict = None
    ) -> dict:
        evidence_text = evidence or ""
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        draft_json = json.dumps(draft or {}, ensure_ascii=False)
        user_prompt = f"""
        YOU ARE A DEBUGGING ASSISTANT FOR MEDICAL MCQ GENERATION.

        STAGE: {stage}
        CONCEPT: {concept}
        TARGET_TOPIC: {target_topic}

        DRAFT (JSON):
        {draft_json}

        ABORT_CONTEXT (JSON):
        {payload_json}

        EVIDENCE (may be empty):
        {evidence_text if evidence_text else "NO_TEXT_EVIDENCE"}

        TASK:
        - Explain why the draft could not be safely revised or accepted.
        - Identify if the evidence is off-topic, missing key facts, or contradicts the draft.
        - Suggest a minimal fix that WOULD make it valid, if possible.
        - If it should be re-generated from scratch, say so.

        OUTPUT JSON:
        {{
            "root_cause": "short",
            "evidence_coverage": "good/partial/none",
            "drifted_topic": "string or null",
            "missing_evidence": ["..."],
            "suggested_fix": "short",
            "can_autofix": true/false,
            "minimal_revision": {{ ... }} ,  # optional draft JSON
            "confidence": 0.0
        }}
        """
        return self._call_api("You are a debugging assistant.", user_prompt, model="deepseek-chat")

    def extract_concepts(self, text: str, topic: str, count: int = 20, **kwargs) -> list:
        avoid_concepts = kwargs.get("avoid_concepts")
        avoid_block = ""
        if avoid_concepts:
            trimmed = [c for c in avoid_concepts if c][:200]
            if trimmed:
                avoid_lines = "\n".join([f"- {c}" for c in trimmed])
                avoid_block = f"""
        EXCLUDE LIST (KESİNLİKLE ÇIKARMA):
        Aşağıdaki kavramları LİSTELEME. Bunların eşanlamlılarını da üretme.
        {avoid_lines}
                """
        prompt_text = f"""
        TASK: Identify {count} distinct, high-yield clinical concepts or diseases from the attached content below for exam question generation.
        TOPIC: {topic}
        
        RULES:
        1. Output JSON: {{ "concepts": [{{"concept": "...", "reason": "...", "evidence": "..."}}] }}.
        2. Focus on specific pathologies (e.g. "Papillary Thyroid Carcinoma", "Addison's Disease").
        3. Avoid generic terms (e.g. "Anatomy", "Introduction").
        4. NO SYNONYMS: Do NOT list the same concept twice (e.g. "Crohn" vs "Crohn Hastalığı" -> Pick ONE).
        5. LANGUAGE: Turkish (Medical Terminology).
        6. "reason" = kısa gerekçe (<= 20 kelime), neden high-yield.
        7. "evidence" = metinden kısa alıntı (<= 25 kelime) veya tablo hücre özeti.
        8. Avoid the excluded concepts list below.
        {avoid_block}
        
        TEXT:
        {text if text else "Attached PDF Document."}
        """
        resp = self._call_api("You are a medical concept extractor.", prompt_text)
        return resp.get("concepts", [])

    def generate_explanation_blocks(self, draft: dict, critique: dict, updates: list, evidence: str, source_material: str, topic: str, use_pro_model: bool = False, **kwargs) -> dict:
        discipline = kwargs.get("discipline")
        siblings = critique.get("sibling_suggestions", [])
        request_context = {
            "draft": draft,
            "siblings": siblings,
            "updates": updates,
            "source_material": source_material,
            "topic": topic
        }

        table_hint = ""
        if discipline:
            table_hint = (
                "\n        TABLO KURALI:"
                "\n        - İlk sütun \"Özellik\" veya \"Kriter\" olsun."
                "\n        - Diğer sütunlar gerçek varlık/antite isimleri olsun (doğru + kardeş antiteler)."
                "\n        - \"Doğru/Ayırıcı/Çeldirici\" gibi meta başlıklar kullanma."
                "\n        - Bir sütunda birden fazla varlık birleştirme; gerekiyorsa yeni sütun aç (max 4)."
            )

        level_instruction = """
        KURAL: HEDEF KİTLE (TUS Adayı / İntörn Doktor)
        - HEDEF: Karşındaki kişi Son Sınıf Tıp Öğrencisidir (İntörn).
        - BİLGİ DÜZEYİ: İleri. Temel fizyopatolojik mekanizmaları bildiğini varsay.
        - DİL: Profesyonel tıbbi terminoloji kullan. Basitleştirmekten kaçın. LLM olarak kendini kısıtlama.
        - ODAK: Sınavda çıkabilecek 'High-Yield' bilgilere, ayırıcı tanıdaki ince detaylara ve klinik tuzaklara odaklan.
        """

        prompt_text = f"""
        GİRDİ VERİSİ:
        {json.dumps(request_context, ensure_ascii=False)}
        
        KAYNAK:
        {evidence if evidence else "Attached PDF Document."}
        
        Bu verileri kullanarak ŞEMAYA TAM UYGUN JSON çıktısı üret.
        - Options listesi "id" ve "text" içermeli.
        - Explanation nesnesi "blocks" içermeli.
        
        KURAL: KARŞILAŞTIRMA (SIBLING ANALYSIS)
        - Kaynakta geçen diğer benzer hastalıkları/ilaçları (Sibling Entities) tespit et.
        - 'mini_ddx' ve 'table' bloklarında mutlaka bu antitelerle karşılaştırma yap.
        - Sadece şıklardaki çeldiricileri değil, metindeki diğer önemli karışabilecek durumlara da değin.
        {table_hint}
        {level_instruction}
        """

        try:
            from backend.database import get_all_visual_tags
            existing_visual_tags = get_all_visual_tags()
        except Exception:
            existing_visual_tags = []

        dynamic_blocks_prompt = construct_system_prompt_blocks(existing_visual_tags)

        model = self.reasoning_model
        return self._call_api(dynamic_blocks_prompt, prompt_text, model=model)

    def repair_json(self, broken_json_str: str, error_msg: str) -> dict:
        prompt = f"BROKEN JSON: {broken_json_str}\nERROR: {error_msg}\nFIX IT."
        return self._call_api(SYSTEM_PROMPT_REPAIR, prompt)

    def generate_flashcards(self, highlighted_text: str, topic: str) -> list:
        """
        Generates Q&A flashcards from user highlights.
        """
        prompt = f"""
        TASK: Create high-yield Flashcards (Q&A) from the following highlighted text.
        TOPIC: {topic}

        RULES (CRITICAL):
        1. Output JSON format ONLY: {{"flashcards": [{{"question_text": "...", "answer_text": "..."}}]}}
        2. **NO ABBREVIATIONS:** Do not use abbreviations. Expand to full Turkish medical terms.
        3. **SHORT Q/A:** Use short, single-sentence questions and answers.
           - Aim for 6-14 words per sentence.
           - If the highlight contains multiple facts, split into multiple flashcards.
        4. **NAMED ENTITIES PRIORITY:** If highlights include named entities (genes, drugs, syndromes, specific pathologies, appearances, clinical signs, adverse effects), make them the focus.
           - Use one named entity per card.
           - Ask for a specific attribute/mechanism/feature or ask for the name given a feature.
           - **COMPARISON EXCEPTION:** If the highlight explicitly compares similar entities, you MAY compare two entities in one card.
        5. **ANSWER LEAKAGE PREVENTION:** The key term or answer MUST NOT appear in the Question Text.
           - Bad: "What is the side effect of Digoxin?" (Too broad)
           - Bad: "Does Digoxin cause arrhythmia?" (Answer leaked)
           - Good: "Which cardiac glycoside causes yellow-green vision changes?" (Target: Digoxin)
        6. **SPECIFICITY:** Avoid generic questions. Target the specific fact in the highlight.
           - Highlight: "Digoksin sodyum-potasyum ATPazı inhibe eder." -> Question: "Digoksinin temel etki mekanizması nedir?" -> Answer: "Sodyum-potasyum ATPaz inhibisyonu."
           - Bad: "What are sides effects of Digoxin?" (Too many answers, not specific)
           - Good: "Furosemid hangi mekanizmayla digoksin toksisitesini artırır?" (Specific mechanism)
        7. **HINT REQUIREMENT:** If the question has multiple potential answers, provide a narrowing HINT in parentheses.
           - Example: "Which gastrointestinal side effect is earliest sign of toxicity? (Hint: Common symptom)"
        8. **CONTEXT:** Focus ONLY on the information explicitly highlighted. Do not hallucinate external facts.
        9. **SELF-CONTAINED (CRITICAL):** The question MUST be answerable WITHOUT seeing the source text.
           - BAD: "What are the findings associated with the highlighted text?"
           - BAD: "What does this passage describe?"
           - GOOD: "Sodyum-potasyum ATPazı inhibe eden ilaç hangisidir?"

        HIGHLIGHTS:
        {highlighted_text}
        """

        resp = self._call_api("You are an expert medical educator.", prompt, model=self.default_model)
        flashcards = resp.get("flashcards", []) if isinstance(resp, dict) else []
        return flashcards if isinstance(flashcards, list) else []

    def generate_flashcards_grouped(self, groups: list, max_cards: int = 30) -> list:
        """
        Generates flashcards from grouped highlights with metadata.
        Each output card includes a group_id to map back to its source.
        """
        prompt = f"""
        TASK: Create high-yield Flashcards (Q&A) from grouped highlights.
        You will receive a JSON list of groups. Each group contains:
        - group_id (integer, use this in output)
        - source_material (Use this for CONTEXT, especially for tables)
        - category
        - topic
        - tags
        - highlights (list of objects ORDERED by creation time):
          each item includes "text", optional "context_snippet", and optional "context_meta.table" fields
          where table metadata can include "title", "row", and "column"

        RULES:
        1. Output JSON format ONLY: {{"flashcards": [{{"group_id": 1, "question_text": "...", "answer_text": "..."}}]}}
        2. **LANGUAGE**: MUST be in **TURKISH**. (Both Question and Answer).
        3. **NO ABBREVIATIONS:** Do not use abbreviations. Expand to full Turkish medical terms.
        4. **SHORT Q/A:** Use short, single-sentence questions and answers.
           - Aim for 6-14 words per sentence.
           - If a group contains multiple facts, split into multiple flashcards.
        5. **ONE FACT PER CARD:** Do not combine multiple entities or mechanisms in one Q/A.
           - **COMPARISON EXCEPTION:** If a table or highlight explicitly contrasts two similar entities, you MAY compare them in one card.
           - Keep the question and answer short; limit to two entities.
        6. **NAMED ENTITIES PRIORITY:** If highlights include named entities (genes, drugs, syndromes, specific pathologies, appearances, clinical signs, adverse effects), make them the focus.
           - Use one named entity per card.
           - Ask for a specific attribute/mechanism/feature or ask for the name given a feature.
           - **COMPARISON EXCEPTION:** If the highlight explicitly compares similar entities, you MAY compare two entities in one card.
        7. **CONTEXT STRATEGY**:
           - The 'highlights' are the PRIMARY focus. Your question must test the highlighted fact.
           - Use 'context_snippet' to locate the highlight when the same word appears multiple times.
           - If 'context_meta.table' is present, use row/column labels to anchor the question.
           - Use 'source_material' to understand context.
           - **TABLES/COMPARISONS**: If highlights come from a table, use `source_material` to identify column headers and row labels.
        8. **ANSWER FORMAT**:
           - Be concise but educational.
           - If relevant, mention the Differentiation/Mechanism briefly.
        9. **SEQUENCE**: Highlights are ordered sequentially. Use this flow if they form a narrative.
        10. Avoid duplicates. Return at most {max_cards} flashcards total.
        11. If a group lacks enough context even with source_material, SKIP that group.

        GROUPS:
        {json.dumps(groups, ensure_ascii=False)[:20000]}
        """

        resp = self._call_api("You are a flashcard generator.", prompt, model=self.default_model)
        flashcards = resp.get("flashcards", []) if isinstance(resp, dict) else []
        return flashcards if isinstance(flashcards, list) else []

    def get_text_embedding(self, text: str) -> list:
        """
        DeepSeek has an embedding model v1/embeddings.
        We utilize it here if available, otherwise return empty list.
        """
        try:
            # Note: DeepSeek API for embeddings might use a different model name or same
            # Checking recent docs, they have 'deepseek-chat' for chat, 
            # for embeddings some providers use 'deepseek-embedding' or similar.
            # If fail, we graceful exit.
            
            # Using standard OpenAI embedding call format
            response = self.client.embeddings.create(
                model="deepseek-chat", # Fallback to chat if specific embedding model not known, 
                                      # although some APIs don't allow this.
                input=text[:8000]
            )
            return response.data[0].embedding
        except Exception as e:
            logging.warning(f"⚠️ DeepSeek Embedding Error: {e}")
            # Try a very simple model name common in some proxy layers
            try:
                response = self.client.embeddings.create(
                    model="deepseek-embed",
                    input=text[:8000]
                )
                return response.data[0].embedding
            except:
                return []

    def select_best_topic(self, question_text: str, all_topics: list) -> str:
        """Picks the most relevant topic from a list using the LLM."""
        topics_str = "\n".join([f"- {t}" for t in all_topics[:50]]) # Limit to first 50
        prompt = f"""
        Given the following medical question, select the MOST appropriate topic from the provided list.
        If no topic fits perfectly, return the closest one.
        ONLY return the topic name, nothing else.

        QUESTION: {question_text}
        
        TOPICS:
        {topics_str}
        """
        
        # Use simple chat model for selection
        resp = self.client.chat.completions.create(
            model=self.default_model,
            messages=[
                {"role": "system", "content": "You are a medical taxonomy expert. Return only the topic name."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        return resp.choices[0].message.content.strip()
