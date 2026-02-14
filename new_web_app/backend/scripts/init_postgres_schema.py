#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from typing import Iterable

import psycopg


SCHEMA_STATEMENTS: list[str] = [
    # Core tables
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
        id BIGSERIAL PRIMARY KEY,
        source_material TEXT,
        topic TEXT,
        question_text TEXT NOT NULL,
        options TEXT NOT NULL,
        correct_answer_index INTEGER NOT NULL,
        explanation_data TEXT,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        category TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews (
        question_id BIGINT,
        user_id BIGINT DEFAULT 1,
        ease_factor DOUBLE PRECISION DEFAULT 2.5,
        interval INTEGER DEFAULT 0,
        repetitions INTEGER DEFAULT 0,
        next_review_date TIMESTAMP,
        last_review_date TIMESTAMP,
        last_grade INTEGER,
        flags TEXT DEFAULT '[]',
        PRIMARY KEY (question_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_sessions (
        user_id BIGINT PRIMARY KEY,
        active_page TEXT,
        active_topic TEXT,
        active_mode TEXT,
        current_card_id BIGINT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        active_source TEXT,
        active_category TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_highlights (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        question_id BIGINT,
        text_content TEXT,
        context_type TEXT,
        word_index INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        context_snippet TEXT,
        context_meta TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS question_feedback (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT,
        question_id BIGINT,
        feedback_type TEXT,
        description TEXT,
        resolved INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending',
        admin_note TEXT
    )
    """,
    # Generation / background jobs
    """
    CREATE TABLE IF NOT EXISTS background_jobs (
        id BIGSERIAL PRIMARY KEY,
        type TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        payload TEXT,
        progress INTEGER DEFAULT 0,
        total_items INTEGER DEFAULT 0,
        worker_id TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        generated_count INTEGER DEFAULT 0,
        attempts INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 3
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_logs (
        id BIGSERIAL PRIMARY KEY,
        topic TEXT,
        question_count INTEGER,
        status TEXT,
        questions_generated INTEGER DEFAULT 0,
        log_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_jobs (
        id BIGSERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        source_material TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        questions_generated INTEGER DEFAULT 0,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP
    )
    """,
    # Prompt/difficulty templates
    """
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        sections TEXT NOT NULL,
        is_default INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS difficulty_templates (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        levels TEXT NOT NULL,
        is_default INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS section_favorites (
        id BIGSERIAL PRIMARY KEY,
        section_key TEXT NOT NULL,
        name TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Topic-scoped history + embeddings
    """
    CREATE TABLE IF NOT EXISTS question_topic_links (
        question_id BIGINT NOT NULL,
        source_material TEXT,
        category TEXT,
        topic TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (question_id, topic)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concept_embeddings (
        id BIGSERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        concept_text TEXT NOT NULL,
        embedding_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Content requests/feedback (admin workflows)
    """
    CREATE TABLE IF NOT EXISTS content_requests (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT,
        request_type TEXT,
        content_path TEXT,
        description TEXT,
        target_topic TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content_feedback (
        id BIGSERIAL PRIMARY KEY,
        question_id BIGINT,
        section TEXT,
        selected_text TEXT,
        user_note TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id BIGINT DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    # Explanations (optional extra content)
    """
    CREATE TABLE IF NOT EXISTS visual_explanations (
        question_id BIGINT PRIMARY KEY,
        image_path TEXT,
        prompt TEXT,
        verification_status TEXT DEFAULT 'pending',
        user_feedback TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_request_note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extended_explanations (
        question_id BIGINT PRIMARY KEY,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verification_status TEXT DEFAULT 'pending',
        user_request_note TEXT
    )
    """,
    # Flashcard support tables
    """
    CREATE TABLE IF NOT EXISTS flashcard_highlight_usage (
        highlight_id BIGINT,
        user_id BIGINT,
        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (highlight_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS flashcard_generation_runs (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP
    )
    """,
    # Indexes (performance)
    "CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions (topic)",
    "CREATE INDEX IF NOT EXISTS idx_questions_category ON questions (source_material, category)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON background_jobs (status)",
    "CREATE INDEX IF NOT EXISTS idx_embeddings_topic ON concept_embeddings (topic)",
    "CREATE INDEX IF NOT EXISTS idx_qtl_scope_topic ON question_topic_links (source_material, category, topic, question_id)",
    "CREATE INDEX IF NOT EXISTS idx_qtl_topic ON question_topic_links (topic, question_id)",
    "CREATE INDEX IF NOT EXISTS idx_qtl_question ON question_topic_links (question_id)",
]


def _run_all(cur, statements: Iterable[str]) -> None:
    for stmt in statements:
        cur.execute(stmt)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Postgres schema for MedQuiz.")
    parser.add_argument(
        "--dsn",
        default=os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL") or "",
        help="Postgres DSN, e.g. postgresql://user:pass@localhost:5432/medquiz",
    )
    args = parser.parse_args()

    dsn = (args.dsn or "").strip()
    if not dsn:
        raise SystemExit("Missing --dsn (or MEDQUIZ_DB_URL/DATABASE_URL).")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            _run_all(cur, SCHEMA_STATEMENTS)
        conn.commit()

    print("✅ Postgres schema initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
