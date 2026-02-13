"""
Flashcards Router

Generates flashcards from user highlights using a single grouped LLM call.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import os
import sys
import logging

from ..database import get_db_connection, safe_json_parse, add_question, ensure_highlight_context_schema
from .auth import get_current_user, require_admin, TokenData

# Import from core (assumes CWD is new_web_app)
try:
    from core.deepseek_client import DeepSeekClient
except ImportError:
    # Fallback for relative import if run differently
    from ...core.deepseek_client import DeepSeekClient

router = APIRouter(prefix="/flashcards", tags=["Flashcards"])

FLASHCARD_SOURCE = "AI Flashcards"
MIN_FLASHCARD_QUESTIONS = 10
MIN_FLASHCARD_CHARS = 150
MAX_FLASHCARD_CARDS = 50
MAX_HIGHLIGHT_LIMIT = 500

logger = logging.getLogger(__name__)

class FlashcardGenerateRequest(BaseModel):
    limit: int = 200
    max_cards: int = MAX_FLASHCARD_CARDS

class FlashcardGenerateResponse(BaseModel):
    created: int
    highlight_count: int
    flashcard_ids: List[int]


def ensure_usage_table(conn) -> None:
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS flashcard_highlight_usage (
            highlight_id INTEGER,
            user_id INTEGER,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (highlight_id, user_id)
        )
    ''')
    conn.commit()

def ensure_generation_table(conn) -> None:
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS flashcard_generation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')
    conn.commit()

def get_unused_highlight_stats(user_id: int) -> Dict[str, int]:
    conn = get_db_connection()
    ensure_usage_table(conn)
    c = conn.cursor()
    c.execute('''
        SELECT COUNT(DISTINCT h.question_id) as question_count,
               COALESCE(SUM(LENGTH(h.text_content)), 0) as total_chars
        FROM user_highlights h
        LEFT JOIN flashcard_highlight_usage u
          ON u.highlight_id = h.id AND u.user_id = ?
        WHERE h.user_id = ? AND u.highlight_id IS NULL AND h.context_type = 'flashcard'
    ''', (user_id, user_id))
    row = c.fetchone()
    conn.close()
    return {
        "question_count": row["question_count"] if row else 0,
        "total_chars": row["total_chars"] if row else 0
    }

def has_active_generation(conn, user_id: int) -> bool:
    ensure_generation_table(conn)
    c = conn.cursor()
    c.execute('''
        SELECT 1 FROM flashcard_generation_runs
        WHERE user_id = ? AND status IN ('pending', 'processing')
        LIMIT 1
    ''', (user_id,))
    return c.fetchone() is not None

def mark_generation_status(conn, run_id: int, status: str) -> None:
    c = conn.cursor()
    c.execute(
        "UPDATE flashcard_generation_runs SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now().isoformat(), run_id)
    )
    conn.commit()

def fetch_highlight_groups(user_id: int, limit: int) -> tuple[list, list]:
    """
    Fetch unused flashcard highlights grouped by question_id.
    
    IMPORTANT: Highlights are ordered by created_at ASC to preserve the user's 
    highlighting order. This is critical for context - when a user highlights 
    table cells, the order they highlighted them provides important context 
    that would be lost if we sorted by word_index instead.
    """
    ensure_highlight_context_schema()
    conn = get_db_connection()
    ensure_usage_table(conn)
    c = conn.cursor()

    # Order by created_at to preserve user's highlighting sequence
    # This is important for tables where index-based ordering loses context
    c.execute('''
        SELECT h.id AS highlight_id,
               h.text_content,
               h.context_type,
               h.word_index,
               h.context_snippet,
               h.context_meta,
               h.question_id,
               h.created_at,
               q.source_material,
               q.category,
               q.topic,
               q.tags,
               q.question_text,
               q.explanation_data
        FROM user_highlights h
        JOIN questions q ON h.question_id = q.id
        LEFT JOIN flashcard_highlight_usage u
          ON u.highlight_id = h.id AND u.user_id = ?
        WHERE h.user_id = ? AND u.highlight_id IS NULL AND h.context_type = 'flashcard'
        ORDER BY h.created_at ASC
        LIMIT ?
    ''', (user_id, user_id, limit))

    rows = c.fetchall()
    conn.close()

    if not rows:
        return [], []

    # Use ordered dict behavior (Python 3.7+) to preserve insertion order
    groups: Dict[int, Dict[str, Any]] = {}
    highlight_ids: List[int] = []

    for row in rows:
        highlight_ids.append(row["highlight_id"])
        # Parse explanation safely to extract text
        expl_data = safe_json_parse(row["explanation_data"], {}) or {}
        # You might want to format the explanation blocks into a readable string
        # For now, let's just dump it or extract text if possible. 
        # A simple dump is often enough for the LLM.
        expl_text = json.dumps(expl_data, ensure_ascii=False)

        # Construct Rich Source Context
        rich_source = f"""
ORIGINAL SOURCE:
{row['source_material']}

---
CONTEXT (QUESTION & EXPLANATION):
Question: {row['question_text']}

