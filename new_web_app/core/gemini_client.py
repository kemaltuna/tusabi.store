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
import random
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
import google.auth

DEFAULT_HTTP_TIMEOUT_MS = int(os.getenv("GENAI_HTTP_TIMEOUT_MS", "240000"))  # 4 minutes

SCHEMA_CONCEPT_LIST = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"}
                },
                "required": ["concept", "reason", "evidence"]
            }
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
                                        "analysis": {"type": "string"},
                                        
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


# ============================================================================
# MODEL CONFIGURATION & FALLBACK
# ============================================================================

# Model Priority (Best → Fallback) - Premium tasks (Draft, Explanation)
# Verified model name in Google AI Studio docs.
MODEL_PRIORITY_FLASH = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# User requested NO PRO models due to cost.
# We redirect PRO requests to the strongest available FLASH model.
MODEL_PRIORITY_PRO = MODEL_PRIORITY_FLASH.copy()

# Cost-optimized model list for low-complexity tasks (Topic Alignment, JSON Repair)
# Use gemini-2.5-flash-lite for simple classification/formatting tasks
MODEL_PRIORITY_CHEAP = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
]

MAX_RETRIES_PER_MODEL = 5

# ============================================================================
# PROMPTS
# ============================================================================

# ============================================================================
# DISCIPLINE FOCUS PROFILES
# ============================================================================

DISCIPLINE_FOCUS_PROFILES = {
    "Farmakoloji": {
        "focus_instruction": """
    ODAK ALANI (FARMAKOLOJİ):
    - İlaç isimleri, ait oldukları gruplar ve prototip ilaçlar.
    - Etki mekanizmaları (hangi reseptör/enzim, agonist/antagonist/inhibitör).
    - Farmakokinetik özellikler (metabolizma, eliminasyon, yarı ömür, biyoyararlanım).
    - Endikasyonlar (klinik kullanım alanları) ve Kontrendikasyonlar.
    - YAN ETKİLER ve TOKSİSİTE (spesifik antidotlar).
    - İlaç etkileşimleri (sitochrom P450 etkileşimleri vb.).
    - ÖNEMLİ: "En uzun etkili", "En kısa etkili", "En toksik", "İlk tercih" gibi ayırt edici özelliklere odaklan. Kaynaktaki ilaç tablolarını karşılaştırmalı soru üretmek için kullan.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Cevaptaki İlaç", "Çeldirici İlaç/Grup"]
    },
    "Patoloji": {
        "focus_instruction": """
    ODAK ALANI (PATOLOJİ):
    - Hastalık/Tümör isimleri ve sınıflandırması.
    - Genetik mutasyonlar, translokasyonlar ve moleküler patoloji.
    - Patognomonik MİKROSKOPİK bulgular (özel cisimcikler, hücre tipleri).
    - İmmünohistokimyasal belirteçler (CD30, CK7, TTF-1 vb.).
    - Makroskopik görünüm özelliklerini.
    - Tümör evreleme ve prognoz faktörlerini.
    - AYIRICI TANI: Benign vs Malign ayrımı, benzer histolojik görünüme sahip tümörlerin ayrımı.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Patoloji", "Ayırıcı Tanıdaki Patoloji"]
    },
    "Anatomi": {
        "focus_instruction": """
    ODAK ALANI (ANATOMİ):
    - Yapıların komşulukları (önünde/arkasında/medialinde ne var).
    - Geçiş güzergahları (hangi foramen/kanal/fissürden ne geçer).
    - Sinirlerin innerve ettiği kaslar ve duyu alanları.
    - Damarların sulama alanları ve varyasyonları.
    - KLİNİK KORELASYON: "Bu sinir kesilirse ne olur?", "Bu damar tıkanırsa hangi alan etkilenir?", "Hangi hareketi yapamaz?".
    - GÖRSELLEŞTİRME: Metindeki anatomik tarifleri zihinsel olarak görselleştir ve uzaysal ilişkileri sor.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Yapı", "Karışan Yapı"]
    },
    "Biyokimya": {
        "focus_instruction": """
    ODAK ALANI (BİYOKİMYA):
    - Enzim eksiklikleri ve metabolik bloklar.
    - Metabolik yolakların hız kısıtlayıcı basamakları ve regülasyonu.
    - Depo hastalıkları (biriken madde, eksik enzim).
    - Vitaminler, kofaktörler ve mineral eksiklikleri.
    - KLİNİK YANSIMA: Enzim defektinin laboratuvar ve klinik bulguları (örn. hipoglisemi, ketozis, asidoz, idrar kokusu).
        """,
        "explanation_table_headers": ["Özellik", "Doğru Enzim/Hastalık", "Diğer Enzim/Hastalık"]
    },
    "Mikrobiyoloji": {
        "focus_instruction": """
    ODAK ALANI (MİKROBİYOLOJİ):
    - Mikroorganizma temel özellikleri (Gram boyama, şekil, kapsül, spor).
    - Kültür özellikleri ve ayırt edici biyokimyasal testler (oksidaz, katalaz vb.).
    - Virülans faktörleri (toksinler, adezinler, enzimler) ve etki mekanizmaları.
    - Bulaş yolları ve vektörler.
    - TEDAVİ: Spesifik antibiyotik tercihleri veya doğal dirençler.
    - İmmünoprofilaksi (aşılar).
        """,
        "explanation_table_headers": ["Özellik", "Doğru Mikroorganizma", "Diğer Mikroorganizma"]
    },
    "Dahiliye": {
        "focus_instruction": """
    ODAK ALANI (DAHİLİYE):
    - Tanı kriterleri ve algoritmaları.
    - En sık görülen nedenler (epidemiyoloji).
    - İlk istenmesi gereken test vs Kesin tanı testi (Gold standart).
    - Tedavi algoritmaları (ilk tercih ilaç, ikinci basamak tedavi).
    - Hastalık komplikasyonları.
    - VAKA KURGUSU: Semptomlar ve laboratuvar bulgularını birleştirerek tanıya yönlendir.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Tanı/Hastalık", "Ayırıcı Tanı"]
    },
    "Pediatri": {
        "focus_instruction": """
    ODAK ALANI (PEDİATRİ):
    - Yaşa özgü normal değerler ve gelişim basamakları.
    - Aşı takvimi ve bağışıklama.
    - Doğumsal sendromlar, genetik geçişler ve dismorfik bulgular.
    - Yenidoğan taramaları ve acilleri.
    - Çocukluk çağı döküntülü hastalıkları.
    - Çocuklarda acil yaklaşımlar ve resüsitasyon (PALS).
        """,
        "explanation_table_headers": ["Özellik", "Doğru Tanı", "Ayırıcı Tanı"]
    },
    "Genel_Cerrahi": {
        "focus_instruction": """
    ODAK ALANI (GENEL CERRAHİ):
    - Cerrahi endikasyonlar (kim ameliyat edilmeli, kim medikal izlenmeli?).
    - Preoperatif hazırlık ve risk değerlendirmesi.
    - Postoperatif komplikasyonlar ve yönetimi.
    - Travma skorlamaları ve acil travma yönetimi.
    - TNM evrelemesi ve evreye göre cerrahi yaklaşım.
    - Sıvı-elektrolit ve asit-baz dengesi yönetimi.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Yaklaşım/Tanı", "Diğer Yaklaşım/Tanı"]
    },
    "Kadin_Dogum": {
        "focus_instruction": """
    ODAK ALANI (KADIN DOĞUM):
    - Gestasyonel haftaya göre yönetim ve normal değerler.
    - Hormon seviyeleri, siklik değişimler ve etkileri.
    - Gebelik tarama testleri ve prenatal tanı.
    - Jinekolojik kanserlerde FIGO evrelemesi ve tedavi.
    - Kontrasepsiyon yöntemleri (endikasyon/kontrendikasyon).
    - Doğum eylemi evreleri ve yönetimi.
        """,
    },
    "Fizyoloji": {
        "focus_instruction": """
    ODAK ALANI (FİZYOLOJİ):
    - Homeostaz mekanizmaları ve feedback (negatif/pozitif) döngüleri.
    - Membran potansiyelleri (aksiyon potansiyeli fazları, iyon kanalları).
    - Hormonal regülasyon (salınım uyaranları, hedef organ etkileri).
    - Kardiyovasküler dinamikler (basınç-hacim eğrileri, debi hesapları).
    - Solunum fizyolojisi (V/Q dengesi, gaz transportu).
    - Böbrek fizyolojisi (klirens, tübüler transport).
    - GRAFİK YORUMLAMA: "Bu grafikte X noktasındaki değişim nedir?" kurgusu.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Mekanizma", "Karışan Mekanizma"]
    },
    "Kucuk_Stajlar": {
        "focus_instruction": """
    ODAK ALANI (KÜÇÜK STAJLAR - Dermatoloji, KBB, Göz, Nöroloji, Psikiyatri, Üroloji, FTR):
    - DERMATOLOJİ: Lezyon tanımları (makül, papül, bül), tanısal işaretler (Nikolsky vb.).
    - NÖROLOJİ: Lokalizasyon (korteks vs beyinsapı), sendrom bulguları.
    - KBB/GÖZ: Muayene bulguları ve acil yaklaşımlar.
    - PSİKİYATRİ: Tanı kriterleri (süre, semptom sayısı) ve ilaç yan etkileri.
    - KLİNİK İPUCU: "En sık görülen", "Tipik triadı nedir?", "Patognomonik bulgusu".
    - TEDAVİ: İlk basamak vs Kesin tedavi ayrımı.
        """,
        "explanation_table_headers": ["Özellik", "Doğru Tanı/Durum", "Ayırıcı Tanı"]
    }
}

