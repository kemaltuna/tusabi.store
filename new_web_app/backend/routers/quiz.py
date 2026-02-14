from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from ..database import get_next_card, update_card_stats, ensure_user_sessions_schema
from ..models import QuizCard, SubmitReviewRequest
from ..helpers import calculate_sm2
from ..database import get_db_connection
from .auth import decode_token
from ..auth_models import TokenData

class FeedbackRequest(BaseModel):
    question_id: int
    feedback_type: str
    description: str

router = APIRouter(prefix="/quiz", tags=["Quiz"])

def get_user_id_from_token(authorization: Optional[str] = Header(None)) -> int:
    """Extract user_id from JWT token if present, otherwise return 1 (default/guest)."""
    if not authorization or not authorization.startswith("Bearer "):
        return 1  # Default user for unauthenticated requests
    
    try:
        token = authorization.split(" ")[1]
        payload = decode_token(token)
        return payload.user_id
    except:
        return 1  # Fallback to default user

def get_optional_user_from_token(authorization: Optional[str] = Header(None)) -> Optional[TokenData]:
    """Return TokenData if a valid token is provided; otherwise None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        token = authorization.split(" ")[1]
        return decode_token(token)
    except HTTPException:
        return None

@router.get("/next", response_model=Optional[QuizCard])
def get_next_question(
    mode: str = "standard", 
    topic: Optional[str] = None, 
    source: Optional[str] = None,
    category: Optional[str] = None,
    user_id: int = Depends(get_user_id_from_token),
    current_user: Optional[TokenData] = Depends(get_optional_user_from_token)
):
    """
    Fetch the next card based on Spaced Repetition (Due) or New Questions.
    Uses authenticated user_id if available, otherwise defaults to user 1.
    """
    if mode == "latest":
        if not current_user or current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

    # source maps to source_material_filter
    # category maps to category_filter (Main Header)
    card = get_next_card(user_id=user_id, topic_filter=topic, source_material_filter=source, category_filter=category, mode=mode)
    if not card:
        return None
        
    return card

@router.post("/submit")
def submit_review(
    data: SubmitReviewRequest,
    user_id: int = Depends(get_user_id_from_token)
):
    """
    Process user answer and update Spaced Repetition stats.
    "Block" card allows suspending it.
    New intervals (Randomized):
    - "again" -> 1-2 days
    - "hard" -> 4-8 days
    - "good" -> 3-5 weeks (21-35 days)
    - "easy" -> 3-4 months (90-120 days)
    - "block" -> Suspends card
    """
    import random
    import json
    
    # 1. We need CURRENT review state to calculate NEXT.
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM reviews WHERE question_id = ? AND user_id = ?", (data.question_id, user_id))
    review = c.fetchone()
    conn.close()
    
    current_flags = []
    prev_rep = 0
    
    if review:
        prev_rep = review['repetitions']
        if review['flags']:
            try:
                current_flags = json.loads(review['flags'])
            except:
                current_flags = []
    
    # Handle "Block" / Suspend
    if data.grade == "block":
        if "suspended" not in current_flags:
            current_flags.append("suspended")
        
        update_data = {
            "interval": 0,
            "ease_factor": 2.5, # Dummy
            "repetitions": prev_rep,
            "next_review_date": datetime.max, # Effectively never
            "flags": json.dumps(current_flags) # Save flags! `update_card_stats` logic needs to support this.
        }
        # Wait, update_card_stats signature in database.py DOES NOT accept flags argument explicitly?
        # Let's check update_card_stats in database.py. 
        # It takes (question_id, new_interval, new_ease_factor, new_repetitions, next_review_date, user_id).
        # It DOES NOT update flags.
        # I need to update database.py update_card_stats to handle flags OR do a manual update here.
        # Manual update here is safer/faster than changing shared DB function signature and breaking other things.
        
        conn = get_db_connection()
        c = conn.cursor()
        # Direct Upsert
        c.execute('''
            INSERT INTO reviews (question_id, user_id, interval, ease_factor, repetitions, next_review_date, last_review_date, flags)
            VALUES (?, ?, 0, 2.5, ?, ?, ?, ?)
            ON CONFLICT(question_id, user_id) DO UPDATE SET
            flags=excluded.flags, next_review_date=excluded.next_review_date
        ''', (data.question_id, user_id, prev_rep, datetime.max, datetime.now(), json.dumps(current_flags)))
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": "Card suspended"}

    # Handle Grades
    if data.grade == "again":
        new_int = random.randint(1, 2)
    elif data.grade == "hard":
        new_int = random.randint(4, 8)
    elif data.grade == "good":
        new_int = random.randint(21, 35)
    elif data.grade == "easy":
        new_int = random.randint(90, 120)
    else:
        new_int = 1 # Fallback
    
    new_rep = prev_rep + 1
    next_date = datetime.now() + timedelta(days=new_int)
    
    # Update DB (Flags remain unchanged if not blocked)
    # Using direct query to be consistent/safe given I can't easily change update_card_stats signature right now
    # Actually, update_card_stats is just a helper. I can replicate its logic.
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO reviews (question_id, user_id, interval, ease_factor, repetitions, next_review_date, last_review_date, flags)
        VALUES (?, ?, ?, 2.5, ?, ?, ?, ?)
        ON CONFLICT(question_id, user_id) DO UPDATE SET
        interval=excluded.interval, repetitions=excluded.repetitions, next_review_date=excluded.next_review_date, last_review_date=excluded.last_review_date
    ''', (data.question_id, user_id, new_int, new_rep, next_date, datetime.now(), json.dumps(current_flags)))
    conn.commit()
    conn.close()
    
    return {"status": "success", "next_review": next_date}

class SessionState(BaseModel):
    active_page: Optional[str] = None
    active_topic: Optional[str] = None
    active_mode: Optional[str] = "standard"
    current_card_id: Optional[int] = None
    active_source: Optional[str] = None
    active_category: Optional[str] = None

@router.get("/session")
def get_session(user_id: int = Depends(get_user_id_from_token)):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return {}

@router.post("/session")
def save_session(state: SessionState, user_id: int = Depends(get_user_id_from_token)):
    conn = get_db_connection()
    c = conn.cursor()

    # Ensure schema is up to date (legacy on-the-fly migration, now centralized).
    try:
        ensure_user_sessions_schema()
    except Exception:
        # Non-fatal: if schema is already correct or DB lacks privileges, proceed.
        pass
    
    c.execute('''
        INSERT INTO user_sessions (user_id, active_page, active_topic, active_source, active_category, active_mode, current_card_id, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        active_page=excluded.active_page,
        active_topic=excluded.active_topic,
        active_source=excluded.active_source,
        active_category=excluded.active_category,
        active_mode=excluded.active_mode,
        current_card_id=excluded.current_card_id,
        last_updated=excluded.last_updated
    ''', (user_id, state.active_page, state.active_topic, state.active_source, state.active_category, state.active_mode, state.current_card_id, datetime.now()))
    conn.commit()
    conn.close()
    return {"status": "saved"}

@router.post("/feedback")
def submit_feedback(data: FeedbackRequest, user_id: int = Depends(get_user_id_from_token)):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO question_feedback (user_id, question_id, feedback_type, description)
        VALUES (?, ?, ?, ?)
    ''', (user_id, data.question_id, data.feedback_type, data.description))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Feedback received"}
