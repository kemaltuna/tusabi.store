"""
PDF Manifests Router
Provides endpoints to access processed PDF manifests for question generation.
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import re
from functools import lru_cache

router = APIRouter(prefix="/pdfs", tags=["PDFs"])

PROCESSED_PDFS_DIR = Path(__file__).parent.parent.parent.parent / "shared" / "processed_pdfs"
SHARED_DIR = PROCESSED_PDFS_DIR.parent
MERGED_GROUPS_PATH = SHARED_DIR / "data" / "merged_topic_groups.json"

PART_PATTERN = re.compile(r"\bpart\s*\d+\b", re.IGNORECASE)

try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

@router.get("/manifests")
def get_all_manifests() -> Dict[str, Any]:
    """
    Get all manifest.json files from processed_pdfs directory.
    Returns a hierarchical structure with subjects → volumes → segments,
    enriched with perfectly synced question counts from the database/library.
    """
    result = {}
    
    if not PROCESSED_PDFS_DIR.exists():
        return {"subjects": {}, "error": "processed_pdfs directory not found"}
    
    # 1. Get Topic/Category Counts from DB (grouped by source and topic/category)
    from ..database import get_db_connection, get_library_structure, normalize_text

    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        "SELECT source_material, category, COUNT(*) as count "
        "FROM questions WHERE category IS NOT NULL AND category != '' "
        "GROUP BY source_material, category"
    )
    category_counts_raw = c.fetchall()

    c.execute(
        "SELECT source_material, topic, COUNT(*) as count "
        "FROM questions WHERE topic IS NOT NULL AND topic != '' "
        "GROUP BY source_material, topic"
    )
    topic_counts_raw = c.fetchall()
    conn.close()

    def normalize_label(text: str) -> str:
        if not text:
            return ""
        normalized = normalize_text(text)
        normalized = PART_PATTERN.sub("", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    category_counts: Dict[tuple, int] = {}
    for row in category_counts_raw:
        source = row["source_material"] or ""
        category = row["category"] or ""
        if not source or not category:
            continue
        key = (source, normalize_label(category))
        category_counts[key] = category_counts.get(key, 0) + row["count"]

    topic_counts: Dict[tuple, int] = {}
    for row in topic_counts_raw:
        source = row["source_material"] or ""
        topic = row["topic"] or ""
        if not source or not topic:
            continue
        key = (source, normalize_label(topic))
        topic_counts[key] = topic_counts.get(key, 0) + row["count"]

    library = get_library_structure()
    
    # 2. Map file paths to question counts using the library structure
    # This is the "Source of Truth" for what appears in Quiz Mode
    path_to_count: Dict[str, int] = {}

    def normalize_manifest_path(path: str) -> str:
        if not path:
            return ""
        clean_path = path.replace("\\", "/")
        if clean_path.startswith("./"):
            clean_path = clean_path[2:]
        if clean_path.startswith("shared/"):
            clean_path = clean_path[len("shared/"):]
        clean_path = clean_path.lstrip("/")
        idx = clean_path.find("processed_pdfs/")
        if idx != -1:
            clean_path = clean_path[idx:]
        return clean_path

    def resolve_pdf_path(file_path: str) -> Optional[Path]:
        if not file_path:
            return None
        clean_path = file_path.replace("\\", "/")
        if clean_path.startswith("./"):
            clean_path = clean_path[2:]
        if clean_path.startswith("shared/"):
            clean_path = clean_path[len("shared/"):]
        clean_path = clean_path.lstrip("/")
        return SHARED_DIR / clean_path

    @lru_cache(maxsize=2048)
    def get_pdf_page_count(file_path: str) -> Optional[int]:
        if not PdfReader:
            return None
        resolved = resolve_pdf_path(file_path)
        if not resolved or not resolved.exists():
            return None
        try:
            reader = PdfReader(str(resolved))
            return len(reader.pages)
        except Exception:
            return None
    for subject_name, subject_data in library.items():
        topics = subject_data.get("topics", [])
        for t in topics:
            topic_name = t.get("topic")
            path = t.get("path")
            if topic_name and path:
                count = topic_counts.get((subject_name, normalize_label(topic_name)), 0)
                normalized_path = normalize_manifest_path(path)
                if normalized_path:
                    path_to_count[normalized_path] = count

    # Helper to get count for a file (exact match)
    def get_file_count(file_path: str) -> int:
        if not file_path:
            return 0
        clean_path = normalize_manifest_path(file_path)
        return path_to_count.get(clean_path, 0)

    def get_category_count(source: str, category_name: str) -> int:
        if not source or not category_name:
            return 0
        return category_counts.get((source, normalize_label(category_name)), 0)

    def get_topic_count(source: str, topic_name: str) -> int:
        if not source or not topic_name:
            return 0
        return topic_counts.get((source, normalize_label(topic_name)), 0)

    def get_page_count(file_path: str, pages_range: List[int]) -> int:
        if isinstance(pages_range, list) and len(pages_range) == 2:
            fallback = pages_range[1] - pages_range[0] + 1
        else:
            fallback = 0
        if fallback <= 1 and file_path:
            actual = get_pdf_page_count(file_path)
            if actual:
                return actual
        return fallback

    merged_groups = []
    if MERGED_GROUPS_PATH.exists():
        try:
            merged_groups = json.loads(MERGED_GROUPS_PATH.read_text(encoding="utf-8"))
        except Exception:
            merged_groups = []
    if not isinstance(merged_groups, list):
        merged_groups = []

    merged_volume_rules = {
        "Kadin_Dogum": ["kadin_dogum_f1", "kadin_dogum_f2"],
        "Dahiliye": ["dahiliye_f2"],
    }

    def _get_merged_groups(source: str, volume_name: str) -> Dict[str, List[Dict[str, Any]]]:
        rules = merged_volume_rules.get(source)
        if not rules:
            return {}
        volume_lower = volume_name.lower()
        if not any(rule in volume_lower for rule in rules):
            return {}
        groups = {}
        for entry in merged_groups:
            if entry.get("source_material") != source:
                continue
            main_header = entry.get("main_header") or ""
            groups.setdefault(main_header, []).append(entry)
        return groups

    def _get_group_page_count(file_list: List[str]) -> int:
        total = 0
        for file_path in file_list or []:
            total += get_page_count(file_path, [0, 0])
        return total

    # 3. Iterate through subject folders and build the tree
    for subject_dir in sorted(PROCESSED_PDFS_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        
        subject_name = subject_dir.name
        result[subject_name] = {"volumes": []}
        
        for volume_dir in sorted(subject_dir.iterdir()):
            if not volume_dir.is_dir():
                continue
            
            manifest_path = volume_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                merged_groups = _get_merged_groups(subject_name, volume_dir.name)
                segments = []
                for seg in manifest.get("segments", []):
                    # Ignore parser leftovers that are not real generation segments.
                    # Some manifests include {"type": "unresolved", "title": "..."} entries
                    # (e.g. migrated/moved headers). Showing them in UI causes phantom
                    # 1-page categories.
                    seg_type = (seg.get("type") or "").strip().lower()
                    if seg_type and seg_type != "main":
                        continue
                    if not seg.get("file"):
                        continue

                    # Sum counts for sub-segments
                    sub_segments = []
                    seg_total_questions = 0
                    merged_for_segment = merged_groups.get(seg.get("title", ""), [])
                    if merged_for_segment:
                        for group in merged_for_segment:
                            group_topic = group.get("merged_topic", "")
                            group_pdfs = group.get("source_pdfs_list", []) or []
                            group_topics = group.get("topics", []) or []
                            group_q_count = get_topic_count(subject_name, group_topic)
                            seg_total_questions += group_q_count
                            sub_segments.append({
                                "title": group_topic,
                                "file": f"merged:{group.get('id', group_topic)}",
                                "page_count": _get_group_page_count(group_pdfs),
                                "question_count": group_q_count,
                                "pages": [0, 0],
                                "source_pdfs_list": group_pdfs,
                                "merged_topics": group_topics,
                            })
                    else:
                        for sub in seg.get("sub_segments", []):
                            sub_file = sub.get("file", "")
                            sub_q_count = get_topic_count(subject_name, sub.get("title", ""))
                            if sub_q_count == 0:
                                sub_q_count = get_file_count(sub_file)
                            seg_total_questions += sub_q_count

                            sub_pages = sub.get("pages", [0, 0])
                            sub_segments.append({
                                "title": sub.get("title", ""),
                                "file": sub_file,
                                "page_count": get_page_count(sub_file, sub_pages),
                                "question_count": sub_q_count,
                                "pages": sub_pages
                            })
                    
                    # Use category count as the primary segment total.
                    seg_category_count = get_category_count(subject_name, seg.get("title", ""))
                    if seg_category_count > 0:
                        seg_total_questions = seg_category_count
                    elif seg_total_questions == 0:
                        seg_total_questions = get_file_count(seg.get("file", ""))

                    pages_raw = seg.get("pages_raw", [0, 0])
                    segments.append({
                        "title": seg.get("title", ""),
                        "file": seg.get("file", ""),
                        "page_count": get_page_count(seg.get("file", ""), pages_raw),
                        "question_count": seg_total_questions,
                        "pages_raw": pages_raw,
                        "sub_segments": sub_segments
                    })
                
                result[subject_name]["volumes"].append({
                    "name": volume_dir.name,
                    "source": manifest.get("source", ""),
                    "segments": segments
                })
                
            except (json.JSONDecodeError, IOError):
                continue
    
    return {"subjects": result}


@router.get("/manifests/{subject}")
def get_subject_manifest(subject: str) -> Dict[str, Any]:
    """Get manifest for a specific subject."""
    subject_dir = PROCESSED_PDFS_DIR / subject
    
    if not subject_dir.exists():
        raise HTTPException(status_code=404, detail=f"Subject '{subject}' not found")
    
    result = {"volumes": []}
    
    for volume_dir in sorted(subject_dir.iterdir()):
        if not volume_dir.is_dir():
            continue
        
        manifest_path = volume_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            result["volumes"].append({
                "name": volume_dir.name,
                "source": manifest.get("source", ""),
                "segments": manifest.get("segments", [])
            })
        except:
            continue
    
    return result


@router.post("/merge")
async def merge_pdfs(pdf_paths: List[str]) -> Dict[str, Any]:
    """
    Merge multiple sub-segment PDFs into a single text for generation.
    Returns the merged text content.
    """
    from PyPDF2 import PdfReader
    
    merged_text = []
    
    for pdf_path in pdf_paths:
        full_path = Path(__file__).parent.parent.parent.parent / "shared" / pdf_path
        
        if not full_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")
        
        try:
            reader = PdfReader(str(full_path))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    merged_text.append(text)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading PDF: {str(e)}")
    
    return {
        "merged_text": "\n\n---\n\n".join(merged_text),
        "pdf_count": len(pdf_paths),
        "total_length": sum(len(t) for t in merged_text)
    }
