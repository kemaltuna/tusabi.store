#!/usr/bin/env python3
"""
Queue question generation jobs according to TUS distribution ratios.

This script reuses the same API endpoints used by the admin UI:
- /admin/generate
- /admin/auto-chunk-generate

Behavior:
- Computes target per mapped segment according to distribution weights.
- Subtracts existing question counts.
- Queues only the missing counts.
- Uses 8 questions per job.
- For segments with <= 20 pages: queues direct category generation.
- For segments with > 20 pages and available sub-segments: queues auto-chunk jobs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import requests


REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = REPO_ROOT / "shared" / "data" / "quiz_v2.db"
REPORTS_DIR = REPO_ROOT / "reports"


@dataclass(frozen=True)
class DistItem:
    source: str
    topic: str
    weight: int
    segments: tuple[str, ...]
    inferred: bool = False


# Some mappings are necessarily approximate due library taxonomy differences.
DISTRIBUTION_ITEMS: tuple[DistItem, ...] = (
    # 1) Anatomi
    DistItem("Anatomi", "Kemikler", 61, ("Kemikler",)),
    DistItem("Anatomi", "Eklemler", 22, ("Eklemler",)),
    DistItem("Anatomi", "Kaslar", 118, ("Kaslar",)),
    DistItem("Anatomi", "Ürogenital Sistem", 28, ("Ürogenital Sistem Anatomisi",), True),
    DistItem("Anatomi", "Gastrointestinal Sistem", 70, ("Sindirim Sistemi Anatomisi",), True),
    DistItem("Anatomi", "Solunum Sistemi", 34, ("Solunum Sistemi Anatomisi",), True),
    DistItem("Anatomi", "Dolaşım Sistemi", 84, ("Dolaşım Sistemi Anatomisi",), True),
    DistItem("Anatomi", "Nöroanatomi", 203, ("Sinir Sistemi Anatomisi",), True),
    # 2) Fizyoloji
    DistItem("Fizyoloji", "Hücre", 49, ("HÜCRE HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Kaslar", 48, ("KAS DOKUSU HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Kardiyovasküler Sistem", 75, ("KARDİYOVASKÜLER SİSTEM HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Üriner Sistem", 39, ("ÜRİNER SİSTEM HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Hemopoetik Sistem", 58, ("HEMATOPOETİK SİSTEM HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Solunum Sistemi", 54, ("SOLUNUM SİSTEMİ HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Doku", 70, ("DOKU HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Sinir Sistemi", 121, ("SANTRAL SİNİR SİSTEMİ HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Gastrointestinal Sistem", 57, ("GASTROİNTESTİNAL SİSTEM HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Endokrin Sistem", 77, ("ENDOKRİN SİSTEM HİSTOLOJİSİ",), True),
    DistItem("Fizyoloji", "Embriyoloji", 65, ("GENEL EMBRİYOLOJİ",), True),
    DistItem("Fizyoloji", "Genital Sistem", 34, ("GENİTAL SİSTEM HİSTOLOJİSİ",), True),
    # 3) Biyokimya
    DistItem("Biyokimya", "Karbonhidratlar", 197, ("Karbonhidratlar",)),
    DistItem("Biyokimya", "Lipitler", 183, ("Lipit Metabolizması",), True),
    DistItem("Biyokimya", "Aminoasitler ve Proteinler", 268, ("Amino Asitler ve Proteinler",), True),
    DistItem("Biyokimya", "Klinik Tanıda Biyokimyasal Testler", 78, ("KLİNİK BİYOKİMYA",), True),
    DistItem("Biyokimya", "DNA, RNA ve Protein Sentezi", 123, ("Nükleik Asitler",), True),
    DistItem("Biyokimya", "Metabolizma", 136, ("Metabolizmanın Temel Kavramları", "Hormon Metabolizması"), True),
    DistItem("Biyokimya", "Hücre ve Organeller", 64, ("Hücre ve Organeller",)),
    DistItem("Biyokimya", "Vitaminler", 93, ("Vitaminler",)),
    # 4) Mikrobiyoloji
    DistItem("Mikrobiyoloji", "Genel Mikrobiyoloji", 122, ("Temel Bakteriyoloji",), True),
    DistItem("Mikrobiyoloji", "İmmünoloji", 157, ("İmmünoloji",)),
    DistItem("Mikrobiyoloji", "Bakteriyoloji", 362, ("Klinik Bakteriyoloji",), True),
    DistItem("Mikrobiyoloji", "Viroloji", 229, ("Viroloji",)),
    DistItem("Mikrobiyoloji", "Mikoloji", 157, ("Mikoloji",)),
    DistItem("Mikrobiyoloji", "Parazitoloji", 123, ("Parazitoloji",)),
    # 5) Patoloji
    DistItem("Patoloji", "Hücre", 74, ("HÜCRE PATOLOJİSİ",)),
    DistItem("Patoloji", "İnflamasyon", 37, ("İNFLAMASYON",)),
    DistItem("Patoloji", "Onarım ve Yara İyileşmesi", 20, ("ONARIM VE REJENERASYON",), True),
    DistItem("Patoloji", "Hemodinamik Hastalıklar", 30, ("HEMODİNAMİK HASTALIKLAR",)),
    DistItem("Patoloji", "İmmun Sistem", 62, ("İMMÜN SİSTEM HASTALIKLARI",), True),
    DistItem("Patoloji", "Neoplazi", 62, ("NEOPLAZİ",)),
    DistItem("Patoloji", "Genetik ve Pediatrik Hastalıklar", 23, ("GENETİK HASTALIKLAR", "ÇOCUKLUK ÇAĞI HASTALIKLARI"), True),
    DistItem("Patoloji", "Çevresel Hastalıklar", 5, ("ÇEVRESEL HASTALIKLAR ve BESLENME",), True),
    DistItem("Patoloji", "Hematopoetik Sistem Hastalıkları", 63, ("HEMATOPOETİK SİSTEM HASTALIKLARI",)),
    DistItem("Patoloji", "Kardiyovasküler Sistem Patolojisi", 61, ("KALP HASTALIKLARI", "DAMAR HASTALIKLARI"), True),
    DistItem("Patoloji", "Solunum Sistemi Patolojisi", 67, ("SOLUNUM SİSTEMİ HASTALIKLARI",)),
    DistItem("Patoloji", "Gastrointestinal Sistem Patolojisi", 90, ("SİNDİRİM SİSTEMİ HASTALIKLARI",), True),
    DistItem("Patoloji", "Karaciğer Patolojileri", 43, ("HEPATOBİLİYER SİSTEM HASTALIKLARI",), True),
    DistItem("Patoloji", "Safra Kesesi Patolojileri", 1, ("HEPATOBİLİYER SİSTEM HASTALIKLARI",), True),
    DistItem("Patoloji", "Pankreas Hastalıkları", 11, ("PANKREAS HASTALIKLARI",)),
    DistItem("Patoloji", "Endokrin Sistem Patolojisi", 55, ("ENDOKRİN SİSTEM HASTALIKLARI",)),
    DistItem("Patoloji", "Meme Hastalıkları", 39, ("MEME HASTALIKLARI",)),
    DistItem("Patoloji", "Kadın Genital Sistemi Patolojisi", 52, ("KADIN GENİTAL SİSTEM",), True),
    DistItem("Patoloji", "Erkek Genital Sistemi Patolojisi", 35, ("ERKEK GENİTAL SİSTEM",), True),
    DistItem("Patoloji", "Üriner Sistem Patolojisi", 62, ("ÜRİNER SİSTEM HASTALIKLARI",)),
    DistItem("Patoloji", "Kas-İskelet Sistemi Patolojisi", 69, ("İSKELET SİSTEMİ HASTALIKLARI",), True),
    DistItem("Patoloji", "Sinir Sistemi Patolojisi", 69, ("SİNİR SİSTEMİ HASTALIKLARI",)),
    DistItem("Patoloji", "Deri Hastalıkları", 41, ("DERİ HASTALIKLARI",)),
    # 6) Farmakoloji
    DistItem("Farmakoloji", "Genel Farmakoloji", 113, ("GENEL FARMAKOLOJİ",)),
    DistItem("Farmakoloji", "Otonom Sinir Sistemi", 100, ("OTONOM SİSTEM İLAÇLARI",), True),
    DistItem("Farmakoloji", "Kardiyovasküler Sistem", 189, ("KARDİYOVASKÜLER SİSTEM FARMAKOLOJİSİ",), True),
    DistItem("Farmakoloji", "Santral Sinir Sistemi", 192, ("SANTRAL SİNİR SİSTEMİ FARMAKOLOJİSİ",), True),
    DistItem("Farmakoloji", "Solunum Sistemi", 22, ("SOLUNUM SİSTEMİ İLAÇLARI",), True),
    DistItem("Farmakoloji", "Gastrointestinal Sistem", 53, ("GASTROİNTESTİNAL SİSTEM FARMAKOLOJİSİ",), True),
    DistItem("Farmakoloji", "Endokrin Sistem", 115, ("ENDOKRİN SİSTEM FARMAKOLOJİSİ",), True),
    DistItem("Farmakoloji", "Otakoidler", 66, ("OTAKOİDLER",)),
    DistItem("Farmakoloji", "Kemoterapötikler", 191, ("ANTİMİKROBİYAL İLAÇLAR", "ANTİNEOPLASTİK İLAÇLAR", "İMMÜNMODÜLATÖR İLAÇLAR"), True),
    DistItem("Farmakoloji", "Toksikoloji", 31, ("TOKSİKOLOJİ",)),
    # 7) Dahiliye
    DistItem("Dahiliye", "Kardiyoloji", 155, ("Kardiyoloji",)),
    DistItem("Dahiliye", "Göğüs Hastalıkları", 147, ("Göğüs Hastalıkları",)),
    DistItem("Dahiliye", "Nefroloji", 122, ("Nefroloji",)),
    DistItem("Dahiliye", "Gastroenteroloji", 80, ("Gastroenteroloji",)),
    DistItem("Dahiliye", "Hepatoloji", 97, ("Hepatoloji",)),
    DistItem("Dahiliye", "Hematoloji", 138, ("Hematoloji",)),
    DistItem("Dahiliye", "Onkoloji", 55, ("Onkoloji",)),
    DistItem("Dahiliye", "Endokrinoloji", 145, ("Endokrinoloji",)),
    DistItem("Dahiliye", "Romatoloji", 90, ("Romatoloji",)),
    DistItem("Dahiliye", "Geriatri", 22, ("Geriatri",)),
    DistItem("Dahiliye", "Enfeksiyon Hastalıkları", 172, ("Göğüs Hastalıkları",), True),
    # 8) Pediatri
    DistItem("Pediatri", "Büyüme ve Gelişme", 21, ("Büyüme ve Gelişme",)),
    DistItem("Pediatri", "Sosyal Pediatri ve Adölesan Hastalıkları", 22, ("ADÖLESAN",), True),
    DistItem("Pediatri", "Beslenme ve Malnutrisyon", 57, ("Beslenme ve Malnütrisyon",), True),
    DistItem("Pediatri", "Pediatrik Acil, Yoğun Bakım ve Zehirlenmeler", 43, ("ACİL VE YOĞUN BAKIM", "Zehirlenmeler"), True),
    DistItem("Pediatri", "Pediatrik Genetik Hastalıklar", 53, ("Genetik",), True),
    DistItem("Pediatri", "Pediatrik Metabolik Hastalıklar", 84, ("Metabolik Hastalıklar",), True),
    DistItem("Pediatri", "Yenidoğan Hastalıkları", 150, ("Yenidoğan",), True),
    DistItem("Pediatri", "Allerji ve İmmünoloji", 94, ("Pediatrik Alerji-İmmünoloji",), True),
    DistItem("Pediatri", "Pediatrik Romatoloji", 59, ("Pediatrik Romatoloji",)),
    DistItem("Pediatri", "Pediatrik Gastroenteroloji", 112, ("Pediatrik Gastroenteroloji",)),
    DistItem("Pediatri", "Pediatrik Göğüs Hastalıkları", 90, ("Pediatrik Göğüs Hastalıkları",)),
    DistItem("Pediatri", "Döküntülü Hastalıklar ve Bağışıklama", 83, ("Döküntülü Hastalıklar ve Bağışıklama",)),
    DistItem("Pediatri", "Pediatrik Kardiyoloji", 113, ("Pediatrik Kardiyoloji",)),
    DistItem("Pediatri", "Pediatrik Hematoloji", 132, ("Pediatrik Hematoloji",)),
    DistItem("Pediatri", "Pediatrik Onkoloji", 78, ("Pediatrik Onkoloji",)),
    DistItem("Pediatri", "Pediatrik Nefroloji ve Üriner Hastalıklar", 92, ("Pediatrik Nefroloji",), True),
    DistItem("Pediatri", "Pediatrik Endokrinoloji", 90, ("Pediatrik Endokrinoloji",)),
    DistItem("Pediatri", "Pediatrik Nöroloji", 87, ("Pediatrik Nöroloji",)),
    # 9) Genel Cerrahi
    DistItem("Genel_Cerrahi", "Sıvı, Elektrolit ve Asit Baz Dengesi", 75, ("SIVI ELEKTROLİT",), True),
    DistItem("Genel_Cerrahi", "Şok", 46, ("ŞOK",)),
    DistItem("Genel_Cerrahi", "Beslenme", 20, ("BESLENME",)),
    DistItem("Genel_Cerrahi", "Yara İyileşmesi", 18, ("YARA İYİLEŞMESİ",)),
    DistItem("Genel_Cerrahi", "Cerrahi Enfeksiyonlar ve Komplikasyonlar", 51, ("CERRAHİ ENFEKSİYONLAR", "CERRAHİ KOMPLİKASYONLAR"), True),
    DistItem("Genel_Cerrahi", "Travmaya Sistemik Cevap", 30, ("TRAVMA CEVABI VE DESTEK",), True),
    DistItem("Genel_Cerrahi", "Travma ve Travma Hastasına Yaklaşım", 50, ("TRAVMA",), True),
    DistItem("Genel_Cerrahi", "Yanık", 14, ("YANIK",)),
    DistItem("Genel_Cerrahi", "Hemostaz ve Transfüzyon", 30, ("HEMOSTAZ VE TRANSFÜZYON",)),
    DistItem("Genel_Cerrahi", "Transplantasyon", 23, ("TRANSPLANTASYON",)),
    DistItem("Genel_Cerrahi", "Meme Hastalıkları ve Cerrahisi", 95, ("MEME HASTALIKLARI VE CERRAHİSİ",)),
    DistItem("Genel_Cerrahi", "Tiroid Hastalıkları ve Cerrahisi", 66, ("TİROİD HASTALIKLARI VE CERRAHİSİ",), True),
    DistItem("Genel_Cerrahi", "Paratiroid Bezi Hastalıkları ve Cerrahisi", 17, ("PARATİROİD CERRAHİSİ",), True),
    DistItem("Genel_Cerrahi", "Adrenal Bez Hastalıkları ve Cerrahisi", 15, ("ADRENAL",), True),
    DistItem("Genel_Cerrahi", "Özofagus Hastalıkları", 47, ("ÖZOFAGUS HASTALIKLARI",)),
    DistItem("Genel_Cerrahi", "Karın Duvarı, Umbilikus, Periton, Mezenter, Omentum ve Retroperiton Hastalıkları", 22, ("PERİTON VE MEZENTER",), True),
    DistItem("Genel_Cerrahi", "Akut Karın ve Gastrointestinal Sistem Kanamaları", 31, ("AKUT KARIN", "GASTROİNTESTİNAL SİSTEM KANAMALARI"), True),
    DistItem("Genel_Cerrahi", "Karın Duvarı Fıtıkları", 27, ("KARIN DUVARI FITIKLARI",), True),
    DistItem("Genel_Cerrahi", "İntestinal Obstrüksiyon", 13, ("İNTESTİNAL TIKANIKLIKLAR",), True),
    DistItem("Genel_Cerrahi", "Gastrointestinal Sistem Fistülleri", 8, ("GİS FİSTÜLLERİ",), True),
    DistItem("Genel_Cerrahi", "Morbid Obezite", 10, ("MORBİD OBEZİTE",)),
    DistItem("Genel_Cerrahi", "Mide Hastalıkları", 48, ("MİDE HASTALIKLARI",)),
    DistItem("Genel_Cerrahi", "İnce Bağırsak Hastalıkları", 29, ("İNCE BAĞIRSAK HASTALIKLARI",)),
    DistItem("Genel_Cerrahi", "Apendiks Hastalıkları", 20, ("APENDİKS VERMİFORMİS HASTALIKLARI",), True),
    DistItem("Genel_Cerrahi", "Kalın Bağırsak ve Rektum Hastalıkları", 80, ("KOLON VE REKTUM HASTALIKLARI",), True),
    DistItem("Genel_Cerrahi", "Perianal Bölge Hastalıkları", 23, ("PERİANAL BÖLGE HASTALIKLARI",), True),
    DistItem("Genel_Cerrahi", "Karaciğer Hastalıkları", 55, ("KARACİĞER HASTALIKLARI", "PORTAL HİPERTANSİYON"), True),
    DistItem("Genel_Cerrahi", "Safra Kesesi ve Safra Yolları Hastalıkları", 55, ("SAFRA YOLLARI",), True),
    DistItem("Genel_Cerrahi", "Pankreas Hastalıkları", 71, ("PANKREAS HASTALIKLARI",)),
    DistItem("Genel_Cerrahi", "Dalak Hastalıkları", 30, ("DALAK HASTALIKLARI",)),
    DistItem("Genel_Cerrahi", "Cerrahi Vasküler Hastalıklar", 13, ("MEZENTERİK VASKÜLER HASTALIKLAR",), True),
    # 10) Küçük Stajlar
    DistItem("Kucuk_Stajlar", "Nöroloji", 133, ("Nöroloji",)),
    DistItem("Kucuk_Stajlar", "Beyin Cerrahisi", 51, ("Beyin Cerrahisi",)),
    DistItem("Kucuk_Stajlar", "Psikiyatri", 85, ("Psikiyatri",)),
    DistItem("Kucuk_Stajlar", "Göz Hastalıkları", 36, ("Göz Hastalıkları",)),
    DistItem("Kucuk_Stajlar", "Dermatoloji", 91, ("Dermatoloji",)),
    DistItem("Kucuk_Stajlar", "Kulak Burun ve Boğaz Hastalıkları", 46, ("Kulak-Burun-Boğaz Hastalıkları",), True),
    DistItem("Kucuk_Stajlar", "Radyoloji", 69, ("Radyoloji ve Nükleer Tıp",), True),
    DistItem("Kucuk_Stajlar", "Nükleer Tıp", 17, ("Radyoloji ve Nükleer Tıp",), True),
    DistItem("Kucuk_Stajlar", "Halk Sağlığı", 72, ("Halk Sağlığı",)),
    DistItem("Kucuk_Stajlar", "Üroloji", 38, ("Üroloji",)),
    DistItem("Kucuk_Stajlar", "Ortopedi", 48, ("Ortopedi",)),
    DistItem("Kucuk_Stajlar", "Fiziksel Tıp ve Rehabilitasyon", 50, ("Fizik Tedavi ve Rehabilitasyon",), True),
    DistItem("Kucuk_Stajlar", "Kalp ve Damar Cerrahisi", 41, ("KVC VE GÖC",), True),
    DistItem("Kucuk_Stajlar", "Göğüs Cerrahisi", 25, ("KVC VE GÖC",), True),
    DistItem("Kucuk_Stajlar", "Çocuk Cerrahisi", 40, ("Çocuk Cerrahisi",)),
    DistItem("Kucuk_Stajlar", "Anestezi", 52, ("Anestezi",)),
    DistItem("Kucuk_Stajlar", "Plastik Cerrahi", 15, ("Plastik ve Rekonstrüktif Cerrahisi",), True),
    DistItem("Kucuk_Stajlar", "Acil Tıp", 29, ("Anestezi",), True),
    # 11) Kadın Doğum
    DistItem("Kadin_Dogum", "Obstetri", 247, ("Obstetri",)),
    DistItem("Kadin_Dogum", "Endokrinoloji", 124, ("Jinekoloji ve Üreme Endokrinolojisi",), True),
    DistItem("Kadin_Dogum", "Jinekoloji", 184, ("Jinekoloji ve Üreme Endokrinolojisi",), True),
    DistItem("Kadin_Dogum", "Onkoloji", 105, ("Jinekolojik Onkoloji",), True),
)


@dataclass
class SegmentPlan:
    source: str
    segment_title: str
    deficit: int
    target: int
    current: int
    page_count: int
    chunk_count: int
    direct_rounds: int
    chunk_multiplier_rounds: int
    chunk_target_pages: int | None
    chunk_page_sizes: list[int]
    inferred_topics: list[str]
    mapped_topics: list[str]
    sub_segments: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue TUS-distribution generation jobs.")
    parser.add_argument("--api-base", default=os.getenv("MEDQUIZ_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--jwt-secret", default=os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production"))
    parser.add_argument("--admin-user-id", type=int, default=1)
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--difficulty", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--page-threshold", type=int, default=20)
    parser.add_argument("--target-pages", type=int, default=20)
    parser.add_argument(
        "--auto-target-pages",
        default="10,15,20",
        help="Comma separated chunk targets tried for homogeneity (e.g. 10,15,20).",
    )
    parser.add_argument("--max-multiplier-per-call", type=int, default=6)
    parser.add_argument("--min-total", type=int, default=20008)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=80)
    parser.add_argument("--max-requests", type=int, default=0, help="Optional hard stop for request count.")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--report-path", default="")
    return parser.parse_args()


def make_admin_token(secret: str, user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def get_existing_total_questions(db_path: Path) -> int:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM questions")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def fetch_manifest_subjects(api_base: str) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/pdfs/manifests"
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    payload = resp.json()
    subjects = payload.get("subjects", {})
    if not isinstance(subjects, dict):
        raise RuntimeError("Invalid /pdfs/manifests payload")
    return subjects


def compute_chunks(sub_segments: list[dict[str, Any]], target: int = 20) -> list[list[dict[str, Any]]]:
    if not sub_segments:
        return []

    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_pages = 0

    for seg in sub_segments:
        page_count = int(seg.get("page_count", 0) or 0)
        new_total = current_pages + page_count

        if not current_chunk:
            current_chunk = [seg]
            current_pages = new_total
            continue

        dist_with = abs(new_total - target)
        dist_without = abs(current_pages - target)

        if dist_with <= dist_without:
            current_chunk.append(seg)
            current_pages = new_total
        else:
            chunks.append(current_chunk)
            current_chunk = [seg]
            current_pages = page_count

    if current_chunk:
        chunks.append(current_chunk)

    min_last_chunk_pages = 9
    while len(chunks) > 1:
        last_chunk = chunks[-1]
        last_pages = sum(int(item.get("page_count", 0) or 0) for item in last_chunk)
        if last_pages >= min_last_chunk_pages:
            break

        prev_chunk = chunks[-2]
        if not prev_chunk:
            break

        moved = prev_chunk.pop()
        last_chunk.insert(0, moved)
        if not prev_chunk:
            chunks.pop(-2)

    return chunks


def _chunk_page_sizes(chunks: list[list[dict[str, Any]]]) -> list[int]:
    return [sum(int(item.get("page_count", 0) or 0) for item in chunk) for chunk in chunks]


def _chunk_score(chunks: list[list[dict[str, Any]]]) -> tuple[float, float, int]:
    if not chunks:
        return (1e9, 1e9, 1_000_000)
    sizes = _chunk_page_sizes(chunks)
    spread = float(max(sizes) - min(sizes))
    mean = sum(sizes) / len(sizes)
    variance = sum((x - mean) ** 2 for x in sizes) / len(sizes)
    stdev = math.sqrt(variance)
    # Prioritize homogeneous chunk sizes; tie-break by fewer chunks.
    return (spread, stdev, len(chunks))


def choose_best_target_pages(
    sub_segments: list[dict[str, Any]],
    candidates: list[int],
    fallback_target: int,
) -> tuple[int, list[list[dict[str, Any]]]]:
    valid_candidates = [c for c in candidates if c > 0]
    if not valid_candidates:
        valid_candidates = [fallback_target]

    best_target = valid_candidates[0]
    best_chunks = compute_chunks(sub_segments, best_target)
    best_score = _chunk_score(best_chunks)

    for candidate in valid_candidates[1:]:
        chunks = compute_chunks(sub_segments, candidate)
        score = _chunk_score(chunks)
        if score < best_score:
            best_target = candidate
            best_chunks = chunks
            best_score = score

    return best_target, best_chunks


def allocate_integer_targets(weight_by_segment: dict[tuple[str, str], float], total_target: int) -> dict[tuple[str, str], int]:
    total_weight = sum(weight_by_segment.values())
    if total_weight <= 0:
        raise RuntimeError("Total distribution weight is zero.")

    raw = {k: (v / total_weight) * total_target for k, v in weight_by_segment.items()}
    base = {k: int(value) for k, value in raw.items()}
    remainder = total_target - sum(base.values())
    if remainder > 0:
        keys = sorted(raw.keys(), key=lambda k: (raw[k] - base[k]), reverse=True)
        for key in keys[:remainder]:
            base[key] += 1
    return base


def build_segment_index(subjects: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for source, source_data in subjects.items():
        for volume in source_data.get("volumes", []):
            for segment in volume.get("segments", []):
                title = segment.get("title")
                if title:
                    index[source][title] = segment
    return index


def build_plans(
    segment_index: dict[str, dict[str, dict[str, Any]]],
    min_total: int,
    existing_total: int,
    batch_size: int,
    page_threshold: int,
    target_pages: int,
    auto_target_pages: list[int],
) -> tuple[list[SegmentPlan], dict[str, Any]]:
    unresolved: list[dict[str, str]] = []
    weight_by_segment: dict[tuple[str, str], float] = defaultdict(float)
    segment_topics: dict[tuple[str, str], list[str]] = defaultdict(list)
    inferred_topics: dict[tuple[str, str], list[str]] = defaultdict(list)

    for item in DISTRIBUTION_ITEMS:
        missing_segments = [segment for segment in item.segments if segment not in segment_index.get(item.source, {})]
        if missing_segments:
            unresolved.append(
                {
                    "source": item.source,
                    "topic": item.topic,
                    "missing_segments": ", ".join(missing_segments),
                }
            )
            continue

        part_weight = item.weight / len(item.segments)
        for segment_title in item.segments:
            key = (item.source, segment_title)
            weight_by_segment[key] += part_weight
            segment_topics[key].append(item.topic)
            if item.inferred:
                inferred_topics[key].append(item.topic)

    if unresolved:
        message = "Distribution mapping has unresolved segments:\n" + json.dumps(unresolved, ensure_ascii=False, indent=2)
        raise RuntimeError(message)

    desired_total = max(min_total, existing_total)
    if desired_total % batch_size != 0:
        desired_total += batch_size - (desired_total % batch_size)

    targets = allocate_integer_targets(weight_by_segment, desired_total)
    plans: list[SegmentPlan] = []
    aggregate = {
        "distribution_weight_total": sum(weight_by_segment.values()),
        "existing_total_questions": existing_total,
        "desired_total_questions": desired_total,
        "segments_in_plan": 0,
        "total_deficit": 0,
        "estimated_jobs": 0,
        "inferred_topic_count": 0,
        "chunk_target_usage": {},
    }

    for (source, segment_title), target in targets.items():
        seg = segment_index[source][segment_title]
        current = int(seg.get("question_count", 0) or 0)
        deficit = max(0, target - current)
        if deficit <= 0:
            continue

        sub_segments = seg.get("sub_segments") or []
        has_chunk = int(seg.get("page_count", 0) or 0) > page_threshold and len(sub_segments) > 0
        if has_chunk:
            selected_target_pages, chunks = choose_best_target_pages(
                sub_segments=sub_segments,
                candidates=auto_target_pages,
                fallback_target=target_pages,
            )
            chunk_count = max(1, len(chunks))
            chunk_multiplier_rounds = math.ceil(deficit / (batch_size * chunk_count))
            direct_rounds = 0
            estimated_jobs = chunk_multiplier_rounds * chunk_count
            chunk_page_sizes = _chunk_page_sizes(chunks)
        else:
            chunk_count = 0
            chunk_multiplier_rounds = 0
            direct_rounds = math.ceil(deficit / batch_size)
            estimated_jobs = direct_rounds
            selected_target_pages = None
            chunk_page_sizes = []

        mapped = sorted(set(segment_topics[(source, segment_title)]))
        inferred = sorted(set(inferred_topics[(source, segment_title)]))

        plans.append(
            SegmentPlan(
                source=source,
                segment_title=segment_title,
                deficit=deficit,
                target=target,
                current=current,
                page_count=int(seg.get("page_count", 0) or 0),
                chunk_count=chunk_count,
                direct_rounds=direct_rounds,
                chunk_multiplier_rounds=chunk_multiplier_rounds,
                chunk_target_pages=selected_target_pages,
                chunk_page_sizes=chunk_page_sizes,
                inferred_topics=inferred,
                mapped_topics=mapped,
                sub_segments=sub_segments,
            )
        )

        aggregate["segments_in_plan"] += 1
        aggregate["total_deficit"] += deficit
        aggregate["estimated_jobs"] += estimated_jobs
        aggregate["inferred_topic_count"] += len(inferred)
        if selected_target_pages is not None:
            key = str(selected_target_pages)
            aggregate["chunk_target_usage"][key] = int(aggregate["chunk_target_usage"].get(key, 0)) + 1

    plans.sort(key=lambda p: (p.source, p.segment_title))
    return plans, aggregate


def split_rounds(total_rounds: int, per_call_cap: int) -> list[int]:
    rounds: list[int] = []
    remaining = total_rounds
    while remaining > 0:
        current = min(per_call_cap, remaining)
        rounds.append(current)
        remaining -= current
    return rounds


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=180)
    if not response.ok:
        detail = response.text
        raise RuntimeError(f"{url} -> {response.status_code}: {detail}")
    return response.json()


def queue_jobs(
    api_base: str,
    token: str,
    plans: list[SegmentPlan],
    difficulty: int,
    batch_size: int,
    max_multiplier_per_call: int,
    sleep_ms: int,
    max_requests: int,
    stop_on_error: bool,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    generate_url = f"{api_base.rstrip('/')}/admin/generate"
    auto_chunk_url = f"{api_base.rstrip('/')}/admin/auto-chunk-generate"

    queued_requests = 0
    queued_jobs = 0
    queued_question_capacity = 0
    failed_requests: list[dict[str, Any]] = []
    call_log: list[dict[str, Any]] = []

    for plan in plans:
        if max_requests > 0 and queued_requests >= max_requests:
            break

        if plan.direct_rounds > 0:
            for _ in range(plan.direct_rounds):
                if max_requests > 0 and queued_requests >= max_requests:
                    break
                payload = {
                    "topic": plan.segment_title,
                    "source_material": plan.source,
                    "count": batch_size,
                    "difficulty": difficulty,
                    "all_topics": [plan.segment_title],
                    "main_header": plan.segment_title,
                    "source_pdfs_list": None,
                }
                try:
                    response = post_json(generate_url, headers, payload)
                    queued_requests += 1
                    queued_jobs += 1
                    queued_question_capacity += batch_size
                    call_log.append(
                        {
                            "mode": "generate",
                            "source": plan.source,
                            "segment": plan.segment_title,
                            "response": response,
                        }
                    )
                except Exception as exc:
                    failed = {
                        "mode": "generate",
                        "source": plan.source,
                        "segment": plan.segment_title,
                        "error": str(exc),
                    }
                    failed_requests.append(failed)
                    if stop_on_error:
                        raise
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)

        if plan.chunk_multiplier_rounds > 0:
            multipliers = split_rounds(plan.chunk_multiplier_rounds, max_multiplier_per_call)
            for multiplier in multipliers:
                if max_requests > 0 and queued_requests >= max_requests:
                    break
                payload = {
                    "source_material": plan.source,
                    "segment_title": plan.segment_title,
                    "sub_segments": [
                        {
                            "title": sub.get("title", ""),
                            "file": sub.get("file", ""),
                            "page_count": int(sub.get("page_count", 0) or 0),
                            "source_pdfs_list": sub.get("source_pdfs_list"),
                            "merged_topics": sub.get("merged_topics"),
                        }
                        for sub in plan.sub_segments
                    ],
                    "count": batch_size,
                    "difficulty": difficulty,
                    "multiplier": multiplier,
                    "target_pages": int(plan.chunk_target_pages or 20),
                }
                try:
                    response = post_json(auto_chunk_url, headers, payload)
                    queued_requests += 1
                    queued_jobs += int(response.get("total_jobs", 0) or 0)
                    chunk_count = int(response.get("total_chunks", plan.chunk_count) or plan.chunk_count or 1)
                    queued_question_capacity += batch_size * multiplier * chunk_count
                    call_log.append(
                        {
                            "mode": "auto_chunk",
                            "source": plan.source,
                            "segment": plan.segment_title,
                            "multiplier": multiplier,
                            "response": response,
                        }
                    )
                except Exception as exc:
                    failed = {
                        "mode": "auto_chunk",
                        "source": plan.source,
                        "segment": plan.segment_title,
                        "multiplier": multiplier,
                        "error": str(exc),
                    }
                    failed_requests.append(failed)
                    if stop_on_error:
                        raise
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)

    return {
        "queued_requests": queued_requests,
        "queued_jobs": queued_jobs,
        "queued_question_capacity": queued_question_capacity,
        "failed_request_count": len(failed_requests),
        "failed_requests": failed_requests,
        "call_log": call_log,
    }


def print_plan_summary(plans: list[SegmentPlan], aggregate: dict[str, Any], batch_size: int, max_multiplier_per_call: int) -> None:
    direct_calls = sum(plan.direct_rounds for plan in plans)
    chunk_calls = sum(math.ceil(plan.chunk_multiplier_rounds / max_multiplier_per_call) for plan in plans)
    print(f"Segments in plan: {aggregate['segments_in_plan']}")
    print(f"Existing total questions: {aggregate['existing_total_questions']}")
    print(f"Desired total questions: {aggregate['desired_total_questions']}")
    print(f"Total deficit: {aggregate['total_deficit']}")
    print(f"Estimated jobs: {aggregate['estimated_jobs']}")
    print(f"Estimated API calls: {direct_calls + chunk_calls} (direct={direct_calls}, auto_chunk={chunk_calls})")
    print(f"Inferred topic mappings used: {aggregate['inferred_topic_count']}")
    if aggregate.get("chunk_target_usage"):
        usage = ", ".join(f"{k}s:{v}" for k, v in sorted(aggregate["chunk_target_usage"].items(), key=lambda x: int(x[0])))
        print(f"Chunk target usage: {usage}")
    print("")
    print("Top 20 deficits:")
    ordered = sorted(plans, key=lambda p: p.deficit, reverse=True)
    for plan in ordered[:20]:
        mode = "chunk" if plan.chunk_multiplier_rounds > 0 else "direct"
        unit = (
            f"{plan.chunk_count} chunk @ {plan.chunk_target_pages}s"
            if mode == "chunk"
            else f"{batch_size}/job"
        )
        print(
            f"- {plan.source} / {plan.segment_title}: "
            f"deficit={plan.deficit}, current={plan.current}, target={plan.target}, "
            f"page={plan.page_count}, mode={mode}, unit={unit}"
        )


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1
    if args.batch_size <= 0:
        print("batch-size must be > 0", file=sys.stderr)
        return 1
    if args.max_multiplier_per_call <= 0:
        print("max-multiplier-per-call must be > 0", file=sys.stderr)
        return 1

    try:
        auto_target_pages = [
            int(part.strip())
            for part in args.auto_target_pages.split(",")
            if part.strip()
        ]
    except ValueError:
        print("auto-target-pages must be a comma separated integer list, e.g. 10,15,20", file=sys.stderr)
        return 1
    if not auto_target_pages:
        auto_target_pages = [args.target_pages]

    existing_total = get_existing_total_questions(DB_PATH)
    subjects = fetch_manifest_subjects(args.api_base)
    segment_index = build_segment_index(subjects)
    plans, aggregate = build_plans(
        segment_index=segment_index,
        min_total=args.min_total,
        existing_total=existing_total,
        batch_size=args.batch_size,
        page_threshold=args.page_threshold,
        target_pages=args.target_pages,
        auto_target_pages=auto_target_pages,
    )

    print_plan_summary(
        plans=plans,
        aggregate=aggregate,
        batch_size=args.batch_size,
        max_multiplier_per_call=args.max_multiplier_per_call,
    )

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(args.report_path) if args.report_path else REPORTS_DIR / f"tus_queue_report_{timestamp}.json"

    report: dict[str, Any] = {
        "timestamp": timestamp,
        "params": {
            "api_base": args.api_base,
            "difficulty": args.difficulty,
            "batch_size": args.batch_size,
            "page_threshold": args.page_threshold,
            "target_pages": args.target_pages,
            "auto_target_pages": auto_target_pages,
            "max_multiplier_per_call": args.max_multiplier_per_call,
            "min_total": args.min_total,
            "execute": args.execute,
            "sleep_ms": args.sleep_ms,
            "max_requests": args.max_requests,
        },
        "aggregate": aggregate,
        "segments": [
            {
                "source": plan.source,
                "segment_title": plan.segment_title,
                "deficit": plan.deficit,
                "target": plan.target,
                "current": plan.current,
                "page_count": plan.page_count,
                "chunk_count": plan.chunk_count,
                "direct_rounds": plan.direct_rounds,
                "chunk_multiplier_rounds": plan.chunk_multiplier_rounds,
                "chunk_target_pages": plan.chunk_target_pages,
                "chunk_page_sizes": plan.chunk_page_sizes,
                "mapped_topics": plan.mapped_topics,
                "inferred_topics": plan.inferred_topics,
            }
            for plan in plans
        ],
    }

    if not args.execute:
        report["queued"] = {"skipped": True, "reason": "dry-run"}
        write_report(report_path, report)
        print(f"Dry-run complete. Report: {report_path}")
        return 0

    token = make_admin_token(
        secret=args.jwt_secret,
        user_id=args.admin_user_id,
        username=args.admin_username,
    )
    queue_result = queue_jobs(
        api_base=args.api_base,
        token=token,
        plans=plans,
        difficulty=args.difficulty,
        batch_size=args.batch_size,
        max_multiplier_per_call=args.max_multiplier_per_call,
        sleep_ms=args.sleep_ms,
        max_requests=args.max_requests,
        stop_on_error=args.stop_on_error,
    )
    report["queued"] = queue_result
    write_report(report_path, report)

    print("")
    print("Queue finished.")
    print(f"- queued_requests: {queue_result['queued_requests']}")
    print(f"- queued_jobs: {queue_result['queued_jobs']}")
    print(f"- queued_question_capacity: {queue_result['queued_question_capacity']}")
    print(f"- failed_request_count: {queue_result['failed_request_count']}")
    print(f"- report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
