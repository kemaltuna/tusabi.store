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

def construct_system_prompt_draft(examples_text="", strict: bool = True):
    evidence_rule = """
CRITICAL RULE: TOPIC SCOPING
- The question must stay within the requested TOPIC and be anchored to the evidence.
- If evidence is empty or clearly unrelated: output
  {"insufficient_evidence": true, "reason": "Evidence mismatch or too sparse"} and STOP.
- If evidence is short but related, still draft a simpler question.
- You MAY use high-yield medical reasoning to craft distractors, tricks, and sibling comparisons
  as long as they do not contradict the evidence.
""".strip()
    if not strict:
        evidence_rule = """
CRITICAL RULE: TOPIC SCOPING (RELAXED)
- Only return insufficient_evidence if the evidence is empty or clearly unrelated.
- If evidence is partial but related, still draft a question anchored to evidence.
- You MAY use standard clinical reasoning for sibling comparisons and traps,
  but keep the question narrow if evidence is limited.
""".strip()

    base_prompt = """Türkçe tıp sınavı soru yazarısın. 
Görevin: Verilen metinden TUS/USMLE standardında klinik vinyet sorusu taslağı çıkarmak.

KURALLAR:
1. Soru metni, referans örneklere uygun stilde ve uzunlukta olmalı.
2. 5 seçenek (A-E), sadece bir doğru.
3. Çeldiriciler mantıklı ve ayırıcı tanıda olmalı.
4. Roma rakamı kombinasyonu kullanılırsa:
   - I–IV maddeleri kökte ALT ALTA yaz (her madde ayrı satır, "I.", "II.", "III.", "IV.").
   - Şıklar kombinasyon formatında ve her biri ayrı seçenek nesnesi olmalı.
5. Kaynakta geçmeyen bilgi "yanlış" sayılmaz; doğruluğu genel tıbbi bilgiyle değerlendir.
6. Dosyalar başlık öncesi/sonrası ±1 sayfa buffer içerebilir; buffer içeriğini konseptle uyumlu değilse kullanma.
7. OCR_TEXT varsa tanıma hataları olabilir; çelişki varsa normal metni öncelikle kullan.

{evidence_rule}

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
    return (
        base_prompt
        .replace("{evidence_rule}", evidence_rule)
        .replace("{examples}", examples_text)
    )

SYSTEM_PROMPT_CRITIQUE = """Sen kıdemli bir tıp editörüsün.
Görevin: Taslak soruyu incelemek, hataları bulmak ve "Kardeş Antite" (Sibling Entity) önerileri sunmak.

ANALİZ ET:
1. Soru kurgusu hatasız mı?
2. Doğru cevap kesinlikle tek mi?
3. Çeldiriciler yeterince güçlü mü ve yanlış şıklardan biri de doğruya gidiyor mu?
4. Soru kökü bir şıkkı isim benzerliği/çağrışımla direkt ele veriyor mu?
5. SIBLING ÖNERİSİ: Bu hastalıkla en sık karışan 2-4 hastalık nedir? (Tablo için lazım)

DÜZELTME YETKİSİ:
- Hata varsa, aynı bağlamı koruyarak soru kökünü/şıkları düzelt.
- Birden fazla doğruya giden şık varsa, doğru olmayanı kaynağa UYUMLU olacak şekilde değiştir.
- Gerekirse correct_option_id güncelle.
- Düzeltme mümkün değilse action="abort" döndür.

ZORUNLU KONTROL (Cevap Sızması / İsim Benzerliği):
- Soru kökünde doğru şıkla aynı/çok benzer isim (eşanlam/eponim/alternatif ad) varsa bu bir HATA.
- Soru kökünde verilen bulgu/ifade tek bir şık ismine doğrudan çağrışım yapıyorsa bu bir HATA.
- Bu durumda action="revise" seç ve şu şekilde düzelt:
  - İsim soruluyorsa: ismi kökten çıkar; hastalık/ilaç/durumun bir ÖZELLİĞİNİ soracak şekilde kökü değiştir.
  - İsim sızması şıklardaysa: doğru şıkkı kaynakta geçen alternatif adıyla ver veya şıkları yeniden düzenle.
  - Dış bilgi ekleme; sadece kaynak/soru/şık bilgisini kullan.

