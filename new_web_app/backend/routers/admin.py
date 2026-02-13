"""
Admin Router for FastAPI Backend

Provides:
- POST /admin/generate - Generate questions synchronously for a topic
- GET /admin/recent-questions - List recent questions
- Feedback management endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from hashlib import sha1
import json

from ..database import get_db_connection, get_prompt_templates, save_prompt_template, update_prompt_template, delete_prompt_template
from .auth import require_admin, TokenData

# Import from core
from ..helpers import find_pdf_for_topic

router = APIRouter(prefix="/admin", tags=["Admin"])

class GenerateRequest(BaseModel):
    topic: str
    source_material: str
    count: int = 5  # Number of questions to generate
    difficulty: int = 3  # 1-5
    source_pdfs_list: Optional[List[str]] = None  # For multi-PDF merge
    all_topics: Optional[List[str]] = None  # All selected topic names
    main_header: Optional[str] = None # Strict Scope: The Main Header (Category) name
    custom_prompt_sections: Optional[dict] = None  # Custom prompt sections from editor
    custom_difficulty_levels: Optional[dict] = None  # Custom difficulty level descriptions

class GenerateResponse(BaseModel):
    success: bool
    topic: str
    source_material: str
    generated_count: int
    skipped_count: int
    failed_count: int
    attempted_count: int
    target_count: int
    question_ids: List[int]
    message: str

class RecentQuestionResponse(BaseModel):
    id: int
    source_material: Optional[str]
    category: Optional[str]
    topic: Optional[str]
    question_text: str
    options: Optional[list] = None
    correct_answer_index: Optional[int] = None
    explanation_data: Optional[dict] = None
    tags: Optional[list] = None
    created_at: str

from pathlib import Path

MERGED_GROUPS_PATH = Path(__file__).parent.parent.parent.parent / "shared" / "data" / "merged_topic_groups.json"

def _build_merged_topic_name(main_header: Optional[str], topics: List[str]) -> str:
    clean_topics = [t.strip() for t in topics if t and t.strip()]
    if not clean_topics:
        return main_header or "Merged Topics"
    if len(clean_topics) == 1:
        return clean_topics[0]
    topic_count = len(clean_topics)
    header = main_header.strip() if main_header else ""
    if topic_count <= 4:
        joined = " + ".join(clean_topics)
        return f"{header} ({joined})" if header else joined
    start = clean_topics[0]
    end = clean_topics[-1]
    if header:
        return f"{header} ({topic_count} konu: {start} -> {end})"
    return f"{start} -> {end} ({topic_count} konu)"

def _record_merged_topic_group(entry: dict) -> None:
    MERGED_GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = []
    if MERGED_GROUPS_PATH.exists():
        try:
            data = json.loads(MERGED_GROUPS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []
    data.append(entry)
    tmp_path = MERGED_GROUPS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(MERGED_GROUPS_PATH)

# LEGACY run_generation_job is removed as logic is now in background_jobs.py


@router.post("/generate", response_model=GenerateResponse)
async def trigger_generation(
    data: GenerateRequest,
    current_user: TokenData = Depends(require_admin)
):
    """Generate questions asynchronously (background task)."""
    effective_topic = data.topic
    merged_topics = data.all_topics or []
    merged_pdfs = data.source_pdfs_list or []
    if merged_pdfs and len(merged_pdfs) > 1 and merged_topics:
        effective_topic = _build_merged_topic_name(data.main_header, merged_topics)
        group_id_seed = f"{data.source_material}|{data.main_header}|{effective_topic}|{merged_pdfs}"
        group_id = sha1(group_id_seed.encode("utf-8")).hexdigest()[:12]
        _record_merged_topic_group({
            "id": group_id,
            "source_material": data.source_material,
            "main_header": data.main_header,
            "merged_topic": effective_topic,
            "topics": merged_topics,
            "source_pdfs_list": merged_pdfs,
            "created_at": datetime.now().isoformat()
        })

    pdf_path_rel = find_pdf_for_topic(effective_topic)
    source_pdf = None
    if pdf_path_rel:
        full_pdf_path = Path(__file__).parent.parent.parent.parent / "shared" / pdf_path_rel
        if full_pdf_path.exists():
            source_pdf = str(full_pdf_path)
            
    payload = {
        "topic": effective_topic,
        "source_material": data.source_material,
        "count": data.count,
        "difficulty": data.difficulty,
        "source_pdf": source_pdf,
        "source_pdfs_list": data.source_pdfs_list,
        "all_topics": merged_topics or [effective_topic],
        "main_header": data.main_header,
        "category": data.main_header,
        "custom_prompt_sections": data.custom_prompt_sections,
        "custom_difficulty_levels": data.custom_difficulty_levels
    }
    
    # Create valid Job ID
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO background_jobs (type, status, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("generation_batch", "pending", json.dumps(payload), datetime.now(), datetime.now())
    )
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return GenerateResponse(
        success=True,
        topic=effective_topic,
        source_material=data.source_material,
        generated_count=0,
        skipped_count=0,
        failed_count=0,
        attempted_count=0,
        target_count=data.count,
        question_ids=[],
        message=f"Job queued (ID: {job_id})"
    )


# ─── Auto-Chunk Generation ───────────────────────────────────────────

class SubSegmentInput(BaseModel):
    title: str
    file: str
    page_count: int
    source_pdfs_list: Optional[List[str]] = None
    merged_topics: Optional[List[str]] = None

class AutoChunkGenerateRequest(BaseModel):
    source_material: str           # e.g., "Anatomi", "Farmakoloji"
    segment_title: str             # Main header / category name
    sub_segments: List[SubSegmentInput]
    count: int = 10                # Questions per chunk per multiplier round
    difficulty: int = 1
    multiplier: int = 1            # How many times to repeat per chunk
    custom_prompt_sections: Optional[dict] = None
    custom_difficulty_levels: Optional[dict] = None
    target_pages: int = 20         # Target page count per chunk

class ChunkInfo(BaseModel):
    chunk_index: int
    topic_name: str
    topics: List[str]
    source_pdfs_list: List[str]
    page_count: int
    job_ids: List[int]

class AutoChunkGenerateResponse(BaseModel):
    success: bool
    total_chunks: int
    total_jobs: int
    chunks: List[ChunkInfo]
    message: str


def _compute_chunks(sub_segments: List[SubSegmentInput], target: int = 20) -> List[List[SubSegmentInput]]:
    """
    Greedy chunking: iterate through sub_segments in order,
    accumulating items. At each step, decide whether adding the next
    item gets us closer to or further from `target`.
    If further, cut the chunk here (unless it's empty).
    
    Refinement: The last chunk must satisfy a minimum page count (e.g. 9 pages).
    If it's smaller, steal items from the previous chunk until it's satisfied
    or the previous chunk runs out.
    """
    if not sub_segments:
        return []

    chunks = []
    current_chunk: List[SubSegmentInput] = []
    current_pages = 0

    for seg in sub_segments:
        new_total = current_pages + seg.page_count

        if len(current_chunk) == 0:
            # Always add at least one item to a chunk
            current_chunk.append(seg)
            current_pages = new_total
        else:
            # Compare: distance if we include vs. distance if we cut here
            dist_with = abs(new_total - target)
            dist_without = abs(current_pages - target)

            if dist_with <= dist_without:
                # Including gets us closer (or equal) to target → include
                current_chunk.append(seg)
                current_pages = new_total
            else:
                # Including pushes us further → cut here, start new chunk
                chunks.append(current_chunk)
                current_chunk = [seg]
                current_pages = seg.page_count

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
        
    # --- REBALANCING LOGIC ---
    # Rule: Last chunk must be >= 9 pages (if possible).
    # If chunks[-1] < 9 pages AND we have a previous chunk,
    # move items from the END of chunks[-2] to the START of chunks[-1].
    
    MIN_LAST_CHUNK_PAGES = 9
    
    while len(chunks) > 1:
        last_chunk = chunks[-1]
        last_page_count = sum(s.page_count for s in last_chunk)
        
        if last_page_count >= MIN_LAST_CHUNK_PAGES:
            break
            
        # Need more pages in last chunk. Take from previous.
        prev_chunk = chunks[-2]
        if not prev_chunk:
            # Should not happen if logic is correct, but safe guard
            break
            
        # Take the last element from previous chunk
        moved_item = prev_chunk.pop()
        last_chunk.insert(0, moved_item)
        
        # If previous chunk became empty, remove it
        if not prev_chunk:
            chunks.pop(-2) # remove the now-empty previous chunk container
            # chunks[-1] is still the same list object we are modifying
            
    return chunks


@router.post("/auto-chunk-generate", response_model=AutoChunkGenerateResponse)
async def auto_chunk_generate(
    data: AutoChunkGenerateRequest,
    current_user: TokenData = Depends(require_admin)
):
    """
    Automatically split a segment's sub-segments into ~20-page chunks
    and create a generation job for each chunk × multiplier.
    """
    if not data.sub_segments:
        raise HTTPException(status_code=400, detail="No sub_segments provided")

    # 1. Compute optimal chunks
    chunk_groups = _compute_chunks(data.sub_segments, data.target_pages)

    all_chunks_info: List[ChunkInfo] = []
    total_jobs = 0

    conn = get_db_connection()
    c = conn.cursor()

    for chunk_idx, chunk_items in enumerate(chunk_groups):
        chunk_topics = [item.title for item in chunk_items]
        chunk_pdfs: List[str] = []
        for item in chunk_items:
            if item.source_pdfs_list:
                chunk_pdfs.extend(item.source_pdfs_list)
            else:
                chunk_pdfs.append(item.file)
        chunk_pdfs = list(dict.fromkeys(chunk_pdfs))  # dedupe while preserving order
        chunk_page_count = sum(item.page_count for item in chunk_items)

        # Build effective topic name
        effective_topic = _build_merged_topic_name(data.segment_title, chunk_topics)

        # Record merged group
        group_id_seed = f"{data.source_material}|{data.segment_title}|{effective_topic}|{chunk_pdfs}"
        group_id = sha1(group_id_seed.encode("utf-8")).hexdigest()[:12]
        _record_merged_topic_group({
            "id": group_id,
            "source_material": data.source_material,
            "main_header": data.segment_title,
            "merged_topic": effective_topic,
            "topics": chunk_topics,
            "source_pdfs_list": chunk_pdfs,
            "created_at": datetime.now().isoformat()
        })

        # Find PDF path for source_pdf field
        pdf_path_rel = find_pdf_for_topic(effective_topic)
        source_pdf = None
        if pdf_path_rel:
            full_pdf_path = Path(__file__).parent.parent.parent.parent / "shared" / pdf_path_rel
            if full_pdf_path.exists():
                source_pdf = str(full_pdf_path)

        # Create jobs (multiplier times)
        chunk_job_ids = []
        for _m in range(data.multiplier):
            payload = {
                "topic": effective_topic,
                "source_material": data.source_material,
                "count": data.count,
                "difficulty": data.difficulty,
                "source_pdf": source_pdf,
                "source_pdfs_list": chunk_pdfs if len(chunk_pdfs) > 1 else None,
                "all_topics": chunk_topics,
                "main_header": data.segment_title,
                "category": data.segment_title,
                "custom_prompt_sections": data.custom_prompt_sections,
                "custom_difficulty_levels": data.custom_difficulty_levels
            }

            c.execute(
                "INSERT INTO background_jobs (type, status, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("generation_batch", "pending", json.dumps(payload), datetime.now(), datetime.now())
            )
            job_id = c.lastrowid
            chunk_job_ids.append(job_id)
            total_jobs += 1

        all_chunks_info.append(ChunkInfo(
            chunk_index=chunk_idx,
            topic_name=effective_topic,
            topics=chunk_topics,
            source_pdfs_list=chunk_pdfs,
            page_count=chunk_page_count,
            job_ids=chunk_job_ids
        ))

    conn.commit()
    conn.close()

    return AutoChunkGenerateResponse(
        success=True,
        total_chunks=len(chunk_groups),
        total_jobs=total_jobs,
        chunks=all_chunks_info,
        message=f"{len(chunk_groups)} chunk, {total_jobs} job oluşturuldu"
    )


@router.post("/preview-chunks")
async def preview_chunks(
    data: AutoChunkGenerateRequest,
    current_user: TokenData = Depends(require_admin)
):
    """
    Preview the chunking result WITHOUT creating any jobs.
    Used by the frontend to show the user how files will be grouped.
    """
    if not data.sub_segments:
        return {"chunks": [], "total_chunks": 0}

    chunk_groups = _compute_chunks(data.sub_segments, data.target_pages)

    preview = []
    for idx, chunk_items in enumerate(chunk_groups):
        topics = [item.title for item in chunk_items]
        page_count = sum(item.page_count for item in chunk_items)
        topic_name = _build_merged_topic_name(data.segment_title, topics)
        preview.append({
            "chunk_index": idx,
            "topic_name": topic_name,
            "topics": topics,
            "page_count": page_count,
            "file_count": len(chunk_items)
        })

    return {
        "chunks": preview,
        "total_chunks": len(chunk_groups),
        "target_pages": data.target_pages
    }


@router.get("/recent-questions", response_model=List[RecentQuestionResponse])
async def list_recent_questions(
    limit: int = 50,
    current_user: TokenData = Depends(require_admin)
):
    """List most recently created questions (newest first)."""
    safe_limit = max(1, min(limit, 200))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, source_material, category, topic, question_text,
               options, correct_answer_index, explanation_data, tags, created_at
        FROM questions
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """, (safe_limit,))
    rows = c.fetchall()
    conn.close()

    def _safe_json(value, default=None):
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    res = []
    for row in rows:
        options = _safe_json(row[5], [])
        explanation = _safe_json(row[7])
        if explanation is None and row[7]:
            explanation = {"text": str(row[7])}
        tags = _safe_json(row[8], [])
        if tags is None:
            tags = []
        res.append(RecentQuestionResponse(
            id=row[0],
            source_material=row[1],
            category=row[2],
            topic=row[3],
            question_text=row[4],
            options=options,
            correct_answer_index=row[6],
            explanation_data=explanation,
            tags=tags,
            created_at=str(row[9])
        ))
    return res

