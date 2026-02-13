"""
OpenAI API Client for Block-Based Question Generation (PROD-SAFE)
Mirror of GeminiClient but using OpenAI's API.
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

import openai
from openai import OpenAI

# ============================================================================
# PROMPTS (Reused from gemini_client.py but adapted if needed)
# ============================================================================

def construct_system_prompt_draft(examples_text=""):
    base_prompt = """Türkçe tıp sınavı soru yazarısın. 
Görevin: Verilen metinden TUS/USMLE standardında klinik vinyet sorusu taslağı çıkarmak.

KURALLAR:
1. Soru metni, referans örneklere uygun stilde ve uzunlukta olmalı.
2. 5 seçenek (A-E), sadece bir doğru.
3. Çeldiriciler mantıklı ve ayırıcı tanıda olmalı.

CRITICAL RULE: TOPIC SCOPING
- You MUST write a question strictly within the requested TOPIC.
- If the provided evidence is for a different topic or is irrelevant, unexpected, or insufficient:
    Output JSON with: `{"insufficient_evidence": true, "reason": "Evidence mismatch or too sparse"}`
    DO NOT HALLUCINATE OR INVENT CONTENT.

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
Görevin: Ana kaynak metni ile varsa güncelleme metnini karşılaştırmak.

ÇIKTI (JSON):
{
    "updates_found": boolean,
    "updates_applied": [
        {
            "source_file": "Dosya adı",
            "change_summary": "...",
            "priority": "update_overrides_main"
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
5. `mini_ddx` -> Yanlış şıkların her biri için analiz.
6. `table` -> Doğru cevap vs Kardeş Antiteler

TABLO KURALLARI:
- Başlık satırı (headers) HARİÇ, her satırda (header sayısı - 1) kadar hücre olmalı.

ÇIKTI ŞEMASI (JSON):
{
  "source_material": "Küçük Stajlar",
  "topic": "...",
  "question_text": "...",
  "options": [{"id": "A", "text": "..."}, ...],
  "correct_option_id": "A",
  "tags": ["concept:..."],
  "explanation": {
      "main_mechanism": "...",
      "clinical_significance": "...",
      "sibling_entities": ["...", "..."],
      "updates_applied": [],
      "update_checked": true,
      "blocks": [
        { "type": "heading", "level": 1, "text": "Detaylı Açıklama & Mekanizma" },
        { "type": "callout", "style": "key_clues", "title": "Klinik İpuçları", "items": ["..."] },
        { "type": "numbered_steps", "title": "Mekanizma Zinciri", "steps": ["...", "..."] },
        { "type": "callout", "style": "exam_trap", "title": "Sınav Tuzağı", "items": ["..."] },
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
1. `mini_ddx` items must match exactly the number of WRONG options.
2. `table` rows must have correct cell count matching headers (headers - 1).
3. `option_id` must be A, B, C, D, or E.
4. `blocks` list must have exactly 6 items in specific order.
5. Callouts must include `title`.

Output ONLY valid JSON.
"""

# ============================================================================
# CLIENT CLASS
# ============================================================================

class OpenAIClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found.")
        
        self.client = OpenAI(api_key=self.api_key)
        
        # Load Reference Examples
        self.reference_examples = self._load_reference_examples()
        
        # Models
        self.default_model = "gpt-5.2" 
        self.reasoning_model = "gpt-5.2" 
        
    def _load_reference_examples(self) -> dict:
        try:
            with open("reference_examples.json", "r") as f:
                return json.load(f)
        except:
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
            out.append(f"Soru: {ex.get('question', '')}")
            out.append(f"Seçenekler: {json.dumps(ex.get('options', []))}")
            out.append("---")
            
        return "\n".join(out)

    def _safe_json_load(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"): lines = lines[1:]
            if lines[-1].startswith("```"): lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Simple fallback
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except:
                    pass
            print(f"❌ JSON Parse Error: {text[:100]}...")
            return {}

    def _call_gpt(self, system_prompt: str, user_prompt: str, model: str = None, json_mode: bool = True) -> dict:
        model = model or self.default_model
        
        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
                
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            return self._safe_json_load(content)
        except Exception as e:
            print(f"⚠️ OpenAI Error: {e}")
            return {}

    def draft_question(self, concept: str, evidence: str, topic: str) -> dict:
        # 1. Get Examples
        examples_text = self._get_examples_text(topic)
        system_prompt = construct_system_prompt_draft(examples_text)
        user_prompt = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK:\n{evidence[:8000]}" # GPT-4o context is large
        return self._call_gpt(system_prompt, user_prompt)

    def critique_question(self, draft: dict, evidence: str) -> dict:
        user_prompt = f"SORU: {json.dumps(draft, ensure_ascii=False)}\nKAYNAK:\n{evidence[:4000]}"
        return self._call_gpt(SYSTEM_PROMPT_CRITIQUE, user_prompt)

    def reconcile_updates(self, main_evidence: str, update_evidence: str) -> list:
        if not update_evidence: return []
        user_prompt = f"MAIN:\n{main_evidence[:4000]}\nUPDATES:\n{update_evidence[:4000]}"
        resp = self._call_gpt(SYSTEM_PROMPT_RECONCILE, user_prompt)
        return resp.get("updates_applied", [])

    def check_topic_alignment(self, question_text: str, correct_option: str, target_topic: str) -> dict:
        gate_prompt = f"""
        ANALYZE TOPIC ALIGNMENT.
        Target: {target_topic}
        Question: {question_text}
        Answer: {correct_option}
        
        Output JSON: {{ "topic_match": true/false, "predicted_topic": "...", "reason": "..." }}
        """
        return self._call_gpt("You are a strict topic gatekeeper.", gate_prompt, model="gpt-4o-mini") # Cheap model

    def extract_concepts(self, text: str, topic: str, count: int = 20) -> list:
        prompt = f"""
        Identifying {count} high-yield clinical concepts from text for '{topic}'.
        Return JSON: {{ "concepts": ["name1", "name2"] }}
        TEXT: {text[:50000]}
        """
        resp = self._call_gpt("You are a medical curriculum expert.", prompt)
        return resp.get("concepts", [])

    def generate_explanation_blocks(self, draft: dict, critique: dict, updates: list, evidence: str, source_material: str, topic: str, use_pro_model: bool = False) -> dict:
        request_context = {
            "draft": draft,
            "siblings": critique.get("sibling_suggestions", []),
            "updates": updates,
            "source_material": source_material,
            "topic": topic
        }
        prompt = f"GİRDİ: {json.dumps(request_context, ensure_ascii=False)}\nKAYNAK: {evidence[:10000]}\nÜret:"
        # Use gpt-4o (or o1 if strictly requested for 'pro')
        model = self.reasoning_model
        return self._call_gpt(SYSTEM_PROMPT_BLOCKS, prompt, model=model)

    def repair_json(self, broken_json_str: str, error_msg: str) -> dict:
        prompt = f"BROKEN JSON: {broken_json_str}\nERROR: {error_msg}\nFIX IT."
        return self._call_gpt(SYSTEM_PROMPT_REPAIR, prompt)