# ============================================================================
# PROMPTS
# ============================================================================

def construct_system_prompt_draft(examples_text="", discipline=None):
    base_prompt = """Türkçe tıp sınavı soru yazarı.
Görevin: Verilen metinden TUS/USMLE standardında soru taslağı çıkar.

SORU TİPLERİ (metne göre seç):
1) Klinik vinyet (öykü+muayene+lab) -> tanı/tedavi/yönetim
2) Spot bilgi (en sık, gold standart, ilk tercih)
3) Mekanizma/fizyopatoloji veya negatif kök
4) İfade doğrulama (tek kök + her şık ayrı ifade)
5) Roma rakamı kombinasyonu (I-IV maddeler + kombinasyon) -> Birden fazla spot bilgiyi (risk faktörleri, belirtiler) sorgulamak için bu formatı SIK KULLAN.

ROMA RAKAMI FORMAT:
- I–IV maddeleri soru kökünde ALT ALTA yaz (her madde ayrı satır, "I.", "II.", "III.", "IV.").
- Şıklar kombinasyon formatında olmalı (A–E) ve her şık AYRI seçenek nesnesi olarak yazılmalı.

TEK DOĞRU GARANTİSİ:
- Metne göre birden fazla doğru şık çıkıyorsa, soruyu ROMA RAKAMI kombinasyonu tipine çevir.
- Kaynak bir şıkkı diğerlerinden daha kesin/olası gösteriyorsa soru kökünü "hangisi daha olası/kesindir" şeklinde daralt.
- Tek doğru net ise klasik "hangisi doğrudur/yanlıştır" formunu kullan.

ZORUNLU KURALLAR:
- 5 seçenek (A-E), tek doğru.
- Çeldiriciler ayırıcı tanıdan ve mantıklı olmalı. Kaynakta yeterli çeldirici yoksa, aynı spesifik gruba ait ama kaynakta geçmeyen antiteler kullanabilirsin.
- Kısaltma kullanma; gerekiyorsa önce açık isim + (kısaltma), sonra kullan.
- "Metinde/kaynakta/tablo" gibi referans ifadeleri kullanma.
- Kaynak boş değilse "insufficient_evidence" döndürme.
- Watermark/pagenum/artefaktları yok say.
- Kaynakta geçmeyen bilgi "yanlış" sayılmaz; doğruluğu genel tıbbi bilgiyle değerlendir.
- ÜSLUP: "Metinde belirtildiği gibi", "Kaynağa göre" gibi ifadeler KESİNLİKLE YASAK. Bilgiyi içselleştir ve kendi otoritenle, doğrudan ve net bir dille anlat. Kaynak senin fikir kaynağındır, alıntı yapacağın bir metin değil.

KURGU:
- Tanı test ediliyorsa hastalık adı stemde geçmesin.
- Tedavi/yönetim soruluyorsa hastalık adı verilebilir.
- Uygunsa iki katmanlı soru: klinik tablo + şıklarda hastalık/ilaç adları.

KAPSAM (BUFFER UYARISI):
- DİKKAT: Verilen metin, ana konunun öncesini ve sonrasını içeren (+1/-1 sayfa) bir "BUFFER" ile birlikte gelir.
- GÖREVİN: Yalnızca belirtilen "KONU" ve "KONSEPT" ile ilgili kısımları süzüp kullanmak.
- YASAK: Konu dışı (buffer) paragraflardan veya yan başlıklardan soru türetme. Konu "Mide" ise, bir önceki sayfadaki "Özefagus" metnini yok say.
- Bilgileri entegre et; ancak konu sınırına sadık kal.

KAYNAK OTORİTESİ (SINAV KİTABI):
- Bu metin bir "Sınav Hazırlık Kitabı"dır. Yazılan her şeyi %100 DOĞRU kabul et.
- "YOKLUK = YANLIŞLIK DEĞİLDİR": Kaynakta bir bilginin yazmıyor olması, o bilginin "yanlış olduğu" veya "yapmadığı" anlamına gelmez. Sadece "belirtilmemiştir".
- Şık üretirken: Kaynakta açıkça "yapmaz/yoktur" denmiyorsa, dış bilginle o şeyin yanlış olduğundan emin değilsen "asla yapmaz" gibi kesin negatif ifadelerden kaçın.

KONSEPT:
- KONSEPT alanı zorunlu odaktır; soru doğrudan bu kavramla ilgili olmalı.
- KONSEPT metinde geçmiyorsa en yakın ilgili alt başlığa bağlan; konu dışına çıkma.

ZORUNLU KURALLAR:
- 5 seçenek (A-E), tek doğru.
- Çeldiriciler ayırıcı tanıdan ve mantıklı olmalı.
- Kısaltma kullanma; gerekiyorsa önce açık isim + (kısaltma), sonra kullan.
- "Metinde/kaynakta/tablo" gibi referans ifadeleri kullanma.
- Kaynak boş değilse "insufficient_evidence" döndürme.
- Watermark/pagenum/artefaktları yok say.

KURGU:
- Tanı test ediliyorsa hastalık adı stemde geçmesin.
- Tedavi/yönetim soruluyorsa hastalık adı verilebilir.
- Uygunsa iki katmanlı soru: klinik tablo + şıklarda hastalık/ilaç adları.

ZORLUK:
- Cevabı ele veren değer/isim yazma; gerekirse tedavi yanıtı ile ayırıcı tanı kur.
- Hedef Kitle: TUS/USMLE adayı (İntörn Doktor).

AÇIKLAMA VE AYIRICI TANI PRENSİPLERİ:
- KAPSAM: Soruda veya şıklarda geçen tüm hastalık/ilaç/antiteleri ("Mini DDX" veya "Detaylı Açıklama" kısmında) mutlaka açıkla.
- DOĞRU ŞIK DAHİL: "Mini DDX" tablosuna DOĞRU ŞIKKI da ekle ve neden doğru olduğunu analiz et.
- KALİTE: Yanlış şıkları sadece "bu yanlıştır" diyerek geçme; o hastalığın/ilacın ne olduğunu ve klinik önemini kısaca özetle (Mini ders notu gibi).
- BAĞLAM: Örneğin trombositopeni sorusunda şıklarda trombositoz varsa, trombositozun da ne zaman görüldüğünü belirt.

NOT: OCR_TEXT varsa tanıma hataları olabilir; çelişki varsa normal metni öncelikle kullan.
NOT: Tıbbi içerik dışındaki her şeyi yok say.

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
    
    # DERS ODAK PROFİLİ ENJEKSİYONU
    discipline_instruction = ""
    if discipline and discipline in DISCIPLINE_FOCUS_PROFILES:
        discipline_instruction = DISCIPLINE_FOCUS_PROFILES[discipline]["focus_instruction"]
    
    # Base prompt construction (Injecting discipline instruction before rules)
    full_prompt = base_prompt.replace("{examples}", examples_text)
    
    if discipline_instruction:
        # Insert after "Görevin:..."
        insert_point = "Görevin: Verilen metinden TUS/USMLE standardında soru taslağı çıkarmak."
        full_prompt = full_prompt.replace(insert_point, f"{insert_point}\n\n    {discipline_instruction}")
    
    # TABLE USAGE INSTRUCTION (GLOBAL)
    table_instruction = """
    TABLE VE LİSTE ÖNCELİĞİ:
    - Kaynakta tablo veya maddeli liste varsa soru üretiminde buna ÖNCELİK VER.
    - NEGATİF SORULAR: "Hangisi X riskini artırmaz?" gibi sorularda, tablo dışından MANTIKSAL ZITLIKLAR kullan.
      * Örnek: Tablo "Trombositopeni risk artırır" diyorsa, şıklara "Trombositoz" (doğru cevap) koyabilirsin.
      * Ancak DİKKAT: Hipotermi/Hipertermi gibi ikisinin de risk olduğu durumlarda bu kuralı uygulama.
    - Tabloda geçmeyen ama o bağlamda kesinlikle yanlış olan bilgileri (mantıksal çıkarım yaparak) kullanmaktan çekinme.
    """
    insert_point_rules = "KURALLAR:"
    full_prompt = full_prompt.replace(insert_point_rules, f"{table_instruction}\n\n    {insert_point_rules}")
        
    return full_prompt

SYSTEM_PROMPT_DRAFT_BASE = construct_system_prompt_draft()


SYSTEM_PROMPT_CRITIQUE = """Kıdemli tıp editörüsün. Taslak soruyu hızlı kontrol et.