Explanation:
{expl_text}
---
"""
        group = groups.setdefault(row["question_id"], {
            "group_id": row["question_id"],
            "source_material": rich_source,
            "category": row["category"],
            "topic": row["topic"],
            "tags": safe_json_parse(row["tags"], []) or [],
            "highlights": [],  # Maintains insertion (creation time) order
        })

        text = (row["text_content"] or "").strip()
        if text:
            highlight_item = {
                "text": text,
                "context_type": row["context_type"],
                "word_index": row["word_index"],
                "context_snippet": (row["context_snippet"] or "").strip() or None,
                "context_meta": safe_json_parse(row["context_meta"], {}) if row["context_meta"] else None,
            }
            # Append in creation order, not word_index order
            group["highlights"].append(highlight_item)

    # Convert to list preserving group order (first highlight's creation time)
    groups_list = []
    for group in groups.values():
        groups_list.append(group)

    return groups_list, highlight_ids


def build_explanation(answer_text: str) -> dict:
    return {
        "blocks": [
            {"type": "heading", "level": 1, "text": "Cevap"},
            {"type": "callout", "title": "Cevap", "items": [{"text": answer_text}]}
        ]
    }


def merge_tags(base_tags: list, extra_tags: list) -> list:
    combined = []
    seen = set()
    for tag in base_tags + extra_tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        combined.append(tag)
    return combined

def run_flashcard_generation(user_id: int, limit: int, max_cards: int) -> FlashcardGenerateResponse:
    stats = get_unused_highlight_stats(user_id)
    if stats["question_count"] < MIN_FLASHCARD_QUESTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Highlights not enough: {stats['question_count']} questions"
        )

    groups, highlight_ids = fetch_highlight_groups(user_id, limit)
    if not groups:
        raise HTTPException(status_code=400, detail="No unused highlights found")

    try:
        client = DeepSeekClient()
    except Exception as exc:
        logger.error("Flashcard generation client init failed: %s", exc)
        raise HTTPException(status_code=500, detail="DeepSeek client is not configured.")

    cards = client.generate_flashcards_grouped(groups, max_cards=max_cards)
    if not cards:
        return FlashcardGenerateResponse(
            created=0,
            highlight_count=0,
            flashcard_ids=[],
        )

    group_map = {g["group_id"]: g for g in groups}
    created_ids: List[int] = []

    for card in cards:
        group_id = card.get("group_id")
        question_text = (card.get("question_text") or "").strip()
        answer_text = (card.get("answer_text") or "").strip()
        if not group_id or not question_text or not answer_text:
            continue

        group = group_map.get(group_id)
        if not group:
            continue

        extra_tags = [
            "flashcard",
            "ai_generated",
            f"origin_source:{group.get('source_material')}",
            f"origin_category:{group.get('category')}",
            f"origin_topic:{group.get('topic')}",
            f"origin_question_id:{group_id}",
        ]
        tags = merge_tags(group.get("tags", []), extra_tags)

        q_data = {
            "source_material": FLASHCARD_SOURCE,
            "category": group.get("category"),
            "topic": group.get("topic"),
            "question_text": question_text,
            "options": [],
            "correct_answer_index": 0,
            "explanation_data": build_explanation(answer_text),
            "tags": tags,
        }

        qid = add_question(q_data)
        if qid:
            created_ids.append(qid)

    if created_ids:
        conn = get_db_connection()
        ensure_usage_table(conn)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.executemany(
            "INSERT OR IGNORE INTO flashcard_highlight_usage (highlight_id, user_id, used_at) VALUES (?, ?, ?)",
            [(hid, user_id, now) for hid in highlight_ids],
        )
        conn.commit()
        conn.close()

    return FlashcardGenerateResponse(
        created=len(created_ids),
        highlight_count=len(highlight_ids),
        flashcard_ids=created_ids,
    )

def maybe_trigger_flashcard_generation(user_id: int) -> None:
    try:
        stats = get_unused_highlight_stats(user_id)
        if stats["question_count"] < MIN_FLASHCARD_QUESTIONS:
            return

        conn = get_db_connection()
        if has_active_generation(conn, user_id):
            conn.close()
            return
        ensure_generation_table(conn)
        c = conn.cursor()
        c.execute(
            "INSERT INTO flashcard_generation_runs (user_id, status, created_at) VALUES (?, ?, ?)",
            (user_id, "processing", datetime.now().isoformat())
        )
        run_id = c.lastrowid
        conn.commit()
        conn.close()

        try:
            run_flashcard_generation(user_id, limit=MAX_HIGHLIGHT_LIMIT, max_cards=MAX_FLASHCARD_CARDS)
            conn = get_db_connection()
            mark_generation_status(conn, run_id, "completed")
            conn.close()
        except Exception as exc:
            logger.error("Auto flashcard generation failed: %s", exc)
            conn = get_db_connection()
            mark_generation_status(conn, run_id, "failed")
            conn.close()
    except Exception as exc:
        logger.error("Auto flashcard trigger error: %s", exc)


@router.post("/generate", response_model=FlashcardGenerateResponse)
async def generate_flashcards(
    data: FlashcardGenerateRequest,
    current_user: TokenData = Depends(require_admin)
):
    limit = max(1, min(data.limit, MAX_HIGHLIGHT_LIMIT))
    max_cards = max(1, min(data.max_cards, MAX_FLASHCARD_CARDS))
    return run_flashcard_generation(current_user.user_id, limit, max_cards)