ZORUNLU KONTROL (Tek Doğru):
- Her şık için \"doğru/yanlış/şüpheli\" değerlendirmesi yap.
- Olası doğru şıkların ID listesini ver (possible_correct_option_ids).
- Eğer mümkün doğru şık sayısı 1'den fazla ise mutlaka action=\"revise\" veya action=\"abort\" seç.
- Kaynakta geçmeyen bilgi \"yanlış\" sayılmaz; bu durumda \"şüpheli\" de. Doğruluğu genel tıbbi bilgiyle değerlendir, sonra soruyu kaynağa UYUMLU olacak şekilde düzelt veya abort et.

ROMA RAKAMI KURALI (YETERSİZ ÇELDİRİCİ):
- Eğer 4 sağlam yanlış/uygun çeldirici üretilemiyorsa veya birden fazla şık doğru görünüyorsa,
  soruyu "Roma rakamı kombinasyonu" tipine çevir.
- Format: Kök altında I–IV maddeler; soru "Yukarıdakilerden hangileri doğrudur/yanlıştır/görülür/görülmez?"
- Şıklar kombinasyon formatında olmalı (tek doğru olacak şekilde). Örnek:
  A) I ve II  B) I ve III  C) II ve III  D) I, II ve III  E) I, II, III ve IV
- Dış bilgi kullanarak doğruluk değerlendirebilirsin; fakat soru/şık/çıktı mutlaka kaynağa UYUMLU olmalı.

KURALLAR (REVIZE):
- 5 seçenek (A-E), tek doğru.
- Soru tarzını koru.
- Kanıt yoksa sadece bariz hataları düzelt.
- concept_tag ve brief_explanation varsa koru.
- revised_draft taslak şemasıyla aynı formatta olmalı (question_text, options, correct_option_id, concept_tag, brief_explanation).

