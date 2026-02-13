"""
Gemini API Client for Block-Based Question Generation (PROD-SAFE)

Features:
- Multi-stage prompts (Draft, Critique, Reconcile, Explain)
- Strict JSON schema enforcement via prompts
- Auto-repair loop
"""

import os
import json
import re
import time
import logging
from typing import Optional, Dict, Any, List

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- JSON SCHEMAS FOR STRUCTURED OUTPUT ---
from google import genai
from google.genai import types

SCHEMA_CONCEPT_LIST = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["concepts"]
}

SCHEMA_QUESTION_DRAFT = {
    "type": "object",
    "properties": {
        "question_text": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
                    "text": {"type": "string"}
                },
                "required": ["id", "text"]
            }
        },
        "correct_option_id": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
        "concept_tag": {"type": "string"},
        "brief_explanation": {"type": "string"},
        "insufficient_evidence": {"type": "boolean"},
        "reason": {"type": "string"}
    },
    "required": ["question_text", "options", "correct_option_id", "concept_tag", "brief_explanation"]
}

SCHEMA_FULL_RESPONSE = {
    "type": "object",
    "properties": {
        "source_material": {"type": "string"},
        "topic": {"type": "string"},
        "question_text": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, 
                    "text": {"type": "string"}
                },
                "required": ["id", "text"]
            }
        },
        "correct_option_id": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "explanation": {
            "type": "object",
            "properties": {
                "main_mechanism": {"type": "string"},
                "clinical_significance": {"type": "string"},
                "sibling_entities": {"type": "array", "items": {"type": "string"}},
                "update_checked": {"type": "boolean"},
                "blocks": {
                    "type": "array", 
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "title": {"type": "string"},
                            "style": {"type": "string"},
                            "level": {"type": "integer"},
                            "text": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}},
                            "items": {
                                "type": "array", 
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        # Union type sim via optional fields
                                        # For Callouts: just a string? No, SCHEMA says object.
                                        # Wait, callout items are usually strings in my prompt?
                                        # PROMPT says: "items": ["..."] for callout.
                                        # BUT "items": [{"option_id": ...}] for mini_ddx.
                                        # This polymorphism is hard for Strict Schema.
                                        # I'll define fields for DDX here, and simple strings will fail if the schema expects object.
                                        # SOLUTION: Split block types or make a superset object.
                                        
                                        # DDX Fields
                                        "option_id": {"type": "string"},
                                        "label": {"type": "string"},
                                        "why_wrong": {"type": "string"},
                                        "would_be_correct_if": {"type": "string"},
                                        "best_discriminator": {"type": "string"},
                                        
                                        # Simple Item (Callout) Helper - actually Callout items are strings in prompt description
                                        # BUT schema "items": {"type": "object"} forces object. 
                                        # I must change callout items to objects or make schema allow string?
                                        # Gemini Structured Output doesn't support "oneOf" (Union) well yet for primitives vs objects.
                                        # I will change the prompt/schema so Callout items are objects: {"text": "..."}
                                        "text": {"type": "string"}
                                    },
                                    # No required fields to allow flexibility between DDX and Callout
                                    "nullable": True
                                }
                            }, 
                            "headers": {"type": "array", "items": {"type": "string"}},
                            "rows": {
                                "type": "array", 
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "entity": {"type": "string"},
                                        "cells": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["entity", "cells"]
                                }
                            }
                        },
                        "required": ["type"]
                    }
                }
            },
            "required": ["main_mechanism", "blocks"]
        }
    },
    "required": ["question_text", "options", "correct_option_id", "explanation"]
}

SCHEMA_FLASHCARDS = {
    "type": "object",
    "properties": {
        "flashcards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_text": {"type": "string"},
                    "answer_text": {"type": "string"}
                },
                "required": ["question_text", "answer_text"]
            }
        }
    },
    "required": ["flashcards"]
}

SCHEMA_FLASHCARDS_GROUPED = {
    "type": "object",
    "properties": {
        "flashcards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer"},
                    "question_text": {"type": "string"},
                    "answer_text": {"type": "string"}
                },
                "required": ["group_id", "question_text", "answer_text"]
            }
        }
    },
    "required": ["flashcards"]
}

SCHEMA_DUPLICATE_CHECK = {
    "type": "object",
    "properties": {
        "is_duplicate": {"type": "boolean"},
        "similar_to_id": {"type": "integer"},
        "reason": {"type": "string"}
    },
    "required": ["is_duplicate", "reason"]
}


# ============================================================================
# MODEL CONFIGURATION & FALLBACK
# ============================================================================

