from fastapi import APIRouter, Depends
from typing import Dict, List, Optional, Set, Tuple
from ..database import get_library_structure, get_db_connection, normalize_text
from .auth import get_current_user, TokenData
import re

router = APIRouter(prefix="/library", tags=["Library"])

# Pattern to strip "(Part X)" suffixes for normalization (same as pdfs.py)
PART_PATTERN = re.compile(r"\bpart\s*\d+\b", re.IGNORECASE)

LESSON_SOURCES = {
    "Anatomi",
    "Biyokimya",
    "Dahiliye",
    "Farmakoloji",
    "Fizyoloji",
    "Genel_Cerrahi",
    "Kadin_Dogum",
    "Kucuk_Stajlar",
    "Mikrobiyoloji",
    "Patoloji",
    "Pediatri",
}

FLASHCARD_SOURCES = {
    "AI Flashcards",
}

# For these sources/categories, show only generated (DB) topics; do not use manifest subtopics.
GENERATED_TOPICS_ONLY: Dict[str, Set[str]] = {}

# Pre-normalize category names for lookup
GENERATED_TOPICS_ONLY_NORM = {
    source: {"*" if name == "*" else normalize_text(name) for name in names}
    for source, names in GENERATED_TOPICS_ONLY.items()
}

# Sources where sub-topics (merged groups) SHOULD be shown.
# Format: (source_name, fascicle_suffix) - uses "contains" matching on the path
SHOW_SUBTOPICS_FOR: Set[Tuple[str, str]] = set()

def should_show_subtopics(source_name: str, topic_path: str) -> bool:
    """Check if sub-topics should be shown for this source/topic path combination."""
    path_lower = topic_path.lower() if topic_path else ""
    for (src, suffix) in SHOW_SUBTOPICS_FOR:
        if source_name == src and suffix in path_lower:
            return True
    return False

def should_use_generated_topics(source_name: str, category_name: str) -> bool:
    cats = GENERATED_TOPICS_ONLY_NORM.get(source_name)
    if not cats:
        return False
    if "*" in cats:
        return True
    return normalize_text(category_name) in cats

