from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime

class QuestionBase(BaseModel):
    source_material: Optional[str] = None
    category: Optional[str] = None
    topic: Optional[str] = None
    question_text: str
    options: List[Any]  # Can be strings or {id, text} objects depending on question source
    correct_answer_index: int
    explanation_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None

class QuestionOut(QuestionBase):
    id: int
    # Postgres returns native `datetime`; sqlite often stores timestamps as strings.
    # Using datetime keeps both compatible (Pydantic will parse strings and serialize to ISO).
    created_at: Optional[datetime] = None

class ReviewState(BaseModel):
    ease_factor: float = 2.5
    interval: float = 0.0
    repetitions: int = 0
    next_review_date: Optional[datetime] = None
    last_review_date: Optional[datetime] = None

class QuizCard(QuestionOut, ReviewState):
    """Combined model for the Frontend Card"""
    pass

class SubmitReviewRequest(BaseModel):
    question_id: int
    grade: str # "again", "hard", "good", "easy"
