# tusabi.store Sistem Mimarisi (Gercek Durum)

Bu dokuman, repo icindeki kodun **mevcut** halini "source of truth" kabul eder. Hedef/plan degil; gercekte calisan akislar ve sorumluluklar anlatilir.

## 1) Yuksek Seviye

```text
           Browser
             |
             v
  Next.js (new_web_app/frontend)
   - UI + auth token (localStorage)
   - /api/* -> rewrite -> FastAPI
             |
             v
 FastAPI (new_web_app/backend)
   - Quiz API (spaced repetition)
   - Library/PDF manifests (processed_pdfs)
   - Admin generation API (queue)
   - Highlights + Flashcards
   - Startup'ta JobWorker thread'i
             |
             v
 Database (Postgres tercih, SQLite fallback)
   - MEDQUIZ_DB_URL/DATABASE_URL = postgres DSN ise Postgres
   - degilse shared/data/quiz_v2.db (SQLite)

Shared Content (shared/)
 - processed_pdfs/: manifest.json + PDF parcasi meta
 - data/: medquiz_library.json, merged_topic_groups.json, quiz_v2.db (SQLite ise)
```

## 2) Repo Dizinleri (Onemli)

```text
medical_quiz_app/
  new_web_app/
    backend/                 FastAPI uygulamasi
      main.py                Router kayitlari + job worker startup/shutdown
      database.py            DB secimi (postgres/sqlite) + query helper'lari
      db_compat.py           Postgres icin sqlite-benzeri uyumluluk (qmark params vb.)
      job_worker.py          background_jobs kuyruk iscisi (tek thread)
      routers/               HTTP API: quiz, library, pdfs, admin, auth, highlights, flashcards
      scripts/               Postgres schema init/migration + audit/cleanup scriptleri
    frontend/                Next.js uygulamasi (App Router)
      next.config.ts         /api rewrite -> http://localhost:8000
      app/dashboard/page.tsx Quiz + generation UI
      lib/api.ts             fetch helper (genellikle /api ile backend'e gider)
    core/                    LLM + generation motoru
      background_jobs.py      generation_batch job processor (merge + history + save)
      bulk_generator.py       LLM prompt + parse + PDF cache akisi
      generation_engine.py    generation orchestration/dedup/saving
      *client.py              Gemini/DeepSeek/OpenAI clientleri
  shared/
    processed_pdfs/           Ders/kategori/topic PDF manifestleri + dosya pathleri
    data/                     library json + db dosyasi (sqlite) + merged_topic_groups.json
```

## 3) Database Mimarisi (Postgres <-> SQLite Uyum)

### Engine secimi
`new_web_app/backend/database.py`:
- `MEDQUIZ_DB_URL` veya `DATABASE_URL` bir Postgres DSN ise Postgres kullanilir.
- Aksi halde SQLite (`shared/data/quiz_v2.db`) kullanilir.

Bu sayede quiz ve generation ayni kod yolunu kullanir; sadece connection degisir.

### Temel tablolar (pratik ozet)
- `questions`: soru bankasi (source_material, category, topic, question_text, options, explanation_data, tags, created_at, ...)
- `users`: login ve rol (`user` / `admin`)
- `reviews`: spaced repetition state (question_id, user_id, interval, repetitions, next_review_date, flags, ...)
- `user_sessions`: dashboard state (active_topic/source/category/mode + current_card_id)
- `user_highlights`: highlight verisi (question_id, user_id, text_content, context_snippet/context_meta, ...)
- `background_jobs`: generation kuyru gu (payload json, status, attempts, worker_id, error_message)
- `question_topic_links`: history scope icin question <-> topic iliskisi (prompt token tasarrufu icin)
- `question_feedback`, `content_feedback`, `extended_explanations`, `visual_explanations`: kalite/icerik feedback ekleri
- `flashcard_highlight_usage`: highlight'in flashcard uretiminde kullanildigi kaydi

### "Orphan" politikasI
Kural: **Soru yoksa, bagli highlight/feedback/review vb. kalmamali.**