# Model Priority (Best → Fallback)
# Model Priority (Best → Fallback)
# Model Priority (Best → Fallback)
MODEL_PRIORITY_FLASH = [
    "gemini-3-flash-preview",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

# User requested NO PRO models due to cost.
# We redirect PRO requests to the strongest available FLASH model.
MODEL_PRIORITY_PRO = MODEL_PRIORITY_FLASH.copy()

MAX_RETRIES_PER_MODEL = 2

# ============================================================================
# PROMPTS
# ============================================================================

# ============================================================================
# PROMPTS
# ============================================================================

def construct_system_prompt_draft(examples_text=""):
    base_prompt = """Türkçe tıp sınavı soru yazarısın. 
    Görevin: Verilen metinden TUS/USMLE standardında soru taslağı çıkarmak.

    ÖNEMLİ: Soru tipi, içeriğe en uygun olan formatta seçilmelidir. Kendini tek bir tiple sınırlama:
    
    1. KLİNİK VİNYET (Vaka Sorusu): 
       - Hasta öyküsü, fizik muayene ve laboratuvar içerir. 
       - Tanı, tedavi veya yönetim sorulur.
       - Derinlemesine analiz gerektiren konularda tercih et.

    2. SPOT BİLGİ (Yüksek Verimli Fact):
       - "En sık görülen neden nedir?", "Patogenezdeki temel defekt nedir?", "Gold standart tanı yöntemi nedir?"
       - "Treatment of choice" (İlk tercih tedavi) nedir?
       - Eğer metin net bir "En Sık", "En Önemli", "Kesin Tanı" bilgisi içeriyorsa, bu formatı kullan. Vinyet zorlama.

    3. MEKANİZMA / FİZYOPATOLOJİ:
       - "Aşağıdaki ilaçlardan hangisi bu yan etkiye neden olur?" (Direkt farmakoloji)
       - "Bu hastalıkta hangisinin görülmesi BEKLENMEZ?" (Negatif soru kökü)

    4. İFADE DOĞRULAMA (Statement Validation) - ÇOK VERİMLİ:
       - Soru kökünde bir varlık (ilaç, hastalık, sendrom) tanıtılır.
       - Her şık, o varlık hakkında ayrı bir GERÇEK İFADE içerir.
       - Öğrenci hangisinin DOĞRU veya YANLIŞ olduğunu bulmalı.
       - ÖRNEK: "Digoksin zehirlenmesi ile ilgili aşağıdakilerden hangisi DOĞRUDUR?"
           A) İlk bulgu gastrointestinal semptomlardır (DOĞRU)
           B) Kırmızı dikromatopsi görülür (YANLIŞ - sarı-yeşil olmalı)
           C) QT uzaması tipiktir (YANLIŞ - ST çökmesi/tersine tick)
           D) Hiperkalemi riski azaltır (YANLIŞ - artırır)
           E) Antidot olarak kalsiyum glukonat verilir (YANLIŞ - Digibind)
       - AVANTAJ: Tek soruda 5 farklı bilgi test edilir. Uzun vinyetten daha verimli.

    5. ROMA RAKAMI KOMBİNASYONU (I, II, III, IV Formatı) - KLASİK TUS FORMATI:
       - Soru kökünde 3-5 madde Roma rakamlarıyla listelenir (I, II, III, IV, V).
       - Bazıları doğru, bazıları yanlış.
       - Şıklarda bu maddelerin kombinasyonları sorulur: "I ve II", "I ve III", "II ve IV" gibi.
       - ÖRNEK: "Damar dışındaki lökositlerin inflamasyon bölgesine kemotaksisinde;
           I. Tromboksan A₂
           II. Lökotrien B₄
           III. Prostaglandin I₂
           IV. Bakteriyel peptidler
           moleküllerinden hangileri önemli rol oynar?"
           A) I ve II
           B) I ve III
           C) I ve IV
           D) II ve III
           E) II ve IV ← DOĞRU
       - AVANTAJ: Öğrenci tüm maddeleri değerlendirmeli. Çoklu bilgi testi.

    KURALLAR:
    1. ESNEK OL: Her soru vaka olmak zorunda değil. "Spot" bilgiler için kısa ve net sorular yaz.
    2. 5 seçenek (A-E), sadece bir doğru.
    3. Çeldiriciler mantıklı ve ayırıcı tanıda olmalı.

    CRITICAL RULE: PRIORITY ON GENERATION
    - You MUST generate a question based on the provided text.
    - If the text is a list of facts, create a "Which of the following is TRUE/FALSE" or "Most Common" question.
    - Only return "insufficient_evidence" if the text is completely empty or non-medical nonsense.

    GUIDELINE: HANDLING DIAGNOSIS (CONTEXT AWARE)
    - **Testing Diagnosis?** If the goal is to see if the user can identify the disease, DESCRIBE the findings (Vignette) and do NOT name it.
    - **Testing Management/Treatment?** If the goal is to ask how to treat a specific known condition, you CAN state the disease name (e.g., "In a patient with Acute Pancreatitis...").
    - **Testing a Fact?** (e.g., "Most common cause"), you can be direct.
    
    GUIDELINE: SCOPE & COVERAGE (CRITICAL)
    - **SCAN FULL TEXT:** Look at potentially ALL headers, sub-topics, and sections in the provided text.
    - **NO LOCATION BIAS:** Valuable info can be at the start, middle, or end. Evaluate everything.
    - **INTEGRATE:** Synthesize info from defined parts (e.g. Symptoms from start + Treatment from end).
    - **AVOID TUNNEL VISION:** Don't get stuck on the first sentence or paragraph. Scan the whole document structure before deciding what to ask.

    GUIDELINE: TWO-LAYER QUESTIONS (ADVANCED - PREFERRED)
    - **HIDE THE ENTITY, ASK MORE:** When using the "don't name the disease" strategy (or "don't name the drug/pathology/syndrome"):
        - You can STILL ask about the entity itself as one of the **answer options**.
        - Add 4 realistic *distractor* alternatives from related or confused entities.
    - **EXAMPLES:**
        - If describing digoxin toxicity symptoms (yellow-green vision, arrhythmia) without naming "digoxin":
            - Instead of only asking "Mechanism?" (with mechanism options)...
            - You CAN ask "Which drug is responsible?" with options: Digoxin, Verapamil, Amiodarone, Metoprolol, Diltiazem.
            - This tests if the student can IDENTIFY the drug AND knows its clinical picture.
        - If describing a classic clinical picture (e.g., Kayser-Fleischer rings, neuropsych symptoms):
            - Options could be disease names: Wilson, Hemochromatosis, PBC, Alpha-1 Antitrypsin, Gaucher.
    - **WHEN TO USE:** This approach is PREFERRED when the clinical scenario is clear enough to be matched to a specific entity. It increases cognitive demand and educational value.

    NEGATIVE CONSTRAINTS (IGNORE THESE):
    - **WATERMARKS:** Ignore names like "Yusuf Kemal", "TUSDATA", IDs (e.g., "178908"), or copyright footers ("Telif Hakları...").
    - **NON-MEDICAL TEXT:** Ignore page numbers, file paths, or random artifacts.
    - **FOCUS:** Extract ONLY the medical content. Never include the watermark text in the question stem or options.
    - Use your judgment to create the most educational and logical question flow. Don't let rigid formatting rules block a good question.

REFERANS ÖRNEKLER (BU STİLDE YAZ):
{examples}

ÇIKTI (JSON):
{
    "question_text": "...",
    "options": [
        {"id": "A", "text": "..."},
        {"id": "B", "text": "..."},
        {"id": "C", "text": "..."},
        {"id": "D", "text": "..."},
        {"id": "E", "text": "..."}
    ],
    "correct_option_id": "A",
    "concept_tag": "concept:...",
    "brief_explanation": "..."
}
"""
    return base_prompt.replace("{examples}", examples_text)

SYSTEM_PROMPT_DRAFT_BASE = construct_system_prompt_draft()


SYSTEM_PROMPT_CRITIQUE = """Sen kıdemli bir tıp editörüsün.
Görevin: Taslak soruyu incelemek, hataları bulmak ve "Kardeş Antite" (Sibling Entity) önerileri sunmak.

ANALİZ ET:
1. Soru kurgusu hatasız mı?
2. Doğru cevap kesinlikle tek mi?
3. Çeldiriciler yeterince güçlü mü?
4. SIBLING ÖNERİSİ: Bu hastalıkla en sık karışan 2-4 hastalık nedir? (Tablo için lazım)

ÇIKTI (JSON):
{
    "critique_passed": boolean,
    "feedback": "...",
    "sibling_suggestions": ["Hastalık A", "Hastalık B", ...],
    "improved_distractors": ["...", ...] (optional)
}
"""

SYSTEM_PROMPT_RECONCILE = """Sen bir tıbbi güncelleme uzmanısın.
Görevin: Ana kaynak metni (MAIN_EVIDENCE) ile varsa güncelleme metnini (UPDATE_EVIDENCE) karşılaştırmak.

GÖREVLER:
1. UPDATE metninde, MAIN metnini değiştiren veya geçersiz kılan bir bilgi var mı?
2. Eğer varsa, bu değişikliği özetle.
3. Eğer çelişki tam çözülemiyorsa 'unresolved_conflict' olarak işaretle.

ÇIKTI (JSON):
{
    "updates_found": boolean,
    "updates_applied": [
        {
            "source_file": "Dosya adı veya 'Update PDF'",
            "change_summary": "Eski bilgi X idi, yeni bilgi Y oldu.",
            "priority": "update_overrides_main" OR "unresolved_conflict"
        }
    ]
}
"""

SYSTEM_PROMPT_BLOCKS = """Sen seçkin bir tıp profesörüsün.
Görevin: Sorunun detaylı açıklamasını JSON formatında, ZORUNLU BLOK yapısında üretmek.

ZORUNLU BLOK SIRASI (Kesinlikle uyulmalı):
1. `heading` -> "Detaylı Açıklama & Mekanizma"
2. `callout` (key_clues) -> Vakadaki 3-5 ipucu
3. `numbered_steps` -> Patofizyoloji zinciri (4-8 adım)
4. `callout` (exam_trap) -> Sınav tuzağı
5. `mini_ddx` -> Yanlış şıkların her biri için analiz. (Doğru şık hariç diğer tüm şıklar)
6. `table` -> Doğru cevap vs Kardeş Antiteler

TABLO KURALLARI:
- Başlık satırı (headers) HARİÇ, her satırda (header sayısı - 1) kadar hücre olmalı.
- Headers listesi: 1. eleman = Entity Label, 2..N elemanlar = Value Columns.
- Rows.cells uzunluğu N-1 olmalı.

ÇIKTI ŞEMASI (JSON):
{
  "source_material": "Küçük Stajlar",
  "topic": "Nöroloji",
  "question_text": "...",
  "options": [{"id": "A", "text": "..."}, ...],
  "correct_option_id": "A",
  "tags": ["concept:..."],
  "explanation": {
      "main_mechanism": "Kısa özet (max 280 karakter)",
      "clinical_significance": "Kısa özet (max 280 karakter)",
      "sibling_entities": ["...", "..."],
      "updates_applied": [],
      "update_checked": true,
      "blocks": [
        { "type": "heading", "level": 1, "text": "Detaylı Açıklama & Mekanizma" },
        { "type": "callout", "style": "key_clues", "title": "Klinik İpuçları", "items": [{"text": "..."}, {"text": "..."}] },
        { "type": "numbered_steps", "title": "Mekanizma Zinciri", "steps": ["...", "..."] },
        { "type": "callout", "style": "exam_trap", "title": "Sınav Tuzağı", "items": [{"text": "..."}] },
        { "type": "mini_ddx", "title": "Çeldirici Analizi", "items": [
            {"option_id": "B", "label": "...", "why_wrong": "...", "would_be_correct_if": "...", "best_discriminator": "..."}
          ] 
        },
        { "type": "table", "title": "Ayırıcı Tanı", "headers": ["Özellik", "Doğru Cevap", "Kardeş 1"], 
          "rows": [
            {"entity": "Etiyoloji", "cells": ["...", "..."]}
          ]
        }
      ]
  }
}
"""

SYSTEM_PROMPT_REPAIR = """You are a JSON repair expert.
Your Task: Fix the broken JSON provided by the user so it matches the Pydantic schema perfectly.

COMMON FIXES:
1. `mini_ddx` items must match exactly the number of WRONG options in the question.
   - Look at `options` list and `correct_option_id`.
   - Ensure every wrong option ID has exactly one entry in DDX.
2. `table` rows must have correct cell count matching headers (headers column - 1).
3. `option_id` must be A, B, C, D, or E.
4. `blocks` list must have exactly 6 items in specific order.
5. **CRITICAL**: For `callout` blocks:
   - Use `type: "callout"`.
   - Include a `title`.
   - `items` MUST be a list of OBJECTS: `[{"text": "Point 1"}, {"text": "Point 2"}]`. Do NOT use strings directly.
6. Ensure `options` is a list of objects `{"id": "A", "text": "..."}`.

Output ONLY valid JSON.
"""

SYSTEM_PROMPT_DUPLICATE_CHECK = """Sen uzman bir sınav analizörüsün.
Görevin: Yeni yazılan sorunun (DRAFT), veritabanındaki eski sorularla (EXISTING) aynı olup olmadığını (Duplicate) tespit etmek.

DRAFT QUESTION:
{draft_question}

EXISTING QUESTIONS:
{existing_questions_list}

ANALİZ KURALLARI:
1. Sadece "Aynı şeyi soran" sorular duplicate sayılır (Semantic Similarity > 0.9).
   - Farklı sayılar, farklı hasta yaşı/cinsiyeti olsa bile ÖZÜ aynıysa duplicate'tir.
   - Örnek: "X ilacının yan etkisi nedir?" ile "Aşağıdakilerden hangisi X'in yan etkisidir?" aynidir.
2. Farklı bir yönü soruyorsa duplicate DEĞİLDİR.
   - Örnek: "X'in tanısı nedir?" vs "X'in tedavisi nedir?" -> FARKLI.
   - Örnek: "En sık sebep Y" vs "En iyi tedavi Z" -> FARKLI.

ÇIKTI (JSON):
{
    "is_duplicate": boolean,
    "similar_to_id": int or null,
    "reason": "kısa açıklama (neden duplicate veya değil)"
}
"""


# ============================================================================
# CLIENT CLASS
# ============================================================================

class GeminiClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found.")
        
        self.client = genai.Client(api_key=self.api_key)
        
        # Load Reference Examples
        self.reference_examples = self._load_reference_examples()
        
        # Models Configuration
        # Defaults per user request
        self.flash_model_name = "gemini-3-flash-preview"
        self.pro_model_name = "gemini-3-flash-preview"

        # Rate Limiting (Token Bucket)
        # 15 RPM = 1 request every 4 seconds per thread? No, global bucket.
        # We share this client instance or we assume 15 RPM total for the API key.
        # Let's implementation a simple class-level safe-guard if instanced per thread, 
        # but ideally this should be global. JobManager uses new instance per job?
        # Actually background_jobs.py creates new instance per job.
        # So we'll use a class-level bucket.
        
    # Class-level rate limiter
    _last_request_time = 0
    _request_interval = 2.0 # Min seconds between global requests (conservative 30 RPM)

    def _wait_for_rate_limit(self):
        """Simple global rate limiter to prevent 429s"""
        current = time.time()
        elapsed = current - GeminiClient._last_request_time
        if elapsed < GeminiClient._request_interval:
            sleep_time = GeminiClient._request_interval - elapsed
            time.sleep(sleep_time)
        GeminiClient._last_request_time = time.time()

    def _load_reference_examples(self) -> dict:
        """Loads the reference_examples.json file."""
        try:
            with open("reference_examples.json", "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load reference examples: {e}")
            return {}

    def _get_examples_text(self, topic: str) -> str:
        """Retrieves formatted examples based on the topic/subject."""
        # Simple mapping heuristic
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
        for i, ex in enumerate(examples[:3]): # Limit to 3 examples context
            out.append(f"ÖRNEK {i+1}:")
            out.append(f"Soru: {ex['question']}")
            out.append(f"Seçenekler: {json.dumps(ex.get('options', []))}")
            out.append("---")
            
        return "\n".join(out)
    
    def _generate_with_fallback(self, system_instruction: str, prompt: str, model_type: str = "flash", json_output: bool = False, **kwargs) -> str:
        """
        Generate content with automatic model fallback and per-model retries.
        args:
            json_output: If True, will retry generation if the output is not valid JSON.
        """
        model_priority = kwargs.pop("model_priority_override", None)
        if not model_priority:
            model_priority = MODEL_PRIORITY_FLASH if model_type == "flash" else MODEL_PRIORITY_PRO
        
        last_error = None
        for model_name in model_priority:
            # Per-model retry loop (e.g., 3 attempts)
            for attempt in range(MAX_RETRIES_PER_MODEL + 1):
                try:
                    # Rate Limit Wait
                    self._wait_for_rate_limit()

                    if attempt > 0:
                        wait_time = 2 ** attempt # 2s, 4s backoff
                        logging.info(f"   🔄 Retrying {model_name} (Attempt {attempt+1}/{MAX_RETRIES_PER_MODEL+1}) in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logging.info(f"   🤖 Trying model: {model_name}")
                        
                    # NEW SDK Syntax: client.models.generate_content
                    # We check if a response_schema is passed in kwargs (simplification refactor)
                    
                    config_args = {
                        "system_instruction": system_instruction,
                        "temperature": 0.7
                    }
                    
                    # If this call requests structured JSON output
                    if "response_schema" in kwargs:
                        config_args["response_mime_type"] = "application/json"
                        config_args["response_schema"] = kwargs["response_schema"]
                    elif json_output:
                        # Even if no strict schema, hint JSON mime type
                        config_args["response_mime_type"] = "application/json"
                    
                    logging.info(f"   📡 Calling Gemini API ({model_name})...")
                    start_time = time.time()
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(**config_args)
                    )
                    duration = time.time() - start_time
                    logging.info(f"   🙌 Gemini API responded in {duration:.2f}s")
                    
                    if not response.text:
                        raise Exception("Empty response from model")

                    # JSON Validation Retry Logic
                    if json_output:
                        try:
                            self._safe_json_load(response.text)
                        except ValueError as ve:
                            # This catches JSON decode errors.
                            # We raise exception to trigger the retry loop!
                            logging.warning(f"   ⚠️ Malformed JSON detected: {ve}. Retrying...")
                            raise Exception(f"Malformed JSON received: {ve}")
                        
                    logging.info(f"   ✅ Success with {model_name}")
                    return response.text
                    
                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    logging.error(f"   ❌ Error with {model_name} (Attempt {attempt+1}): {e}")
                    
                    # Check if retryable error (Quota or transient 500/Internal OR Malformed JSON OR Overloaded)
                    is_retryable = any(x in error_str for x in ["429", "ResourceExhausted", "Quota", "500", "503", "Internal", "internal_error", "Malformed JSON", "UNAVAILABLE", "Overloaded"])
                    is_not_found = any(x in error_str for x in ["404", "not found"])
                    
                    if is_retryable and attempt < MAX_RETRIES_PER_MODEL:
                        continue # Try same model again
                    
                    if is_not_found:
                        logging.warning(f"   ⚠️ Model {model_name} not available, trying next model in priority list...")
                        break # Move to next model in priority list
                    
                    # If it's a non-retryable error or we exhausted attempts for this model, 
                    # we'll break the attempt loop and move to the next model in the priority list.
                    break 
        
        # All models and retries exhausted
        print(f"   ❌ All models exhausted. Last error: {last_error}")
        raise Exception(f"All models in priority list failed. Last: {last_error}")

    def _safe_json_load(self, text: str) -> dict:
        """Robust JSON filtering and loading."""
        if not text:
            raise ValueError("Empty response text")
            
        # 1. Strip Markdown Code Fences
        clean_text = text.strip()
        if clean_text.startswith("```"):
            # Remove first line
            first_newline = clean_text.find('\n')
            if first_newline != -1:
                clean_text = clean_text[first_newline+1:]
            # Remove last line if it ends with ```
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3].strip()
        
        # 2. Try Direct Parse
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            pass
            
        # 3. Regex Extraction (Best for "Here is the JSON: { ... }")
        # Finds the widest possible brace pair
        try:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                candidate = match.group(1)
                return json.loads(candidate)
        except Exception:
            pass

        # 4. Fallback: Naive Substring
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
                
        raise ValueError(f"No valid JSON found in response. First 50 chars: {text[:50]}")

    def upload_file(self, path: str):
        """
        Uploads a file to Google GenAI for multimodal processing.
        Returns the file object.
        Handles non-ASCII characters by using a temporary safe filename.
        """
        print(f"   📤 Uploading file: {path}...")
        import shutil
        import uuid
        
        # Create a safe ASCII filename
        ext = os.path.splitext(path)[1]
        safe_name = f"{uuid.uuid4()}{ext}"
        temp_path = os.path.join("/tmp", safe_name)
        
        try:
            # Copy to temp
            shutil.copy(path, temp_path)
            
            # New SDK file upload using the safe path
            # We can pass the original name as display_name if needed, but not critical for generation
            file_ref = self.client.files.upload(file=temp_path)
            print(f"   ✅ File uploaded: {file_ref.name} (URI: {file_ref.uri})")
            return file_ref
        except Exception as e:
            print(f"   ❌ File upload failed: {e}")
            raise e
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def draft_question(self, concept: str, evidence: str, topic: str, media_file=None) -> dict:
        """Stage 1: Draft (Enhanced with Few-Shot Examples)"""
        
        # 1. Get Examples
        examples_text = self._get_examples_text(topic)
        
        # 2. Construct Dynamic System Prompt
        dynamic_system_prompt = construct_system_prompt_draft(examples_text)
        
        # 3. Use structured output
        # If media_file is provided, evidence might be empty or a summary
        if media_file:
            prompt_text = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK: Attached PDF Document."
            contents = [prompt_text, media_file]
        else:
            prompt_text = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK:\n{evidence[:15000]}"
            contents = prompt_text
        
        # We pass the Schema dict
        response_text = self._generate_with_fallback(
            dynamic_system_prompt, 
            contents, 
            model_type="flash",
            json_output=True,
            response_schema=SCHEMA_QUESTION_DRAFT
        )
        return self._safe_json_load(response_text)

    def critique_question(self, draft: dict, evidence: str) -> dict:
        """Stage 2: Critique & Suggest Siblings (Uses PRO for better reasoning)"""
        # For critique, we might not pass the full PDF to save tokens/time if draft is good.
        # But ideally we should. For now, let's assume critique works on the textual evidence or self-consistency.
        # If evidence was a PDF, we don't have text here unless we extracted it.
        # TODO: Pass PDF to critique as well if needed. For now, we'll rely on the draft content.
        
        prompt = f"SORU: {json.dumps(draft, ensure_ascii=False)}\nKAYNAK (Özet/Metin):\n{evidence[:5000]}"
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_CRITIQUE, prompt, model_type="pro", json_output=True)
        return self._safe_json_load(response_text)
        
    def reconcile_updates(self, main_evidence: str, update_evidence: str) -> list:
        """Stage 2b: Reconcile Update Evidence"""
        if not update_evidence:
            return []
            
        prompt = f"""
        MAIN EVIDENCE:
        {main_evidence[:2000]}
        
        UPDATE EVIDENCE:
        {update_evidence[:5000]}
        """
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_RECONCILE, prompt, model_type="flash", json_output=True)
        result = self._safe_json_load(response_text)
        return result.get("updates_applied", [])

    def check_topic_alignment(self, question_text: str, correct_option: str, target_topic: str) -> dict:
        """
        Gating Step: Verify if the generated question actually belongs to the target topic.
        Uses a fast model (Flash) to catch 'drift' (e.g. Cardio question in Neuro).
        """
        gate_prompt = f"""
        ANALYZE THIS QUESTION FOR TOPIC ALIGNMENT.
        
        Target Topic: {target_topic}
        
        Question: {question_text}
        Correct Answer: {correct_option}
        
        Task:
        1. Does this question belong to '{target_topic}'? 
        2. Is it clearly drifting into another specialty (e.g. Cardiology, Pulmonology) without a link to {target_topic}?
        
        Output JSON:
        {{
            "topic_match": true/false,
            "predicted_topic": "string",
            "reason": "short explanation"
        }}
        """
        
        try:
            # Use fallback system even for gating
            response_text = self._generate_with_fallback("You are a topic alignment specialist.", gate_prompt, model_type="flash", json_output=True)
            data = self._safe_json_load(response_text)
            return data
        except Exception as e:
            print(f"⚠️ Topic Gate Error: {e}")
            return {"topic_match": False, "predicted_topic": "Error", "reason": str(e)}

    def select_best_topic(self, question_text: str, topic_list: list) -> str:
        """
        Given a question and a list of possible topics, asks the model to pick the best fit.
        Robustly validates the output against the list.
        """
        if not topic_list:
            return "Unknown"
            
        options_text = "\n".join([f"- {t}" for t in topic_list])
        
        selection_prompt = f"""
        TASK: CATEGORIZE THIS MEDICAL QUESTION.
        
        POSSIBLE TOPICS (Select ONE from this exact list):
        {options_text}
        
        QUESTION:
        {question_text}
        
        RULES:
        1. You MUST return ONLY the exact string from the POSSIBLE TOPICS list.
        2. Do NOT create new topic names.
        3. Do NOT add numbers or prefixes if they are not in the list.
        4. If the question covers multiple topics, pick the most specific one from the list.
        5. If you are unsure, pick the first topic in the list.
        
        OUTPUT FORMAT:
        Just the topic string.
        """
        
        try:
            response_text = self._generate_with_fallback("You are a medical topic classifier.", selection_prompt, model_type="flash")
            selected = response_text.strip()
            
            # Clean if model added extra markers
            if selected.startswith("- "): selected = selected[2:]
            if selected.startswith('"') and selected.endswith('"'): selected = selected[1:-1]
            selected = selected.strip()
            
            # Strict Validation
            if selected in topic_list:
                return selected
            
            # Fuzzy recovery
            import difflib
            matches = difflib.get_close_matches(selected, topic_list, n=1, cutoff=0.8)
            if matches:
                 logging.info(f"   🩹 Recovered fuzzy topic match: '{selected}' -> '{matches[0]}'")
                 return matches[0]
                 
            logging.warning(f"   ⚠️ Model selected invalid topic '{selected}'. Fallback to first topic.")
            return topic_list[0] 
            
        except Exception as e:
            print(f"⚠️ Topic Selection Error: {e}")
            return topic_list[0] if topic_list else "Unknown"

    def check_for_duplicates(self, draft_question: dict, existing_questions: list) -> dict:
        """
        Stage 2.5: Semantic Duplicate Check
        Checks if the draft question is too similar to existing questions in the DB.
        """
        if not existing_questions:
            return {"is_duplicate": False, "reason": "No existing questions."}
            
        # Format existing questions for prompt
        # We limit to last 20 to avoid context overflow, though Flash can handle matches
        # We focus on the Question Stem and Correct Answer to define "What is asked"
        existing_text = ""
        # User Request: Check ALL questions (removed limit)
        for q in existing_questions:
            existing_text += f"- [ID: {q['id']}] Q: {q['question']} | A: {q['correct_answer']}\n"
            
        draft_text = f"Q: {draft_question.get('question_text', '')}\nA: Correct ID {draft_question.get('correct_option_id')}"
        
        # We inject the formatted lists into the prompt
        prompt = SYSTEM_PROMPT_DUPLICATE_CHECK.replace("{draft_question}", draft_text).replace("{existing_questions_list}", existing_text)
        
        # Use simple instruction for system, as the detailed rules are in the prompt body
        res = self._generate_with_fallback(
            "You are a Duplicate Detector.", 
            prompt, 
            model_type="flash", 
            json_output=True,
            response_schema=SCHEMA_DUPLICATE_CHECK
        )
        
        return self._safe_json_load(res)



    def extract_concepts(self, text: str, topic: str, count: int = 20, media_file=None) -> list:
        """
        Extracts a list of key concepts/diseases from the source text or PDF for question generation.
        """
        prompt_text = f"""
        TASK: Identify {count} distinct, high-yield clinical concepts or diseases from the attached content below for exam question generation.
        TOPIC: {topic}
        
        RULES:
        1. Return a JSON list of strings.
        2. Focus on specific pathologies (e.g. "Papillary Thyroid Carcinoma", "Addison's Disease").
        3. Avoid generic terms (e.g. "Anatomy", "Introduction").
        4. NO SYNONYMS: Do NOT list the same concept twice (e.g. "Crohn" vs "Crohn Hastalığı" -> Pick ONE).
        5. LANGUAGE: Turkish (Medical Terminology).
        6. Output JSON: {{ "concepts": ["Concept 1", "Concept 2", ...] }}
        
        TEXT:
        {text[:100000] if text else "Attached PDF Document."}
        """
        
        try:
            if media_file:
                contents = [prompt_text, media_file]
            else:
                contents = prompt_text
                
            # Use fallback system for extraction
            response_text = self._generate_with_fallback(
                "You are a medical concept extractor.", 
                contents, 
                model_type="flash",
                json_output=True,
                response_schema=SCHEMA_CONCEPT_LIST
            )
            data = self._safe_json_load(response_text)
            return data.get("concepts", [])
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.error(f"⚠️ Concept Extraction Failed: {e}")
            return []


    def generate_explanation_blocks(self, draft: dict, critique: dict, updates: list, evidence: str, source_material: str, topic: str, media_file=None, use_pro_model: bool = True) -> dict:
        """Stage 3: Block-based Explanation (Always uses PRO for complex structured output)"""
        siblings = critique.get("sibling_suggestions", [])
        
        # Merge draft into final structure request
        request_context = {
            "draft": draft,
            "siblings": siblings,
            "updates": updates,
            "source_material": source_material,
            "topic": topic
        }
        
        prompt_text = f"""
        GİRDİ VERİSİ:
        {json.dumps(request_context, ensure_ascii=False)}
        
        KAYNAK:
        {evidence[:10000] if evidence else "Attached PDF Document."}
        
        Bu verileri kullanarak ŞEMAYA TAM UYGUN JSON çıktısı üret.
        - Options listesi "id" ve "text" içermeli.
        - Explanation nesnesi "blocks" içermeli.
        """
        
        if media_file:
            contents = [prompt_text, media_file]
        else:
            contents = prompt_text
        
        # Always use PRO models for complex structured output
        # Always use PRO models for complex structured output
        response_text = self._generate_with_fallback(
            SYSTEM_PROMPT_BLOCKS, 
            contents, 
            model_type="pro",
            json_output=True,
            response_schema=SCHEMA_FULL_RESPONSE
        )
        return self._safe_json_load(response_text)

    def repair_json(self, broken_json_str: str, error_msg: str) -> dict:
        """Stage 4: Auto-Repair Loop"""
        prompt = f"""
        BROKEN JSON:
        {broken_json_str}
        
        ERROR MESSAGE (PYDANTIC):
        {error_msg}
        
        TASK:
        Fix the JSON to resolve the validation error. 
        Ensure block order is correct (Heading -> Key Clues -> Steps -> Trap -> DDX -> Table).
        Ensure Table dimensions are consistent.
        CHECK OPTIONS: If options are list of strings, convert to objects {{ "id": "A", "text": "..." }}.
        """
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_REPAIR, prompt, model_type="flash", json_output=True)
        return self._safe_json_load(response_text)

    def generate_flashcards(self, highlighted_text: str, topic: str) -> list:
        """
        Generates Q&A flashcards from user highlights.
        """
        prompt = f"""
        TASK: Create high-yield Flashcards (Q&A) from the following highlighted text.
        TOPIC: {topic}
        
        RULES:
        1. Output a JSON list of objects calling 'flashcards'.
        2. Format: {{"flashcards": [{{"question_text": "...", "answer_text": "..."}}]}}
        3. Questions should be direct and stimulating.
        4. Answers should be concise but complete.
        5. Focus ONLY on the information provided in the highlights.
        6. If the highlights are insufficient or not suitable for a reliable flashcard, return an empty list.
        
        HIGHLIGHTS:
        {highlighted_text[:20000]}
        """
        
        try:
            response_text = self._generate_with_fallback(
                "You are a flashcard generator.",
                prompt,
                model_type="flash",
                json_output=True,
                response_schema=SCHEMA_FLASHCARDS,
                model_priority_override=["gemini-2.0-flash"]
            )
            data = self._safe_json_load(response_text)
            return data.get("flashcards", [])
        except Exception as e:
            print(f"⚠️ Flashcard Generation Failed: {e}")
            return []

    def generate_flashcards_grouped(self, groups: list, max_cards: int = 30) -> list:
        """
        Generates flashcards from grouped highlights with metadata.
        Each output card includes a group_id to map back to its source.
        """
        prompt = f"""
        TASK: Create high-yield Flashcards (Q&A) from grouped highlights.
        You will receive a JSON list of groups. Each group contains:
        - group_id (integer, use this in output)
        - source_material
        - category
        - topic
        - tags
        - highlights (list of words/phrases)

        RULES:
        1. Output JSON format: {{"flashcards": [{{"group_id": 1, "question_text": "...", "answer_text": "..."}}]}}
        2. Use ONLY the highlights for that group. Do not add outside knowledge.
        3. Keep answers concise but complete.
        4. Avoid duplicates. Return at most {max_cards} flashcards total.
        5. If a group lacks enough context, SKIP that group (no card).
        6. It is valid to return an empty flashcards list if nothing is suitable.

        GROUPS:
        {json.dumps(groups, ensure_ascii=False)[:20000]}
        """

        try:
            response_text = self._generate_with_fallback(
                "You are a flashcard generator.",
                prompt,
                model_type="flash",
                json_output=True,
                response_schema=SCHEMA_FLASHCARDS_GROUPED,
                model_priority_override=["gemini-2.0-flash"]
            )
            data = self._safe_json_load(response_text)
            return data.get("flashcards", [])
        except Exception as e:
            print(f"⚠️ Grouped Flashcard Generation Failed: {e}")
            return []