Kontrol:
1) Kurgu hatası var mı?
2) Doğru cevap tek mi?
3) Çeldiriciler güçlü mü ve yanlış şıklardan biri de doğruya gidiyor mu?
4) Soru kökü bir şıkkı isim benzerliği/çağrışımla direkt ele veriyor mu?
5) 2-4 sibling (kardeş antite) öner.

DÜZELTME YETKİSİ:
- Hata varsa, aynı bağlamı koruyarak soru kökünü/şıkları düzelt.
- Birden fazla doğruya giden şık varsa, doğru olmayanı kaynağa UYUMLU olacak şekilde değiştir.
- Gerekirse correct_option_id güncelle.
- ABORT ETME. Her zaman action="revise" veya action="accept" dön.

ABORT SADECE ŞU DURUMLARDA:
- (DEVRE DIŞI) Bu modda abort kullanılmaz. Her zaman revise veya accept.

TERCIH SIRASI:
- Mümkünse action="revise" ile düzelt (kök/şık/distraktör).
- Tek doğru zaten varsa ve sadece küçük kalite sorunları varsa action="accept".

ZORUNLU KONTROL (Cevap Sızması / İsim Benzerliği):
- HATA TANIMI: Soru kökünde doğru şıkkın *ismi*, *eşanlamlısı* veya *kelime kökü* açıkça geçiyorsa bu bir SIZDIRMADIR (Leakage).
  - Örnek HATA: "Çölyak artere bası yapan durum..." -> Cevap: "Çölyak arter bası sendromu" (Kelime kökü aynı).
- GEÇERLİ SORU (Feature -> Entity): Soru kökünde bir hastalığın/ilacın mekanizması, klinik bulgusu veya özelliği verip ismini sormak HATA DEĞİLDİR. Bu bir "Tanı/Bilgi" sorusudur ve kabul edilmelidir.
  - Örnek GEÇERLİ: "Mu reseptör parsiyel agonisti olan..." -> Cevap: "Buprenorfin". (Bu leakage değildir, bilgiyi ölçer).
- Action="revise" sadece gerçek sızdırma (kelime benzerliği) varsa seç. Özellik-İsim eşleşmesi varsa action="accept" ver.

ZORUNLU KONTROL (Tek Doğru / Çift Cevap):
- Her şık için "doğru/yanlış/şüpheli" değerlendirmesi yap.
- Olası doğru şıkların ID listesini ver (possible_correct_option_ids).
- Eğer mümkün doğru şık sayısı 1'den fazla ise (Çift Cevap), action="revise" ZORUNLUDUR.
- ÇÖZÜM 1: Fazla olan doğru şıklardan birini, kaynak metne göre KESİN YANLIŞ olan bir bilgiyle değiştir (Distractor Replacement).
- ÇÖZÜM 2: Eğer şıkları değiştirmek zorsa ve soru uygunsa, soruyu "Roma Rakamı Kombinasyonu" formatına çevir.
- ÇÖZÜM 3: Kaynak metinde karşılaştırma varsa (daha sık, en yüksek, daha fazla vb.), soru kökünü bu nüansı içerecek şekilde değiştir (Örn: "Hangisi yapar?" yerine "Hangisi EN SIK yapar?").
- ASLA çift cevaplı soruyu "accept" etme. Mutlaka bu üç çözümden birini uygulayarak revize et.
- Kaynakta geçmeyen bilgi "yanlış" sayılmaz; bu durumda "şüpheli" de. Doğruluğu genel tıbbi bilgiyle değerlendir.

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

NOT:
- critique_passed = true sadece action="accept" ise.
- action="revise" ise critique_passed=false olmalı.
"""

SYSTEM_PROMPT_RECONCILE = """Ana metin ile güncellemeyi karşılaştır.
1) UPDATE, MAIN'i değiştiriyor mu?
2) Varsa değişikliği özetle.
3) Çelişki çözülmüyorsa 'unresolved_conflict' işaretle.

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

SYSTEM_PROMPT_TABLE_REFINE = """Kıdemli tıp editörüsün.
Görev: Verilen tabloyu daha net ve doğru bir karşılaştırma tablosuna dönüştür.

KURALLAR:
- Sadece tabloyu düzelt; soru/şıklar/diğer bloklara dokunma.
- Tablo karşılaştırma odaklı ve sade olsun.
- Yeni tıbbi bilgi ekleme; yalnızca mevcut hücre içeriklerini kısalt/yeniden düzenle.
- Bağlam (context) bilgisini içerik eklemek için kullanma; sadece başlık netleştirmede yararlan.
- Başlıklar kısa ve içerik odaklı olsun; "doğru cevap" ve "çeldirici" kelimeleri asla geçmesin.
- Varlık isimleri sütun başlıklarında olmalı (örn. "Özellik", "HPV 6-11", "Treponema pallidum").
- Varlık isimlerini satır etiketi olarak kullanma.
- Bir başlıkta birden fazla varlık listelenmişse ayır ve ayrı sütun yap.
- JSON sadece tablo bloğu olarak dönsün.

ÇIKTI ŞEMASI (JSON):
{
  "type": "table",
  "title": "...",
  "headers": ["...", "...", "..."],
  "rows": [
    {"entity": "...", "cells": ["...", "..."] }
  ]
}
"""