Bu repo'da bunun iki ayagi var:
1. Temizlik araci: `new_web_app/backend/scripts/cleanup_orphans.py`
2. Postgres FK hijyeni: `new_web_app/backend/scripts/init_postgres_schema.py` icinde idempotent FK constraint'ler
   - Ornek: `user_highlights.question_id -> questions.id ON DELETE CASCADE`
   - `user_sessions.current_card_id -> questions.id ON DELETE SET NULL`

## 4) Ana Akislar

### A) Quiz / Spaced Repetition
1. Frontend `new_web_app/frontend/app/dashboard/page.tsx` -> `GET /quiz/next`
2. Backend `new_web_app/backend/routers/quiz.py` -> `database.get_next_card(...)`
3. Kullanici cevap verir -> `POST /quiz/submit`
4. `reviews` tablosu update olur (interval/next_review_date/flags vb.)

Notlar:
- `mode=latest` sadece admin icin (son eklenen sorulara bakma modu).
- Token yoksa backend "guest" gibi davranip default user (genelde `1`) ile devam edebilir.

### B) Kutuphane / PDF Taxonomy
- UI generation icin `GET /pdfs/manifests` (processed_pdfs altindaki manifest.json'lari okur)
- Kutuphane/quiz listesi icin `GET /library/structure` (medquiz_library.json tabanli)
- `/pdfs/manifests` ayrica DB'den soru sayilarini cekip UI'da "kac soru var" bilgisini senkron gosterir.

### C) Soru Uretimi (Admin Queue + Worker)
1. Admin UI -> `POST /admin/generate`
2. Backend `background_jobs` tablosuna `generation_batch` job'u `pending` olarak yazar
3. `new_web_app/backend/job_worker.py` startup'ta calisir:
   - Postgres'te `FOR UPDATE SKIP LOCKED` ile job claim eder
   - SQLite'da `BEGIN IMMEDIATE` ile lock alir
4. Job calisma:
   - `new_web_app/core/background_jobs.py::process_generation_batch_job`
   - Gerekirse birden fazla PDF'i arkaplanda merge eder (`temp_merges/`)
   - History scope:
     - Varsayilan: topic-scoped (chunk'taki `all_topics` + `question_topic_links`)
     - Bulamazsa category fallback
   - `new_web_app/core/bulk_generator.py` LLM prompt kurar + PDF cache kullanir
   - Uretilen sorular DB'ye yazilir, `question_topic_links` guncellenir

### D) Flashcard Uretimi (Highlights -> LLM)
- `POST /flashcards/generate` benzeri endpointler (router: `new_web_app/backend/routers/flashcards.py`)
- Input: kullanicinin `context_type='flashcard'` highlight'lari
- Model: DeepSeek (API key env ile)
- Output: `questions` tablosuna "AI Flashcards" kaynakli kartlar + `flashcard_highlight_usage` kaydi

## 5) Calistirma / Deploy

Yerel (dev):
- `./start_all.sh` (Next dev + FastAPI uvicorn, loglari root'a yazar)
- `./stop_all.sh`

Custom domain (quiz.tusabi.store) keep-alive:
- `./scripts/keep_alive_custom.sh` (backend + frontend build/start + cloudflared tunnel)

Postgres (opsiyonel ama multi-user icin onerilen):
- `docker compose -f docker-compose.postgres.yml up -d`
- DSN env: `MEDQUIZ_DB_URL=postgresql://medquiz:medquiz@localhost:5432/medquiz`

## 6) Degisiklik Yaparken Altin Kurallar

- Generation pipeline'ini bozmamak icin:
  - `background_jobs` payload semasini ve `process_generation_batch_job` akisini koru.
  - `processed_pdfs` taxonomy path'lerini degistiriyorsan, `/pdfs/manifests` ve `helpers.find_pdf_for_topic` etkilenir.
- DB degisiklikleri:
  - Postgres schema icin tek giris noktasi: `new_web_app/backend/scripts/init_postgres_schema.py`
  - Orphan kontrolu: `new_web_app/backend/scripts/cleanup_orphans.py` (dry-run varsayilan)