ÇIKTI (JSON):
{
    "critique_passed": boolean,
    "feedback": "...",
    "sibling_suggestions": ["Hastalık A", "Hastalık B", ...],
    "improved_distractors": ["...", ...] (optional),
    "option_assessment": {
        "A": "doğru/yanlış/şüpheli",
        "B": "doğru/yanlış/şüpheli",
        "C": "doğru/yanlış/şüpheli",
        "D": "doğru/yanlış/şüpheli",
        "E": "doğru/yanlış/şüpheli"
    },
    "possible_correct_option_ids": ["A", "..."],
    "action": "accept|revise|abort",
    "revised_draft": { ... }  # sadece action == "revise" ise
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

EK KURALLAR:
- Doğruluk kontrolünde genel tıbbi bilgi kullanabilirsin; ancak soru/şık/çıktı kaynağa UYUMLU olmalı.
- Kaynakta geçmeyen bilgi "yanlış" değildir; belirsizse soruyu kaynağa UYUMLU olacak şekilde düzelt.
- Eksikse kısa ve nötr ifade kullan (ör. "Soruda belirtilmemiştir"); "Bilinmiyor" yazma.
- Taslak soru ile kaynak çelişirse, soru kökü/şıklar/doğru şık bilgisini KAYNAĞA göre düzelt.
- Çelişki yoksa taslak soru ve şıkları AYNEN koru (parafraz yapma).
- Tek doğruyu sağlamak için gerekiyorsa kaynakta geçen ayırt edici ipucunu soru köküne ekle.
- Klinik ipuçları, sınav tuzakları ve çeldiriciler kaynağa UYUMLU olmalı; doğruluk kontrolünde genel tıbbi bilgi kullanabilirsin.
- Kardeş antitelerle karşılaştırma yap, ortaklık ve ayrımları netleştir.
- Kanıt yetersizse yeni bilgi ekleme; sadece verilenleri özetle.
- ROMA RAKAMI KURALI (mini_ddx):
  - Soru kökünde I–IV maddeleri varsa `mini_ddx` analizini şıklara değil I/II/III/IV maddelerine göre yaz.
  - `option_id` yine yanlış şıklardan biri olmalı, ama `label/why_wrong` I–IV maddelerine odaklanmalı.
- `explanation.main_mechanism` ve `explanation.clinical_significance` 300 karakteri geçmemeli.
- `callout.items` MUTLAKA obje olmalı: [{"text": "..."}] (string listesi YASAK).

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
        { "type": "callout", "style": "key_clues", "title": "Klinik İpuçları", "items": [{"text": "..."}] },
        { "type": "numbered_steps", "title": "Mekanizma Zinciri", "steps": ["...", "..."] },
        { "type": "callout", "style": "exam_trap", "title": "Sınav Tuzağı", "items": [{"text": "..."}] },
        { "type": "mini_ddx", "title": "Çeldirici Analizi", "items": [
            {"option_id": "B", "label": "...", "analysis": "..."}
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
6. Do NOT use placeholder content like "Bilinmiyor", "Unknown", "N/A", or empty strings.

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
        
        self.client = OpenAI(api_key=self.api_key, timeout=120.0)
        
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

    def draft_question(self, concept: str, evidence: str, topic: str, strict: bool = True, **kwargs) -> dict:
        # 1. Get Examples
        examples_text = self._get_examples_text(topic)
        system_prompt = construct_system_prompt_draft(examples_text, strict=strict)
        user_prompt = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK:\n{evidence}"
        return self._call_gpt(system_prompt, user_prompt)

    def critique_question(self, draft: dict, evidence: str, **kwargs) -> dict:
        user_prompt = f"SORU: {json.dumps(draft, ensure_ascii=False)}\nKAYNAK:\n{evidence}"
        return self._call_gpt(SYSTEM_PROMPT_CRITIQUE, user_prompt)

    def reconcile_updates(self, main_evidence: str, update_evidence: str) -> list:
        if not update_evidence: return []
        user_prompt = f"MAIN:\n{main_evidence}\nUPDATES:\n{update_evidence}"
        resp = self._call_gpt(SYSTEM_PROMPT_RECONCILE, user_prompt)
        return resp.get("updates_applied", [])

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
        return self._call_gpt("You are a strict topic gatekeeper.", gate_prompt, model="gpt-4o-mini")

    def extract_concepts(self, text: str, topic: str, count: int = 20, avoid_concepts: Optional[list] = None) -> list:
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
        prompt = f"""
        Identifying {count} high-yield clinical concepts from text for '{topic}'.
        Return JSON: {{ "concepts": [{{"concept": "...", "reason": "...", "evidence": "..."}}] }}
        - "reason": kısa gerekçe (<= 20 kelime), neden high-yield.
        - "evidence": metinden kısa alıntı (<= 25 kelime) veya tablo hücre özeti.
        Avoid any concepts from the exclusion list below.
        {avoid_block}
        TEXT: {text}
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
        prompt = (
            f"GİRDİ: {json.dumps(request_context, ensure_ascii=False)}\n"
            f"KAYNAK: {evidence}\n"
            "Doğruluk kontrolünde genel tıbbi bilgi kullanabilirsin; ancak soru/şık/çıktı kaynağa UYUMLU olmalı.\n"
            "Eğer taslak soru kaynakla çelişiyorsa, soru kökü/şıkları/doğru şık bilgisini KAYNAĞA göre düzelt.\n"
            "Çelişki yoksa taslak soru ve şıkları AYNEN koru (parafraz yapma).\n"
            "Üret:"
        )
        # Use gpt-4o (or o1 if strictly requested for 'pro')
        model = self.reasoning_model
        return self._call_gpt(SYSTEM_PROMPT_BLOCKS, prompt, model=model)

    def repair_json(self, broken_json_str: str, error_msg: str) -> dict:
        prompt = f"BROKEN JSON: {broken_json_str}\nERROR: {error_msg}\nFIX IT."
        return self._call_gpt(SYSTEM_PROMPT_REPAIR, prompt)