class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    question_id: int
    feedback_type: str
    description: str
    status: str
    admin_note: Optional[str]
    created_at: str
    question_text: Optional[str]
    topic: Optional[str]

class ResolveFeedbackRequest(BaseModel):
    status: str # resolved, ignored, pending
    admin_note: Optional[str] = None

@router.get("/feedbacks", response_model=List[FeedbackResponse])
async def list_feedback(
    status: Optional[str] = None,
    current_user: TokenData = Depends(require_admin)
):
    """List all feedback, optionally filtered by status."""
    conn = get_db_connection()
    conn.row_factory = None
    c = conn.cursor()
    
    query = """
        SELECT f.id, f.user_id, f.question_id, f.feedback_type, f.description, 
               f.status, f.admin_note, f.created_at, q.question_text, q.topic
        FROM question_feedback f
        LEFT JOIN questions q ON f.question_id = q.id
    """
    
    params = []
    if status and status != 'all':
        query += " WHERE f.status = ?"
        params.append(status)
        
    query += " ORDER BY f.created_at DESC LIMIT 100"
    
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()
    
    res = []
    for row in rows:
        res.append(FeedbackResponse(
            id=row[0],
            user_id=row[1],
            question_id=row[2],
            feedback_type=row[3],
            description=row[4],
            status=row[5] or 'pending',
            admin_note=row[6],
            created_at=str(row[7]),
            question_text=row[8],
            topic=row[9]
        ))
    return res