def build_library_tree(allowed_sources: Optional[set] = None, include_orphans: bool = False, collapse_subtopics: bool = True, user_id: Optional[int] = None) -> Dict:
    """Build tree from processed_pdfs manifest files with DB counts.
    
    Quiz Mode specific behavior:
    - NO volume (cilt) separation - all volumes merged
    - Shows only category names with aggregated counts
    - Includes 'solved_count' if user_id is provided
    """
    from pathlib import Path
    import json
    
    PROCESSED_PDFS_DIR = Path(__file__).parent.parent.parent.parent / "shared" / "processed_pdfs"
    
    if not PROCESSED_PDFS_DIR.exists():
        return {}
    
    def normalize_label(text: str) -> str:
        """Normalize text and strip (Part X) suffixes for consistent aggregation."""
        if not text:
            return ""
        normalized = normalize_text(text)
        normalized = PART_PATTERN.sub("", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    
    # Get question counts from database
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Get counts by (source, category)
    c.execute("SELECT source_material, category, COUNT(*) as count FROM questions WHERE category IS NOT NULL AND category != '' GROUP BY source_material, category")
    category_counts_raw: Dict[Tuple[str, str], int] = {}
    for row in c.fetchall():
        source = row["source_material"] or ""
        category = row["category"] or ""
        category_counts_raw[(source, category)] = row["count"]
    
    # 2. Get counts by (source, topic)
    c.execute("SELECT source_material, topic, COUNT(*) as count FROM questions WHERE topic IS NOT NULL AND topic != '' GROUP BY source_material, topic")
    topic_counts_raw: Dict[Tuple[str, str], int] = {}
    for row in c.fetchall():
        source = row["source_material"] or ""
        topic = row["topic"] or ""
        topic_counts_raw[(source, topic)] = row["count"]
    
    # 3. Get SOLVED counts if user_id provided
    category_solved_counts: Dict[Tuple[str, str], int] = {}
    topic_solved_counts: Dict[Tuple[str, str], int] = {}
    topic_solved_counts_exact: Dict[Tuple[str, str], int] = {}

    if user_id:
        c.execute("""
            SELECT q.source_material, q.category, COUNT(*) as count 
            FROM questions q
            JOIN reviews r ON q.id = r.question_id
            WHERE q.category IS NOT NULL AND q.category != '' 
              AND r.user_id = ? AND r.repetitions > 0
            GROUP BY q.source_material, q.category
        """, (user_id,))
        for row in c.fetchall():
            source = row["source_material"] or ""
            category = row["category"] or ""
            # Normalize key using same logic as total counts
            norm_key = (source, normalize_label(category))
            category_solved_counts[norm_key] = category_solved_counts.get(norm_key, 0) + row["count"]
            
        c.execute("""
            SELECT q.source_material, q.topic, COUNT(*) as count 
            FROM questions q
            JOIN reviews r ON q.id = r.question_id
            WHERE q.topic IS NOT NULL AND q.topic != '' 
              AND r.user_id = ? AND r.repetitions > 0
            GROUP BY q.source_material, q.topic
        """, (user_id,))
        for row in c.fetchall():
            source = row["source_material"] or ""
            topic = row["topic"] or ""
            norm_key = (source, normalize_label(topic))
            topic_solved_counts[norm_key] = topic_solved_counts.get(norm_key, 0) + row["count"]
            
            # Also store exact match for Parts lookup
            exact_key = (source, normalize_text(topic))
            topic_solved_counts_exact[exact_key] = topic_solved_counts_exact.get(exact_key, 0) + row["count"]

    conn.close()

    # Build mapping for "Part" topics (e.g., "Obstetri (Part 1)") to their base category
    # ... (existing code for part topics) ... 
    part_topics_by_category: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
    # We also need solved counts for parts
    part_solved_by_category: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}

    for (source, topic), count in topic_counts_raw.items():
        match = re.match(r"(.+?)\\s*\\(\\s*part\\s*\\d+\\s*\\)\\s*$", topic, re.IGNORECASE)
        if not match:
            continue
        base = match.group(1).strip()
        if not base:
            continue
        key = (source, normalize_text(base))
        part_topics_by_category.setdefault(key, []).append((topic, count))
        
        # Add solved count if available
        if user_id:
            # For Parts, we MUST use the exact lookup, otherwise we get the aggregate of the whole category
            norm_topic_key = (source, normalize_text(topic))
            solved = topic_solved_counts_exact.get(norm_topic_key, 0)
            if solved > 0:
                part_solved_by_category.setdefault(key, []).append((topic, solved))

    # Helper to get generated topics that match a category prefix
    def get_generated_topics_for_category(source: str, category_name: str) -> List[Tuple[str, int, int]]:
        # Returns (topic, total_count, solved_count)
        base_norm = normalize_text(category_name)
        out = []
        for (src, topic), count in topic_counts_raw.items():
            if src != source or count <= 0:
                continue
            if normalize_text(topic).startswith(base_norm):
                norm_topic_key = (src, normalize_label(topic))
                solved = topic_solved_counts.get(norm_topic_key, 0)
                out.append((topic, count, solved))
        # Stable order by topic text
        return sorted(out, key=lambda x: x[0])
    


    # Build normalized lookup dictionaries
    def build_normalized_lookup(raw_counts: Dict[Tuple[str, str], int]) -> Dict[Tuple[str, str], int]:
        """Build lookup with normalized keys for matching."""
        lookup = {}
        for (source, name), count in raw_counts.items():
            norm_key = (source, normalize_label(name))
            lookup[norm_key] = lookup.get(norm_key, 0) + count
        return lookup
    
    category_counts = build_normalized_lookup(category_counts_raw)
    topic_counts = build_normalized_lookup(topic_counts_raw)
    
    # Helper to get category count (total, solved)
    def get_category_stats(source: str, category_name: str) -> Tuple[int, int]:
        norm_key = (source, normalize_label(category_name))
        return category_counts.get(norm_key, 0), category_solved_counts.get(norm_key, 0)
    
    # Helper to get topic count (total, solved)
    def get_topic_stats(source: str, topic_name: str) -> Tuple[int, int]:
        norm_key = (source, normalize_label(topic_name))
        return topic_counts.get(norm_key, 0), topic_solved_counts.get(norm_key, 0)
    
    tree: Dict[str, Dict[str, object]] = {}
    
    # Iterate through subject folders
    for subject_dir in sorted(PROCESSED_PDFS_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        
        subject_name = subject_dir.name
        if allowed_sources and subject_name not in allowed_sources:
            continue
        
        # Collect all categories from ALL volumes (merged, no cilt separation)
        all_categories: Dict[str, Dict] = {}  # category_name -> {count, topics: []}
        
        for volume_dir in sorted(subject_dir.iterdir()):
            if not volume_dir.is_dir():
                continue
            
            manifest_path = volume_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                
                # Check if this volume should show sub-topics
                should_show_topics = False
                if collapse_subtopics:
                    for (src, suffix) in SHOW_SUBTOPICS_FOR:
                        if src == subject_name and suffix in volume_dir.name.lower():
                            should_show_topics = True
                            break
                else:
                    should_show_topics = True

                for seg in manifest.get("segments", []):
                    category_name = seg.get("title", "")
                    if not category_name:
                        continue
                    
                    # Initialize category if not exists
                    if category_name not in all_categories:
                        all_categories[category_name] = {
                            "count": 0,
                            "solved_count": 0,
                            "topics": [],
                            "show_topics": False,
                            "subtopic_norms": set(),
                            "extra_topic_norms": set(),
                            "generated_only": should_use_generated_topics(subject_name, category_name),
                        }
                    
                    cat_entry = all_categories[category_name]

                    # Generated-only categories: skip manifest subtopics and counts
                    if cat_entry.get("generated_only"):
                        cat_entry["show_topics"] = True
                        continue
                    
                    if should_show_topics and seg.get("sub_segments"):
                        # Add topics for this category
                        cat_entry["show_topics"] = True
                        for sub in seg.get("sub_segments", []):
                            sub_title = sub.get("title", "")
                            if sub_title:
                                sub_total, sub_solved = get_topic_stats(subject_name, sub_title)
                                cat_entry["topics"].append({
                                    "topic": sub_title,
                                    "count": sub_total,
                                    "solved_count": sub_solved
                                })
                                cat_entry["count"] += sub_total
                                cat_entry["solved_count"] += sub_solved
                                cat_entry["subtopic_norms"].add(normalize_text(sub_title))
                    else:
                        # Just add category count (no topics shown)
                        cat_total, cat_solved = get_category_stats(subject_name, category_name)
                        cat_entry["count"] += cat_total
                        cat_entry["solved_count"] += cat_solved

            except (json.JSONDecodeError, IOError):
                continue
        
        # Build final structure for this subject
        if all_categories:
            # For generated-only categories, populate topics from DB (count>0 only)
            for cat_name, cat_data in all_categories.items():
                if not cat_data.get("generated_only"):
                    continue
                generated_stats = get_generated_topics_for_category(subject_name, cat_name)
                cat_data["topics"] = [
                    {"topic": t, "count": c, "solved_count": sc, "is_generated": True}
                    for t, c, sc in generated_stats
                    if c > 0
                ]
                cat_data["count"] = sum(t["count"] for t in cat_data["topics"])
                cat_data["solved_count"] = sum(t["solved_count"] for t in cat_data["topics"])
                cat_data["show_topics"] = True
                cat_data["show_topics"] = True

            # Add "Part" topics under their base category if subtopics are shown
            for cat_name, cat_data in all_categories.items():
                if cat_data.get("generated_only"):
                    continue
                if not cat_data.get("show_topics"):
                    continue
                key = (subject_name, normalize_text(cat_name))
                for part_topic, part_count in part_topics_by_category.get(key, []):
                    norm_part = normalize_text(part_topic)
                    if norm_part in cat_data["subtopic_norms"] or norm_part in cat_data["extra_topic_norms"]:
                        continue
                    
                    # Compute solved count for this part dynamically or from pre-aggregation
                    # Using topic_solved_counts directly for safety
                    part_solved = topic_solved_counts.get((subject_name, normalize_label(part_topic)), 0)
                    
                    cat_data["topics"].append({
                        "topic": part_topic,
                        "count": part_count,
                        "solved_count": part_solved,
                        "is_part": True
                    })
                    cat_data["extra_topic_norms"].add(norm_part)
                    cat_data["count"] += part_count
                    cat_data["solved_count"] += part_solved

            categories_output = {}
            for cat_name, cat_data in sorted(all_categories.items()):
                if cat_data["show_topics"] and cat_data["topics"]:
                    # Show as list of topics
                    categories_output[cat_name] = cat_data["topics"]
                else:
                    # Show as single collapsed category entry
                    categories_output[cat_name] = [{
                        "topic": cat_name,
                        "count": cat_data["count"],
                        "solved_count": cat_data["solved_count"],
                        "is_category": True
                    }]
            
            tree[subject_name] = {
                "topic_count": sum(len(v) for v in categories_output.values()),
                "categories": categories_output,
            }
    
    return tree
    


@router.get("/structure")
def get_library():
    """Returns the JSON taxonomy of subjects and topics."""
    return get_library_structure()

@router.get("/tree")
def get_library_tree(current_user: TokenData = Depends(get_current_user)):
    """Returns the library structure with question counts per topic (student view - collapsed)."""
    return build_library_tree(allowed_sources=LESSON_SOURCES, include_orphans=False, collapse_subtopics=True, user_id=current_user.user_id)

@router.get("/tree/full")
def get_library_tree_full(current_user: TokenData = Depends(get_current_user)):
    """Returns the FULL library structure with all sub-topics (admin/generation view)."""
    return build_library_tree(allowed_sources=LESSON_SOURCES, include_orphans=False, collapse_subtopics=False, user_id=current_user.user_id)


@router.get("/flashcards")
def get_flashcards_tree():
    """Returns flashcard sources grouped separately."""
    if not FLASHCARD_SOURCES:
        return {}
    conn = get_db_connection()
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(FLASHCARD_SOURCES))
    c.execute(
        f"SELECT source_material, topic, COUNT(*) as count FROM questions "
        f"WHERE source_material IN ({placeholders}) GROUP BY source_material, topic",
        tuple(sorted(FLASHCARD_SOURCES)),
    )
    rows = c.fetchall()
    conn.close()

    tree: Dict[str, Dict[str, object]] = {}
    for row in rows:
        source_name = row["source_material"]
        tree.setdefault(source_name, {"topic_count": 0, "categories": {"Flashcards": []}})
        tree[source_name]["categories"]["Flashcards"].append({
            "topic": row["topic"],
            "count": row["count"],
            "path": "Flashcards",
        })

    for source_name, source_data in tree.items():
        source_data["categories"]["Flashcards"].sort(key=lambda x: x["topic"])
    return tree

@router.get("/sources")
def get_sources():
    """Returns just the list of source names."""
    return sorted(LESSON_SOURCES)