def construct_system_prompt_blocks(existing_tags: list = []) -> str:
    tags_hint = ""
    if existing_tags:
        tags_str = ", ".join([f'"{t}"' for t in existing_tags])
        tags_hint = f"\n- MEVCUT ETİKETLERİ KULLANMAYA ÇALIŞ: {tags_str}\n- Eğer uygunsa bunlardan birini seç. Değilse yeni üret."

    return f"""Sen kıdemli bir tıp profesörüsün.
Görevin: açıklamayı JSON formatında, ZORUNLU BLOK yapısında üretmek.

KISA KURALLAR:
- Doğru cevabı ismiyle yaz (`main_mechanism` + heading).
- Kaynak atfı yapma ("metinde/kaynakta..." yasak). Bilgiyi kendi bilginmiş gibi doğrudan anlat.
- Kısaltma kullanma; gerekiyorsa önce açık isim + (kısaltma), sonra kullan.
- Doğruluk kontrolünde genel tıbbi bilgi kullanabilirsin; ancak soru/şık/çıktı kaynağa UYUMLU olmalı.
- Kaynakta geçmeyen bilgi \"yanlış\" değildir; belirsizse soruyu kaynağa UYUMLU olacak şekilde düzelt.
- Eksikse kısa ve nötr ifade kullan (ör. "Soruda belirtilmemiştir"); "Bilinmiyor" yazma.
- Taslak soru ile kaynak çelişirse, soru kökü/şıklar/doğru şık bilgisini KAYNAĞA göre düzelt.
- Tek doğruyu sağlamak için gerekiyorsa kaynakta geçen ayırt edici ipucunu soru köküne ekle.
- Birden fazla doğru varsa soruyu ROMA RAKAMI kombinasyonu tipine çevir veya "hangisi daha olası/kesindir" şeklinde daralt.
- Yanlış şıkları `mini_ddx` ile açıkla; değerlendirmede genel tıbbi bilgi kullanabilirsin ama çıktı kaynağa UYUMLU olmalı.
- `exam_trap` bloğu kaynağa UYUMLU olmalı; genel tıbbi bilgiyle doğruluk kontrolü yapabilirsin.
- ROMA RAKAMI / ÖNCÜLLÜ SORU KURALI (mini_ddx):
  - Soru kökünde I, II, III gibi öncüller varsa `mini_ddx` bloğunu ŞIKLARA GÖRE DEĞİL, ÖNCÜLLERE GÖRE YAZ.
  - `option_id` değerlerini "I", "II", "III", "IV" olarak kullan.
  - Her bir öncülün neden doğru veya yanlış olduğunu açıkla.
  - Şıkları (A, B...) değil, doğrudan öncülleri analiz et.
  - `numbered_steps` bloğunu standart mekanizma anlatımı için kullan (öncül analizi için değil).
  - `numbered_steps` kısmında öncüller analiz edildiği için, burada tekrara düşme.
  - `mini_ddx` analizini kombinasyon mantığına göre yaz.
  - YASAK: "A şıkkı yanlıştır çünkü I yanlıştır" gibi totolojik (döngüsel) açıklama yapma.

TABLO:
- Kardeş/karışan antiteleri karşılaştıran tablo ekle.
- Yapıyı sen belirle; tablo net ve karşılaştırmalı olsun.
- JSON formatında "headers" ve "rows" alanlarını doldur (başlık/row yapısı sana ait).
- Hücrelere varlık etiketi yazma (örn. "Gabapentin:").
- Başlıklar kısa ve içerik odaklı olmalı; meta etiketler kullanma (örn. "doğru cevap", "çeldirici").
- Sütun başlıkları gerçek varlık isimleri olmalı (örn. "HPV 6-11", "Treponema pallidum").
- Varlık isimlerini "İsim" satırı olarak yazma; başlıkta ver.
- Bir sütunda birden fazla varlık birleştirme; gerekiyorsa yeni sütun aç.

VISUAL TAGGING:
- Yolak/şema/döngü/ilaç mekanizması varsa `visual:*` etiketi ekle.
- Anatomi: pleksus/boşluk/foramen -> `visual:anatomy_plexus|space|foramen`.
{tags_hint}

AÇIKLAMA YAPISI:
- Kendi açıklamanı özgürce yaz. Konuyu derinleştirebilir, klinik bağlam ekleyebilirsin.
- Aşağıdaki 3 bloğu her zaman ekle:
  1) callout (exam_trap)
  2) mini_ddx
  3) table

İSTEĞE BAĞLI BLOKLAR (gerekirse ekle):
- heading, key_clues, numbered_steps

ÇIKTI ŞEMASI (JSON):
{{
  "source_material": "Küçük Stajlar",
  "topic": "Nöroloji",
  "question_text": "...",
  "options": [{{"id": "A", "text": "..."}}, ...],
  "correct_option_id": "A",
  "tags": ["concept:..."],
  "explanation": {{
      "main_mechanism": "Bu soruda doğru cevap [ENTITY ADI]. [Kısa mekanizma özeti, max 400 karakter]",
      "clinical_significance": "Kısa özet (max 400 karakter)",
      "sibling_entities": ["...", "..."],
      "updates_applied": [],
      "update_checked": true,
      "blocks": [
        {{ "type": "heading", "level": 1, "text": "Detaylı Açıklama & Mekanizma" }},
        {{ "type": "callout", "style": "key_clues", "title": "Klinik İpuçları", "items": [{{"text": "..."}}, {{"text": "..."}}] }},
        {{ "type": "numbered_steps", "title": "Mekanizma Zinciri", "steps": ["...", "..."] }},
        {{ "type": "callout", "style": "exam_trap", "title": "Sınav Tuzağı", "items": [{{"text": "..."}}] }},
        {{ "type": "mini_ddx", "title": "Çeldirici Analizi", "items": [
            {{ "option_id": "B", "label": "...", "analysis": "..." }}
          ]
        }},
        {{ "type": "table", "title": "Ayırıcı Tanı", "headers": ["Özellik", "ENTİTE A", "ENTİTE B"],
          "rows": [
            {{ "entity": "Patogenez", "cells": ["...", "..."] }},
            {{ "entity": "Klinik Bulgular", "cells": ["...", "..."] }}
          ]
        }}
      ]
  }}
}}
"""

SYSTEM_PROMPT_REPAIR = """You are a JSON repair expert.
Your Task: Fix the broken JSON provided by the user so it matches the Pydantic schema perfectly.

COMMON FIXES:
1. `mini_ddx` items must include ALL options (correct + wrong).
   - Look at `options` list.
   - Ensure every option ID (A, B, C, D, E) has exactly one entry in DDX.
2. `table` rows must have correct cell count matching headers (headers column - 1).
3. `option_id` must be A, B, C, D, or E.
4. `blocks` list must have at least 3 items (exam_trap, mini_ddx, table are mandatory).
5. **CRITICAL**: For `callout` blocks:
   - Use `type: "callout"`.
   - Include a `title`.
   - `items` MUST be a list of OBJECTS: `[{"text": "Point 1"}, {"text": "Point 2"}]`. Do NOT use strings directly.
6. Ensure `options` is a list of objects `{"id": "A", "text": "..."}`.
7. Do NOT use placeholder content like "Bilinmiyor", "Unknown", "N/A", or empty strings.

Output ONLY valid JSON.
"""