@router.post("/feedbacks/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: int,
    data: ResolveFeedbackRequest,
    current_user: TokenData = Depends(require_admin)
):
    """Update feedback status."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("""
        UPDATE question_feedback 
        SET status = ?, admin_note = ? 
        WHERE id = ?
    """, (data.status, data.admin_note, feedback_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "id": feedback_id, "new_status": data.status}

class JobResponse(BaseModel):
    id: int
    status: str
    topic: str
    main_header: Optional[str]
    progress: int
    total_items: int
    generated_count: int
    created_at: str
    updated_at: str
    error_message: Optional[str]

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(limit: int = 20, current_user: TokenData = Depends(require_admin)):
    """List recent background generation jobs."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if table exists (in case running against old DB or during migration)
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='background_jobs'")
        if not c.fetchone():
            conn.close()
            return []
            
        c.execute("""
            SELECT id, status, payload, progress, total_items, generated_count, created_at, updated_at, error_message
            FROM background_jobs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    conn.close()
    
    jobs = []
    for row in rows:
        payload = {}
        try:
            if row[2]:
                payload = json.loads(row[2])
        except: pass
        
        main_header = payload.get('main_header') or payload.get('category')
        topic = payload.get('topic') or "Unknown Topic"
        
        jobs.append(JobResponse(
            id=row[0],
            status=row[1],
            topic=topic,
            main_header=main_header,
            progress=row[3] or 0,
            total_items=row[4] or 0,
            generated_count=row[5] or 0,
            created_at=str(row[6]),
            updated_at=str(row[7]),
            error_message=row[8]
        ))
        
    return jobs


# ─── Prompt Template CRUD ────────────────────────────────────────────

class PromptTemplateCreate(BaseModel):
    name: str
    sections: dict
    is_default: bool = False

class PromptTemplateUpdate(BaseModel):
    name: str
    sections: dict
    is_default: bool = False


@router.get("/prompt-templates")
async def list_prompt_templates(current_user: TokenData = Depends(require_admin)):
    """List all saved prompt templates."""
    return get_prompt_templates()


@router.post("/prompt-templates")
async def create_prompt_template(data: PromptTemplateCreate, current_user: TokenData = Depends(require_admin)):
    """Save a new prompt template."""
    new_id = save_prompt_template(data.name, data.sections, data.is_default)
    return {"id": new_id, "status": "created"}


@router.put("/prompt-templates/{template_id}")
async def edit_prompt_template(template_id: int, data: PromptTemplateUpdate, current_user: TokenData = Depends(require_admin)):
    """Update an existing prompt template."""
    ok = update_prompt_template(template_id, data.name, data.sections, data.is_default)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "status": "updated"}


@router.delete("/prompt-templates/{template_id}")
async def remove_prompt_template(template_id: int, current_user: TokenData = Depends(require_admin)):
    """Delete a prompt template."""
    ok = delete_prompt_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "status": "deleted"}


@router.get("/prompt-default-sections")
async def get_default_sections(current_user: TokenData = Depends(require_admin)):
    """Return the default prompt section templates, difficulty levels, and section order."""
    from core.bulk_generator import DEFAULT_PROMPT_SECTIONS, DEFAULT_DIFFICULTY_LEVELS, DEFAULT_SECTION_ORDER
    return {
        "sections": DEFAULT_PROMPT_SECTIONS,
        "difficulty_levels": DEFAULT_DIFFICULTY_LEVELS,
        "section_order": DEFAULT_SECTION_ORDER
    }


# ─── Per-Section Favorites ─────────────────────────────────────────

class SectionFavoriteCreate(BaseModel):
    section_key: str  # e.g. "persona", "principles", or a custom key
    name: str
    content: str


@router.get("/section-favorites")
async def list_section_favorites(
    section_key: Optional[str] = None,
    current_user: TokenData = Depends(require_admin)
):
    """List per-section favorites, optionally filtered by section key."""
    from ..database import get_section_favorites
    return get_section_favorites(section_key)


@router.post("/section-favorites")
async def create_section_favorite(data: SectionFavoriteCreate, current_user: TokenData = Depends(require_admin)):
    """Save a per-section favorite snippet."""
    from ..database import save_section_favorite
    new_id = save_section_favorite(data.section_key, data.name, data.content)
    return {"id": new_id, "status": "created"}


@router.delete("/section-favorites/{fav_id}")
async def remove_section_favorite(fav_id: int, current_user: TokenData = Depends(require_admin)):
    """Delete a per-section favorite."""
    from ..database import delete_section_favorite
    ok = delete_section_favorite(fav_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Section favorite not found")
    return {"id": fav_id, "status": "deleted"}


# ─── Difficulty Templates ──────────────────────────────────────────

class DifficultyTemplateCreate(BaseModel):
    name: str
    levels: dict
    is_default: bool = False

@router.get("/difficulty-templates")
async def list_difficulty_templates(current_user: TokenData = Depends(require_admin)):
    """List all saved difficulty templates."""
    from ..database import get_difficulty_templates
    return get_difficulty_templates()

@router.post("/difficulty-templates")
async def create_difficulty_template(data: DifficultyTemplateCreate, current_user: TokenData = Depends(require_admin)):
    """Save a new difficulty template."""
    from ..database import save_difficulty_template
    new_id = save_difficulty_template(data.name, data.levels, data.is_default)
    return {"id": new_id, "status": "created"}

@router.put("/difficulty-templates/{template_id}")
async def edit_difficulty_template(template_id: int, data: DifficultyTemplateCreate, current_user: TokenData = Depends(require_admin)):
    """Update an existing difficulty template."""
    from ..database import update_difficulty_template
    ok = update_difficulty_template(template_id, data.name, data.levels, data.is_default)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "status": "updated"}

@router.delete("/difficulty-templates/{template_id}")
async def remove_difficulty_template(template_id: int, current_user: TokenData = Depends(require_admin)):
    """Delete a difficulty template."""
    from ..database import delete_difficulty_template
    ok = delete_difficulty_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "status": "deleted"}
