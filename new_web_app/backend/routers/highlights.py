"""
Highlights Router for FastAPI Backend

Provides:
- POST /highlights - Save a new highlight
- GET /highlights/{question_id} - Get highlights for a question
- DELETE /highlights/{id} - Remove a highlight
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import json

from ..database import get_db_connection, ensure_highlight_context_schema, safe_json_parse
from .auth import get_current_user, TokenData

router = APIRouter(prefix="/highlights", tags=["Highlights"])

class HighlightCreate(BaseModel):
    question_id: int
    text_content: str
    context_type: str = "explanation"  # "question" or "explanation"
    word_index: Optional[int] = None
    context_snippet: Optional[str] = None
    context_meta: Optional[dict] = None

class HighlightResponse(BaseModel):
    id: int
    user_id: int
    question_id: int
    text_content: str
    context_type: str
    word_index: Optional[int]
    created_at: str
    context_snippet: Optional[str] = None
    context_meta: Optional[dict] = None

@router.post("", response_model=HighlightResponse)
async def create_highlight(
    data: HighlightCreate,
    current_user: TokenData = Depends(get_current_user),
    background_tasks: BackgroundTasks = None
):
    """Save a new text highlight for the current user."""
    ensure_highlight_context_schema()
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check for duplicates
    c.execute("""
        SELECT id FROM user_highlights 
        WHERE user_id = ? AND question_id = ? AND context_type = ? AND word_index IS ?
    """, (current_user.user_id, data.question_id, data.context_type, data.word_index))
    
    existing = c.fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Highlight already exists")
    
    # Insert new highlight
    c.execute("""
        INSERT INTO user_highlights (user_id, question_id, text_content, context_type, word_index, context_snippet, context_meta, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """, (
        current_user.user_id,
        data.question_id,
        data.text_content,
        data.context_type,
        data.word_index,
        data.context_snippet,
        json.dumps(data.context_meta) if data.context_meta else None,
        datetime.now().isoformat()
    ))

    inserted = c.fetchone()
    highlight_id = None
    if inserted:
        try:
            highlight_id = int(inserted["id"])
        except Exception:
            highlight_id = int(inserted[0])
    conn.commit()
    conn.close()

    # Auto-trigger flashcard generation when thresholds are reached.
    if data.context_type == "flashcard" and background_tasks is not None:
        from .flashcards import maybe_trigger_flashcard_generation
        background_tasks.add_task(maybe_trigger_flashcard_generation, current_user.user_id)
    
    return HighlightResponse(
        id=highlight_id,
        user_id=current_user.user_id,
        question_id=data.question_id,
        text_content=data.text_content,
        context_type=data.context_type,
        word_index=data.word_index,
        created_at=datetime.now().isoformat(),
        context_snippet=data.context_snippet,
        context_meta=data.context_meta
    )

@router.get("/{question_id}", response_model=List[HighlightResponse])
async def get_highlights(
    question_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """Get all highlights for a specific question and user."""
    ensure_highlight_context_schema()
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("""
        SELECT * FROM user_highlights
        WHERE user_id = ? AND question_id = ?
        ORDER BY created_at ASC
    """, (current_user.user_id, question_id))
    
    rows = c.fetchall()
    conn.close()
    
    return [
        HighlightResponse(
            id=row["id"],
            user_id=row["user_id"],
            question_id=row["question_id"],
            text_content=row["text_content"],
            context_type=row["context_type"],
            word_index=row["word_index"],
            created_at=row["created_at"],
            context_snippet=row["context_snippet"],
            context_meta=safe_json_parse(row["context_meta"], {}) if row["context_meta"] else None
        )
        for row in rows
    ]

@router.delete("/{highlight_id}")
async def delete_highlight(
    highlight_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """Delete a highlight (only if owned by current user)."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Verify ownership
    c.execute("SELECT user_id FROM user_highlights WHERE id = ?", (highlight_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Highlight not found")
    
    if str(row["user_id"]) != str(current_user.user_id):
        conn.close()
        raise HTTPException(status_code=403, detail="Not authorized to delete this highlight")
    
    c.execute("DELETE FROM user_highlights WHERE id = ?", (highlight_id,))
    conn.commit()
    conn.close()
    
    return {"status": "deleted", "id": highlight_id}