# ============================================================================
# CLIENT CLASS
# ============================================================================

class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        vertex_project: Optional[str] = None,
        vertex_location: Optional[str] = None,
        vertex_enabled: Optional[bool] = None
    ):
        # Multi-Key Support for Round-Robin (Gemini Developer mode)
        self.api_keys = []
        if api_key:
            self.api_keys.append(api_key)
        else:
            main_key = os.environ.get("GEMINI_API_KEY")
            if main_key:
                self.api_keys.append(main_key)
            i = 2
            while True:
                key = os.environ.get(f"GEMINI_API_KEY_{i}")
                if not key:
                    break
                self.api_keys.append(key)
                i += 1

        self.vertex_project = (
            vertex_project
            or os.environ.get("VERTEX_PROJECT")
            or os.environ.get("GCLOUD_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        )
        self.vertex_location = vertex_location or os.environ.get("VERTEX_LOCATION") or "us-central1"
        env_vertex_flag = os.environ.get("GEMINI_USE_VERTEX", "").lower() in {"1", "true", "yes"}
        self.vertex_enabled = vertex_enabled if vertex_enabled is not None else env_vertex_flag

        self.credentials = None
        if self.vertex_enabled or not self.api_keys:
            try:
                creds, default_project = google.auth.default()
                self.credentials = creds
                if not self.vertex_project:
                    self.vertex_project = default_project
                self.vertex_enabled = True
            except Exception as exc:
                if not self.api_keys:
                    raise ValueError(
                        "No GEMINI_API_KEY found and ADC credentials are unavailable."
                    ) from exc
        if not self.vertex_enabled and not self.api_keys:
            raise ValueError("GEMINI_API_KEY not found and Vertex mode is disabled.")

        if self.vertex_enabled:
            print(
                "🔐 GeminiClient initialized in Vertex mode "
                f"(project={self.vertex_project}, location={self.vertex_location})."
            )
        else:
            print(f"🔑 GeminiClient initialized with {len(self.api_keys)} API Keys.")

        self.api_key = self.api_keys[0] if self.api_keys else None
        self.client = self._build_client(api_key=self.api_key)
        
        # Load Reference Examples
        self.reference_examples = self._load_reference_examples()
        
        # Models Configuration
        # Defaults: gemini-3-flash-preview for premium tasks
        self.flash_model_name = "gemini-3-flash-preview"
        self.pro_model_name = "gemini-3-flash-preview"  # Use same model for pro tasks

        # Rate Limiting (Token Bucket)
        # 15 RPM = 1 request every 4 seconds per thread? No, global bucket.
        # We share this client instance or we assume 15 RPM total for the API key.
        # Let's implementation a simple class-level safe-guard if instanced per thread, 
        # but ideally this should be global. JobManager uses new instance per job?
        # Actually background_jobs.py creates new instance per job.
        # So we'll use a class-level bucket.
        
    # Class-level rate limiter
    _last_request_time = 0
    _request_interval = 1.0 # Faster rate limit for Flash Lite (higher quota)
    
    # Global Circuit Breaker for 429s
    # Shared across all threads to stop everything if one thread hits a limit.
    _cooldown_until = 0.0

    # Class-level PDF cache for context caching
    # Key: PDF file path, Value: {"cache_name": str, "uploaded_file": obj, "expires_at": float}
    _pdf_cache = {}
    _cache_ttl_seconds = 1800  # 30 minutes TTL for cached content

    def _wait_for_rate_limit(self):
        """Simple global rate limiter to prevent 429s"""
        # 1. Check Global Circuit Breaker
        current = time.time()
        if current < GeminiClient._cooldown_until:
            wait_time = GeminiClient._cooldown_until - current
            logging.warning(f"   🛑 Global Circuit Breaker Active. Pausing ALL threads for {wait_time:.1f}s...")
            time.sleep(wait_time)
            # Re-read time after sleep
            current = time.time()

        # 2. Per-Request Interval (RPM Control)
        elapsed = current - GeminiClient._last_request_time
        if elapsed < GeminiClient._request_interval:
            sleep_time = GeminiClient._request_interval - elapsed
            time.sleep(sleep_time)
        GeminiClient._last_request_time = time.time()

    def _build_client(self, api_key: Optional[str] = None) -> genai.Client:
        """Initialize a genai.Client for either Vertex or Gemini Developer API."""
        client_kwargs = {}
        if self.vertex_enabled:
            client_kwargs["vertexai"] = True
            if self.vertex_project:
                client_kwargs["project"] = self.vertex_project
            if self.vertex_location:
                client_kwargs["location"] = self.vertex_location
            if self.credentials:
                client_kwargs["credentials"] = self.credentials
        else:
            if not api_key:
                raise ValueError("API key is required when Vertex mode is disabled.")
            client_kwargs["api_key"] = api_key
        # Prevent indefinitely hanging HTTP calls (timeout is in milliseconds).
        client_kwargs["http_options"] = types.HttpOptions(timeout=DEFAULT_HTTP_TIMEOUT_MS)
        return genai.Client(**client_kwargs)

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
        for i, ex in enumerate(examples[:2]): # Limit to 2 examples context for speed
            out.append(f"ÖRNEK {i+1}:")
            out.append(f"Soru: {ex['question']}")
            out.append(f"Seçenekler: {json.dumps(ex.get('options', []))}")
            out.append("---")
            
        return "\n".join(out)
    
    def get_sticky_key(self):
        """Returns a random key to be bound to a job/session (Vertex uses ADC, so None)."""
        if self.vertex_enabled or not self.api_keys:
            return None
        return random.choice(self.api_keys)

    def _get_rotated_client(self):
        """Returns a genai.Client using either Vertex ADC or a rotated API key."""
        if self.vertex_enabled:
            return self._build_client()
        return self._build_client(api_key=self.get_sticky_key())

    def _generate_with_fallback(self, system_instruction: str, prompt: str, model_type: str = "flash", json_output: bool = False, specific_api_key: str = None, **kwargs) -> str:
        """
        Generate content with automatic model fallback and per-model retries.
        args:
            json_output: If True, will retry generation if the output is not valid JSON.
            specific_api_key: If provided, forces use of this key (needed for file permissions).
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
                        # Exponential backoff with Jitter: (2^attempt) + random(0.1, 1.5)
                        backoff = 2 ** attempt
                        jitter = random.uniform(0.1, 1.5)
                        wait_time = backoff + jitter
                        
                        logging.info(f"   🔄 Retrying {model_name} (Attempt {attempt+1}/{MAX_RETRIES_PER_MODEL+1}) in {wait_time:.2f}s...")
                        time.sleep(wait_time)
                    else:
                        logging.info(f"   🤖 Trying model: {model_name}")
                        
                    config_args = {
                        "system_instruction": system_instruction,
                        "temperature": 0.7
                    }
                    
                    if "response_schema" in kwargs:
                        config_args["response_mime_type"] = "application/json"
                        config_args["response_schema"] = kwargs["response_schema"]
                    elif json_output:
                        config_args["response_mime_type"] = "application/json"
                    
                    if "cached_content" in kwargs and kwargs["cached_content"]:
                        config_args["cached_content"] = kwargs["cached_content"]
                        logging.info(f"   💾 Using cached content for request")
                    
                    logging.info(f"   📡 Calling Gemini API ({model_name})...")
                    start_time = time.time()
                    
                    # Sticky Key Implementation
                    if specific_api_key and not self.vertex_enabled:
                        current_client = self._build_client(api_key=specific_api_key)
                    else:
                        current_client = self._get_rotated_client()
                    
                    response = current_client.models.generate_content(
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
                    error_lower = error_str.lower()
                    last_error = e
                    logging.error(f"   ❌ Error with {model_name} (Attempt {attempt+1}): {e}")
                    
                    # Check if retryable error (Quota or transient 500/Internal OR Malformed JSON OR Overloaded)
                    is_rate_limit = any(x in error_str for x in ["429", "ResourceExhausted", "Quota", "UNAVAILABLE", "Overloaded"])
                    is_timeout = any(x in error_lower for x in ["timeout", "timed out", "readtimeout", "connecttimeout", "deadline exceeded"])
                    is_retryable = (
                        is_rate_limit
                        or is_timeout
                        or any(x in error_str for x in ["500", "503", "Internal", "internal_error", "Malformed JSON"])
                    )
                    is_not_found = any(x in error_str for x in ["404", "not found"])

                    # CRITICAL: Trigger Global Circuit Breaker on Rate Limit
                    if is_rate_limit:
                        # Add Jitter to Global Cooldown (45s - 90s) to prevent Thundering Herd
                        cooldown_secs = random.uniform(45.0, 90.0)
                        logging.warning(f"   ⚠️ Rate Limit Hit ({model_name}). Triggering GLOBAL COOLDOWN for {cooldown_secs:.1f}s.")
                        GeminiClient._cooldown_until = time.time() + cooldown_secs
                    
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

    def upload_file(self, path: str, specific_api_key: str = None):
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
        
        # Select Client
        if specific_api_key and not self.vertex_enabled:
            upload_client = self._build_client(api_key=specific_api_key)
        else:
            upload_client = self._get_rotated_client()
        
        try:
            # Vertex Support: Return local path, SDK handles it or we handle it downstream
            if self.vertex_enabled:
                 print(f"   ℹ️ Vertex Mode: Using local file path instead of File API upload (not supported).")
                 return types.Part.from_uri(file_uri=path, mime_type="application/pdf") if path.startswith("gs://") else path

            # Copy to temp
            shutil.copy(path, temp_path)
            
            # New SDK file upload using the safe path
            # We can pass the original name as display_name if needed, but not critical for generation
            file_ref = upload_client.files.upload(file=temp_path)
            print(f"   ✅ File uploaded: {file_ref.name} (URI: {file_ref.uri})")
            return file_ref
        except Exception as e:
            if "Only supported" in str(e) or self.vertex_enabled:
                print(f"   ℹ️ Fallback to local path (Vertex/Error): {path}")
                # For Vertex, we can return the path. The SDK client often handles local paths in 'contents'.
                return path
            print(f"   ❌ File upload failed: {e}")
            raise e
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def get_or_create_pdf_cache(self, pdf_path: str, system_instruction: str = None, specific_api_key: str = None):
        """
        Get or create a cached content for a PDF file.
        If the PDF was already cached and cache hasn't expired, returns the cache name.
        Otherwise, uploads the PDF, creates a new cache, and returns the cache name.
        
        This provides ~90% cost savings on input tokens for repeated use of the same PDF.
        
        Returns: (cache_name, uploaded_file_ref) tuple
        """
        current_time = time.time()
        
        # Cache Key now includes the API Key to prevent 403 Inter-Key Access Errors
        # (If specific_api_key is None, we use 'default')
        cache_identifier = f"{pdf_path}_{specific_api_key[-4:] if specific_api_key else 'default'}"
        
        # Check if PDF is already cached and not expired
        if cache_identifier in GeminiClient._pdf_cache:
            cache_entry = GeminiClient._pdf_cache[cache_identifier]
            if cache_entry.get("expires_at", 0) > current_time:
                logging.info(f"   💾 Using cached PDF: {os.path.basename(pdf_path)} (Key: ...{specific_api_key[-4:] if specific_api_key else 'def'})")
                return cache_entry.get("cache_name"), cache_entry.get("uploaded_file")
            else:
                logging.info(f"   🔄 Cache expired for: {os.path.basename(pdf_path)}")
                # Remove expired entry
                del GeminiClient._pdf_cache[cache_identifier]
        
        if self.vertex_enabled:
             print(f"   ℹ️ Vertex Mode: PDF Caching skipped (using inline/local file).")
             # Just return None for cache_name and the path (or Part) as uploaded_file
             # We rely on downstream generate_content to handle the path/Part
             return None, types.Part.from_bytes(data=open(pdf_path, "rb").read(), mime_type="application/pdf")

        # Select Client
        if specific_api_key and not self.vertex_enabled:
             cache_client = self._build_client(api_key=specific_api_key)
        else:
             cache_client = self.client # Fallback to default client
             
        # Upload the PDF first (reuse existing upload_file method)
        logging.info(f"   📤 Uploading PDF for caching: {os.path.basename(pdf_path)}")
        uploaded_file = self.upload_file(pdf_path, specific_api_key=specific_api_key)
        
        # Create cache with the uploaded file
        try:
            default_system = system_instruction or "You are a medical education expert analyzing PDF content."
            
            cache = cache_client.caches.create(
                model=self.flash_model_name,
                config=types.CreateCachedContentConfig(
                    display_name=f"pdf_cache_{os.path.basename(pdf_path)}",
                    system_instruction=default_system,
                    contents=[uploaded_file],
                    ttl=f"{GeminiClient._cache_ttl_seconds}s"
                )
            )
            
            # Store in class-level cache
            GeminiClient._pdf_cache[cache_identifier] = {
                "cache_name": cache.name,
                "uploaded_file": uploaded_file,
                "expires_at": current_time + GeminiClient._cache_ttl_seconds
            }
            
            print(f"   ✅ PDF cached successfully: {cache.name}")
            return cache.name, uploaded_file
            
        except Exception as e:
            print(f"   ⚠️ Cache creation failed, using direct upload: {e}")
            # Fallback: return None cache_name, use uploaded_file directly
            return None, uploaded_file
    
    def clear_pdf_cache(self, pdf_path: str = None):
        """Clear PDF cache. If pdf_path is None, clears all caches."""
        if pdf_path:
            if pdf_path in GeminiClient._pdf_cache:
                del GeminiClient._pdf_cache[pdf_path]
                print(f"   🗑️ Cache cleared for: {pdf_path}")
        else:
            GeminiClient._pdf_cache.clear()
            print("   🗑️ All PDF caches cleared")

    def draft_question(self, concept: str, evidence: str, topic: str, media_file=None, cached_content: Optional[str] = None, discipline=None, specific_api_key: str = None, strict: bool = True, **kwargs) -> dict:
        """Stage 1: Draft (Enhanced with Few-Shot Examples)"""
        
        # 1. Get Examples
        examples_text = self._get_examples_text(topic)
        
        # 2. Construct Dynamic System Prompt
        dynamic_system_prompt = construct_system_prompt_draft(examples_text, discipline)
        
        # 3. Use structured output
        # If media_file is provided, evidence might be empty or a summary
        if cached_content:
            prompt_text = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK: Attached PDF Document."
            contents = prompt_text
        elif media_file:
            prompt_text = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK: Attached PDF Document."
            contents = [prompt_text, media_file]
        else:
            prompt_text = f"KONSEPT: {concept}\nKONU: {topic}\nKAYNAK:\n{evidence}"
            contents = prompt_text
        
        # We pass the Schema dict
        response_text = self._generate_with_fallback(
            dynamic_system_prompt, 
            contents, 
            model_type="pro",
            json_output=True,
            response_schema=SCHEMA_QUESTION_DRAFT,
            specific_api_key=specific_api_key,
            cached_content=cached_content
        )
        return self._safe_json_load(response_text)

    def critique_question(self, draft: dict, evidence: str, topic_verification_result: dict = None, specific_api_key: str = None) -> dict:
        """Stage 2: Critique & Suggest Siblings (Uses PRO for better reasoning)"""
        # For critique, we might not pass the full PDF to save tokens/time if draft is good.
        # But ideally we should. For now, let's assume critique works on the textual evidence or self-consistency.
        # If evidence was a PDF, we don't have text here unless we extracted it.
        # TODO: Pass PDF to critique as well if needed. For now, we'll rely on the draft content.
        
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

        prompt = f"SORU: {json.dumps(draft, ensure_ascii=False)}\n\n{topic_feedback_str}\n\nKAYNAK (Özet/Metin):\n{evidence}"
        # Quality: Use premium model (gemini-3-flash-preview) for critique - important for sibling suggestions
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_CRITIQUE, prompt, model_type="flash", json_output=True, specific_api_key=specific_api_key)
        return self._safe_json_load(response_text)
        
    def reconcile_updates(self, main_evidence: str, update_evidence: str) -> list:
        """Stage 2b: Reconcile Update Evidence"""
        if not update_evidence:
            return []
            
        prompt = f"""
        MAIN EVIDENCE:
        {main_evidence}
        
        UPDATE EVIDENCE:
        {update_evidence}
        """
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_RECONCILE, prompt, model_type="flash", json_output=True)
        result = self._safe_json_load(response_text)
        return result.get("updates_applied", [])

    def check_topic_alignment(self, question_text: str = None, correct_option: str = None, target_topic: str = None, draft: dict = None, evidence: str = "", specific_api_key: str = None) -> dict:
        """
        Gating Step (Reporter Mode): Verify if the generated question actually belongs to the target topic.
        Returns a report to be used by the Critique step. DOES NOT REVISE.
        """
        if draft and isinstance(draft, dict):
            question_text = question_text or draft.get("question_text", "")
            correct_option = correct_option or next(
                (o.get("text") for o in draft.get("options", []) if isinstance(o, dict) and o.get("id") == draft.get("correct_option_id")),
                "Unknown"
            )
        evidence_text = evidence or ""
        gate_prompt = f"""
        YOU ARE A TOPIC ALIGNMENT ANALYST.
        
        TARGET TOPIC: {target_topic}
        
        DRAFT (JSON):
        {json.dumps(draft if isinstance(draft, dict) else {{"question_text": question_text, "correct_option": correct_option}}, ensure_ascii=False)}
        
        EVIDENCE (may be empty):
        {evidence_text if evidence_text else "NO_TEXT_EVIDENCE"}
        
        TASK:
        1. Determine if the question belongs to the TARGET TOPIC.
        2. Check for "Topic Drift" (e.g. asking about Cardiology in a Neurology topic).
        3. Provide specific feedback for the Editor (Critique Step).
        
        OUTPUT JSON:
        {{
            "topic_match": true/false,
            "predicted_topic": "string",
            "reason": "short explanation",
            "feedback_for_critique": "Instructions for the editor. If match=false, explain clearly how to fix the drift."
        }}
        """
        
        try:
            # Use primary flash model for alignment (non-JSON-fix tasks stay on gemini-3-flash-preview)
            response_text = self._generate_with_fallback(
                "You are a topic alignment analyst.",
                gate_prompt,
                model_type="flash",
                json_output=True,
                specific_api_key=specific_api_key
            )
            data = self._safe_json_load(response_text)
            return data
        except Exception as e:
            print(f"⚠️ Topic Gate Error: {e}")
            return {"topic_match": False, "predicted_topic": "Error", "reason": str(e), "feedback_for_critique": "Topic check failed due to technical error."}

    def select_best_topic(self, question_text: str, topic_list: list) -> str:
        """
        Given a question and a list of possible topics, asks the model to pick the best fit.
        """
        options_text = "\n".join([f"- {t}" for t in topic_list])
        
        selection_prompt = f"""
        TASK: CATEGORIZE THIS MEDICAL QUESTION.
        
        POSSIBLE TOPICS (Select ONE):
        {options_text}
        
        QUESTION:
        {question_text}
        
        RULES:
        1. Return ONLY the exact string from the POSSIBLE TOPICS list.
        2. Do not add explanations or quotes.
        3. If unsure, pick the first one.
        """
        
        try:
            response_text = self._generate_with_fallback("You are a medical topic classifier.", selection_prompt, model_type="flash")
            selected = response_text.strip()
            # Clean if model added extra markers
            if selected.startswith("- "): selected = selected[2:]
            return selected
        except Exception as e:
            print(f"⚠️ Topic Selection Error: {e}")
            return topic_list[0] if topic_list else "Unknown"



    def extract_concepts(self, text: str, topic: str, count: int = 20, media_file=None, cached_content: Optional[str] = None, specific_api_key: str = None, avoid_concepts: Optional[list] = None) -> list:
        """
        Extracts a list of key concepts/diseases from the source text or PDF for question generation.
        """
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
        
        try:
            if cached_content:
                contents = prompt_text
            elif media_file:
                contents = [prompt_text, media_file]
            else:
                contents = prompt_text
                
            # Use fallback system for extraction
            response_text = self._generate_with_fallback(
                "You are a medical concept extractor.", 
                contents, 
                model_type="flash",
                json_output=True,
                response_schema=SCHEMA_CONCEPT_LIST,
                specific_api_key=specific_api_key,
                cached_content=cached_content
            )
            data = self._safe_json_load(response_text)
            return data.get("concepts", [])
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.error(f"⚠️ Concept Extraction Failed: {e}")
            return []


    def generate_explanation_blocks(self, draft: dict, critique: dict, updates: list, evidence: str, source_material: str, topic: str, media_file=None, cached_content: Optional[str] = None, use_pro_model: bool = True, discipline=None, student_level: str = "advanced", specific_api_key: str = None) -> dict:
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
        
        # TABLO BAŞLIK ÖNERİSİ (Basit ve tutarlı)
        table_hint = ""
        if discipline and discipline in DISCIPLINE_FOCUS_PROFILES:
            table_hint = (
                "\n        TABLO KURALI:"
                "\n        - İlk sütun \"Özellik\" veya \"Kriter\" olsun."
                "\n        - Diğer sütunlar gerçek varlık/antite isimleri olsun (doğru + kardeş antiteler)."
                "\n        - \"Doğru/Ayırıcı/Çeldirici\" gibi meta başlıklar kullanma."
                "\n        - Bir sütunda birden fazla varlık birleştirme; gerekiyorsa yeni sütun aç (max 4)."
            )

        # LEVEL INSTRUCTION (TUS STANDARD)
        # Kullanıcı Feedback'i: Hedef kitle 6. sınıf (İntörn). Daima ileri seviye kabul edilecek.
        level_instruction = """
        HEDEF KİTLE: TUS adayı (ileri seviye).
        - Dil profesyonel; gereksiz uzatma yok.
        - High-yield, ayırıcı tanı ve klinik tuzaklara odaklan.
        """

        prompt_text = f"""
        GİRDİ VERİSİ:
        {json.dumps(request_context, ensure_ascii=False)}
        
        KAYNAK:
        {evidence if evidence else "Attached PDF Document."}
        
        Doğruluk kontrolünde genel tıbbi bilgi kullanabilirsin; ancak soru/şık/çıktı kaynağa UYUMLU olmalı.
        Eğer taslak soru kaynakla çelişiyorsa, soru kökü/şıkları/doğru şık bilgisini KAYNAĞA göre düzelt.
        Çelişki yoksa taslak soru ve şıkları AYNEN koru (parafraz yapma).
        
        ŞEMAYA TAM UYGUN JSON üret (options + explanation.blocks zorunlu).
        
        KARŞILAŞTIRMA:
        - Sibling entity'leri tespit et.
        - 'mini_ddx' ve 'table' bloklarında mutlaka karşılaştır.
        {table_hint}
        {level_instruction}
        """
        
        if cached_content:
            contents = prompt_text
        elif media_file:
            contents = [prompt_text, media_file]
        else:
            contents = prompt_text
        
        # Always use PRO models for complex structured output
        # Fetch existing visual tags for dynamic prompt injection
        try:
            from backend.database import get_all_visual_tags
            existing_visual_tags = get_all_visual_tags()
        except:
            existing_visual_tags = []

        # Construct dynamic prompt blocks
        dynamic_blocks_prompt = construct_system_prompt_blocks(existing_visual_tags)

        response_text = self._generate_with_fallback(
            dynamic_blocks_prompt, 
            contents, 
            model_type="pro",
            json_output=True,
            response_schema=SCHEMA_FULL_RESPONSE,
            specific_api_key=specific_api_key,
            cached_content=cached_content
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
        # Cost optimization: Use cheaper Gemini 2.0 Flash for JSON repair (simple formatting task)
        response_text = self._generate_with_fallback(SYSTEM_PROMPT_REPAIR, prompt, model_type="flash", json_output=True, model_priority_override=MODEL_PRIORITY_CHEAP)
        return self._safe_json_load(response_text)

    def refine_table_block(self, table_block: dict, context: dict) -> dict:
        payload = {
            "context": context,
            "table": table_block,
        }
        prompt = f"GİRİŞ:\n{json.dumps(payload, ensure_ascii=False)}"
        response_text = self._generate_with_fallback(
            SYSTEM_PROMPT_TABLE_REFINE,
            prompt,
            model_type="flash",
            json_output=True,
            model_priority_override=MODEL_PRIORITY_CHEAP
        )
        return self._safe_json_load(response_text)

    def generate_flashcards(self, highlighted_text: str, topic: str) -> list:
        """
        Generates Q&A flashcards from user highlights.
        """
        prompt = f"""
        TASK: Create high-yield Flashcards (Q&A) from the following highlighted text.
        TOPIC: {topic}
        
        RULES (CRITICAL):
        1. Output a JSON list of objects calling 'flashcards'.
        2. Format: {{"flashcards": [{{"question_text": "...", "answer_text": "..."}}]}}
        3. **NO ABBREVIATIONS:** Do not use abbreviations. Expand to full Turkish medical terms.
        4. **SHORT Q/A:** Use short, single-sentence questions and answers.
           - Aim for 6-14 words per sentence.
           - If the highlight contains multiple facts, split into multiple flashcards.
        5. **NAMED ENTITIES PRIORITY:** If highlights include named entities (genes, drugs, syndromes, specific pathologies, appearances, clinical signs, adverse effects), make them the focus.
           - Use one named entity per card.
           - Ask for a specific attribute/mechanism/feature or ask for the name given a feature.
           - **COMPARISON EXCEPTION:** If the highlight explicitly compares similar entities, you MAY compare two entities in one card.
        6. **ANSWER LEAKAGE PREVENTION:** The key term or answer MUST NOT appear in the Question Text.
           - Bad: "What is the side effect of Digoxin?" (Too broad)
           - Bad: "Does Digoxin cause arrhythmia?" (Answer leaked)
           - Good: "Which cardiac glycoside causes yellow-green vision changes?" (Target: Digoxin)
        7. **SPECIFICITY:** Avoid generic questions. Target the specific fact in the highlight.
           - Highlight: "Digoksin sodyum-potasyum ATPazı inhibe eder." -> Question: "Digoksinin temel etki mekanizması nedir?" -> Answer: "Sodyum-potasyum ATPaz inhibisyonu."
           - Bad: "What are sides effects of Digoxin?" (Too many answers, not specific)
           - Good: "Furosemid hangi mekanizmayla digoksin toksisitesini artırır?" (Specific mechanism)
        8. **HINT REQUIREMENT:** If the question has multiple potential answers (e.g. "What is a side effect?"), provide a narrowing HINT in parentheses.
           - Example: "Which gastrointestinal side effect is earliest sign of toxicity? (Hint: Common symptom)"
        9. **CONTEXT:** Focus ONLY on the information explicitly highlighted. Do not hallucinate external facts.
        10. **SELF-CONTAINED (CRITICAL):** The question MUST be 100% understandable and answerable WITHOUT seeing the source text.
           - BAD: "What are the findings associated with the highlighted text?" (User cannot see the text!)
           - BAD: "What does this passage describe?" (Refers to invisible context)
           - GOOD: "Sodyum-potasyum ATPazı inhibe eden ilaç hangisidir?" (Standalone, answerable)
        
        HIGHLIGHTS:
        {highlighted_text}
        """
        
        try:
            response_text = self._generate_with_fallback(
                "You are an expert medical educator.", 
                prompt, 
                model_type="flash", 
                json_output=True
            )
            data = self._safe_json_load(response_text)
            return data.get("flashcards", [])
        except Exception as e:
            print(f"⚠️ Flashcard Generation Failed: {e}")
            return []

    def get_text_embedding(self, text: str) -> list:
        """
        Get semantic embedding for text using text-embedding-004.
        Returns list of floats.
        """
        try:
            # text-embedding-004 is very cheap and fast
            model = "text-embedding-004"
            # Rate limit check (reuse existing if possible or safe call)
            # self._wait_for_rate_limit() # Optional if not spamming
            
            result = self.client.models.embed_content(
                model=model,
                contents=text
            )
            return result.embeddings[0].values
        except Exception as e:
            print(f"⚠️ Embedding failed: {e}")
            return []

    def generate_raw_text(self, prompt: str, model_type: str = "pro", cached_content: str = None, specific_api_key: str = None) -> str:
        """
        Public method to generate raw text from a prompt (no JSON enforcement).
        """
        return self._generate_with_fallback(
            system_instruction="You are a helpful AI assistant.",
            prompt=prompt,
            model_type=model_type,
            json_output=False,
            cached_content=cached_content,
            specific_api_key=specific_api_key
        )



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
          { "text": "...", "context_snippet": "...", "context_meta": { "table": { "title": "...", "row": "...", "column": "..." } } }

        RULES:
        1. Output JSON format: {{"flashcards": [{{"group_id": 1, "question_text": "...", "answer_text": "..."}}]}}
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
            - However, you MUST use the 'source_material' text to understand the context.
            - **TABLES/COMPARISONS**: If the highlights come from a table (e.g. comparing Disease A vs Disease B), look at the `source_material` to identify column headers and row labels.
            - Example Table Logic: If highlight is "Fraksiyonel sodyum atılımı azalmış" for "Prerenal Azotemia", asking "Prerenal azotemide fraksiyonel sodyum atılımı nasıldır?" is perfect. Use source text to confirm which disease column the highlight belongs to.
        8. **ANSWER FORMAT**:
           - Be concise but educational.
           - If relevant, mention the Differentiation/Mechanism briefly.
           - Example: "%1'den küçüktür. (Mekanizma: Tübüler fonksiyon korunmuştur, volümü korumak için sodyum geri emilir)."
        9. **SEQUENCE**: The highlights are ordered sequentially. Use this flow to build logical questions if they form a narrative.
        10. Avoid duplicates. Return at most {max_cards} flashcards total.
        11. If a group lacks enough context even with source_material, SKIP that group.

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
                model_priority_override=["gemini-2.5-flash-lite"]
            )
            data = self._safe_json_load(response_text)
            return data.get("flashcards", [])
        except Exception as e:
            print(f"⚠️ Grouped Flashcard Generation Failed: {e}")
            return []
