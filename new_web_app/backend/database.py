import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import re
import unicodedata
from pathlib import Path
import difflib
import logging

# Paths relative to this file (new_web_app/backend/database.py)
_BASE_DIR = Path(__file__).parent.parent.parent  # -> medical_quiz_app
DB_PATH = str(_BASE_DIR / "shared" / "data" / "quiz_v2.db")
LIBRARY_JSON_PATH = str(_BASE_DIR / "shared" / "data" / "medquiz_library.json")

def get_db_engine() -> str:
    """
    Returns the active DB engine name used by the backend.

    - "sqlite": default (uses shared/data/quiz_v2.db)
    - "postgres": when MEDQUIZ_DB_URL (or DATABASE_URL) is a postgres DSN
    """
    dsn = os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL") or ""
    try:
        from .db_compat import is_postgres_dsn
        return "postgres" if is_postgres_dsn(dsn) else "sqlite"
    except Exception:
        return "sqlite"

def get_db_connection():
    dsn = os.getenv("MEDQUIZ_DB_URL") or os.getenv("DATABASE_URL")
    try:
        from .db_compat import is_postgres_dsn, PostgresCompatConnection
    except Exception:
        is_postgres_dsn = None
        PostgresCompatConnection = None

    if dsn and is_postgres_dsn and PostgresCompatConnection and is_postgres_dsn(dsn):
        # Postgres connection (psycopg). Keep rows dict-like for existing call sites.
        import psycopg
        from .db_compat import compat_row_factory

        raw = psycopg.connect(dsn, row_factory=compat_row_factory)
        return PostgresCompatConnection(raw)

    # SQLite fallback (default)
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def ensure_concept_embeddings_table():
    """Ensures that the concept_embeddings table exists."""
    conn = get_db_connection()
    c = conn.cursor()
    if get_db_engine() == "postgres":
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS concept_embeddings (
                id BIGSERIAL PRIMARY KEY,
                topic TEXT NOT NULL,
                concept_text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        c.execute('''
            CREATE TABLE IF NOT EXISTS concept_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                concept_text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    # Index for faster lookup by topic
    c.execute('CREATE INDEX IF NOT EXISTS idx_embeddings_topic ON concept_embeddings (topic)')
    conn.commit()
    conn.close()

def ensure_highlight_context_schema():
    """Ensure user_highlights has context fields for location-aware flashcards."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        columns = set()
        if get_db_engine() == "postgres":
            c.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'user_highlights'
                """
            )
            for row in c.fetchall() or []:
                # psycopg dict_row returns dicts
                if isinstance(row, dict):
                    columns.add(row.get("column_name"))
                else:
                    columns.add(row[0])
        else:
            c.execute("PRAGMA table_info(user_highlights)")
            for row in c.fetchall():
                try:
                    columns.add(row["name"])
                except Exception:
                    columns.add(row[1])
        if "context_snippet" not in columns:
            c.execute("ALTER TABLE user_highlights ADD COLUMN context_snippet TEXT")
        if "context_meta" not in columns:
            c.execute("ALTER TABLE user_highlights ADD COLUMN context_meta TEXT")
        conn.commit()
    finally:
        conn.close()

def ensure_user_sessions_schema() -> None:
    """Ensure user_sessions has active_source and active_category columns (legacy on-the-fly migration)."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        columns = set()
        if get_db_engine() == "postgres":
            c.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'user_sessions'
                """
            )
            for row in c.fetchall() or []:
                if isinstance(row, dict):
                    columns.add(row.get("column_name"))
                else:
                    columns.add(row[0])
        else:
            c.execute("PRAGMA table_info(user_sessions)")
            for row in c.fetchall() or []:
                try:
                    columns.add(row["name"])
                except Exception:
                    columns.add(row[1])

        if "active_source" not in columns:
            c.execute("ALTER TABLE user_sessions ADD COLUMN active_source TEXT")
        if "active_category" not in columns:
            c.execute("ALTER TABLE user_sessions ADD COLUMN active_category TEXT")
        conn.commit()
    finally:
        conn.close()

def ensure_question_topic_links_table():
    """Create question-topic relationship table used for topic-scoped history."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if get_db_engine() == "postgres":
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS question_topic_links (
                    question_id BIGINT NOT NULL,
                    source_material TEXT,
                    category TEXT,
                    topic TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (question_id, topic)
                )
                """
            )
        else:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS question_topic_links (
                    question_id INTEGER NOT NULL,
                    source_material TEXT,
                    category TEXT,
                    topic TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (question_id, topic)
                )
                """
            )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_qtl_scope_topic "
            "ON question_topic_links (source_material, category, topic, question_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_qtl_topic "
            "ON question_topic_links (topic, question_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_qtl_question "
            "ON question_topic_links (question_id)"
        )
        conn.commit()
    finally:
        conn.close()


from contextlib import contextmanager

@contextmanager
def get_db_cursor():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def safe_json_parse(value: Any, default: Any = None) -> Any:
    """Parses JSON string to object, with fallback."""
    if isinstance(value, (dict, list)):
        return value
    if not value and default is not None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # Try AST fallback if simple Quote issue (legacy data might use single quotes)
            import ast
            try:
                return ast.literal_eval(value)
            except:
                return default
    return default

def process_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Converts SQLite Row to Dict and parses JSON fields."""
    d = dict(row)
    
    # Fields that are stored as JSON strings
    json_fields = {
        'options': [],
        'explanation_data': {},
        'tags': [],
        'flags': []
    }
    
    for key, default_val in json_fields.items():
        if key in d:
             d[key] = safe_json_parse(d[key], default_val)
             
    return d

def get_variants(text: Optional[str]) -> List[str]:
    """Generate case variants for robust matching (handles Turkish I/İ)."""
    if not text:
        return []
    variants = {text}
    variants.add(text.upper())
    variants.add(text.lower())
    variants.add(text.replace("i", "İ").upper())
    variants.add(text.replace("I", "ı").lower())
    variants.add(text.replace("İ", "i").lower())
    return list(variants)

def normalize_text(text: str) -> str:
    """Normalize text for loose matching across casing/diacritics/prefixes."""
    text = text.strip()
    text = re.sub(r"^\d+\s*", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("ı", "i")
    text = re.sub(r"[^0-9a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _normalize_topic_value(topic: Any) -> str:
    if not isinstance(topic, str):
        return ""
    return re.sub(r"\s+", " ", topic.strip())

def _dedupe_topics(topics: Any) -> List[str]:
    if topics is None:
        return []
    values = topics if isinstance(topics, list) else [topics]
    cleaned: List[str] = []
    seen = set()
    for value in values:
        topic = _normalize_topic_value(value)
        if not topic or topic in seen:
            continue
        seen.add(topic)
        cleaned.append(topic)
    return cleaned

def _extract_concepts_from_tag_values(tag_values: List[Any]) -> List[str]:
    concepts: List[str] = []
    for tags_raw in tag_values:
        if not tags_raw:
            continue
        tags = tags_raw if isinstance(tags_raw, list) else safe_json_parse(tags_raw, [])
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("concept:"):
                concept_text = tag.replace("concept:", "").strip()
                if concept_text:
                    concepts.append(concept_text)
                break
    return concepts

def link_question_to_topics(
    question_id: int,
    topics: Any,
    source_material: Optional[str] = None,
    category: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Attach question to one or more topics in question_topic_links."""
    clean_topics = _dedupe_topics(topics)
    if not question_id or not clean_topics:
        return 0

    owns_conn = conn is None
    if owns_conn:
        ensure_question_topic_links_table()
        conn = get_db_connection()

    inserted = 0
    try:
        c = conn.cursor()
        for topic in clean_topics:
            c.execute(
                '''
                INSERT INTO question_topic_links
                (question_id, source_material, category, topic)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                ''',
                (question_id, source_material, category, topic)
            )
            if c.rowcount and c.rowcount > 0:
                inserted += c.rowcount
        if owns_conn:
            conn.commit()
        return inserted
    finally:
        if owns_conn and conn:
            conn.close()

def get_recent_concepts_by_topic_scope(
    source_material: Optional[str],
    topics: Any,
    category: Optional[str] = None,
    limit: int = 300
) -> List[str]:
    """Fetch concept titles from questions linked to the provided topic set."""
    clean_topics = _dedupe_topics(topics)
    if not source_material or not clean_topics:
        return []

    safe_limit = max(1, int(limit or 1))
    ensure_question_topic_links_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        where_clauses = ["l.source_material = ?"]
        params: List[Any] = [source_material]
        if category:
            where_clauses.append("l.category = ?")
            params.append(category)

        placeholders = ",".join(["?"] * len(clean_topics))
        where_clauses.append(f"l.topic IN ({placeholders})")
        params.extend(clean_topics)
        params.append(safe_limit)

        c.execute(
            f'''
            SELECT q.tags
            FROM questions q
            JOIN (
                SELECT DISTINCT l.question_id
                FROM question_topic_links l
                WHERE {" AND ".join(where_clauses)}
            ) scoped ON scoped.question_id = q.id
            ORDER BY q.id DESC
            LIMIT ?
            ''',
            tuple(params)
        )
        rows = c.fetchall()
        return _extract_concepts_from_tag_values([row[0] for row in rows])
    except Exception as e:
        logging.error(f"Topic-scoped history fetch failed: {e}")
        return []
    finally:
        conn.close()

def get_recent_concepts_by_category_scope(
    categories: Any,
    source_material: Optional[str] = None,
    limit: int = 100
) -> List[str]:
    """Fallback history fetch using category scope."""
    clean_categories = _dedupe_topics(categories)
    if not clean_categories:
        return []

    safe_limit = max(1, int(limit or 1))
    conn = get_db_connection()
    try:
        c = conn.cursor()
        where_clauses = []
        params: List[Any] = []
        if source_material:
            where_clauses.append("source_material = ?")
            params.append(source_material)

        placeholders = ",".join(["?"] * len(clean_categories))
        where_clauses.append(f"category IN ({placeholders})")
        params.extend(clean_categories)
        params.append(safe_limit)

        query = "SELECT tags FROM questions"
        if where_clauses:
            query += f" WHERE {' AND '.join(where_clauses)}"
        query += " ORDER BY id DESC LIMIT ?"

        c.execute(query, tuple(params))
        rows = c.fetchall()
        return _extract_concepts_from_tag_values([row[0] for row in rows])
    except Exception as e:
        logging.error(f"Category-scoped history fetch failed: {e}")
        return []
    finally:
        conn.close()

def _extract_concept_tag(tags: Any) -> Optional[str]:
    tags_list = tags
    if isinstance(tags_list, str):
        tags_list = safe_json_parse(tags_list, [])
    if not isinstance(tags_list, list):
        return None
    for tag in tags_list:
        if isinstance(tag, str) and tag.startswith("concept:"):
            return tag.replace("concept:", "").strip()
    return None

def _extract_correct_answer_text(options: Any, correct_answer_index: Any) -> Optional[str]:
    if options is None:
        return None
    opts = options
    if isinstance(opts, str):
        opts = safe_json_parse(opts, [])
    if not isinstance(opts, list):
        return None
    if correct_answer_index is None:
        return None
    try:
        idx = int(correct_answer_index)
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx >= len(opts):
        return None
    opt = opts[idx]
    if isinstance(opt, dict):
        return (opt.get("text") or "").strip()
    return str(opt).strip()

def _extract_roman_statements(question_text: Optional[str]) -> Dict[str, str]:
    if not question_text:
        return {}
    text = question_text.replace("\r\n", "\n").replace("\r", "\n")
    pattern = re.compile(
        r"(?s)(?:^|\n)\s*(I|II|III|IV|V)\s*[\.\)]\s*(.*?)(?=(?:\n\s*(?:I|II|III|IV|V)\s*[\.\)])|$)"
    )
    statements: Dict[str, str] = {}
    for numeral, stmt in pattern.findall(text):
        cleaned = re.sub(r"\s+", " ", stmt).strip()
        if cleaned:
            statements[numeral] = cleaned
    return statements

def _extract_roman_tokens(answer_text: str) -> List[str]:
    if not answer_text:
        return []
    tokens = re.findall(r"\b(IV|III|II|I|V)\b", answer_text, flags=re.IGNORECASE)
    return [t.upper() for t in tokens]

def _expand_roman_answer_text(question_text: Optional[str], answer_text: str) -> str:
    if not question_text or not answer_text:
        return answer_text
    statements = _extract_roman_statements(question_text)
    if not statements:
        return answer_text
    tokens = _extract_roman_tokens(answer_text)
    if not tokens:
        return answer_text
    if not all(tok in statements for tok in tokens):
        return answer_text
    seen = set()
    expanded: List[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        expanded.append(statements.get(tok, tok))
    if not expanded:
        return answer_text
    return " / ".join(expanded)

def build_qa_signature(
    question_text: Optional[str],
    options: Any,
    correct_answer_index: Any,
    tags: Any
) -> Optional[str]:
    answer_text = _extract_correct_answer_text(options, correct_answer_index)
    if not answer_text:
        return None
    answer_text = _expand_roman_answer_text(question_text, answer_text)
    concept_text = _extract_concept_tag(tags)
    base_text = concept_text or (question_text or "")
    if not base_text.strip():
        return None
    return f"{normalize_text(base_text)}||{normalize_text(answer_text)}"

def build_qa_tag(
    question_text: Optional[str],
    options: Any,
    correct_answer_index: Any,
    tags: Any
) -> Optional[str]:
    answer_text = _extract_correct_answer_text(options, correct_answer_index)
    if not answer_text:
        return None
    answer_text = _expand_roman_answer_text(question_text, answer_text)
    concept_text = _extract_concept_tag(tags)
    base_text = concept_text or (question_text or "")
    if not base_text.strip():
        return None
    base_text = base_text.strip()
    if len(base_text) > 120:
        base_text = base_text[:120].rstrip()
    return f"qa:concept={base_text}|answer={answer_text.strip()}"

def find_duplicate_qa_signature(
    source_material: str,
    category: str,
    qa_signature: str,
    *,
    category_prefix: Optional[str] = None,
    limit: int = 600
) -> Optional[int]:
    if not source_material or not category or not qa_signature:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if category_prefix:
            c.execute(
                "SELECT id, question_text, options, correct_answer_index, tags FROM questions "
                "WHERE source_material = ? AND category LIKE ? ORDER BY id DESC LIMIT ?",
                (source_material, f"{category_prefix}%", limit)
            )
        else:
            c.execute(
                "SELECT id, question_text, options, correct_answer_index, tags FROM questions "
                "WHERE source_material = ? AND category = ? ORDER BY id DESC LIMIT ?",
                (source_material, category, limit)
            )
        rows = c.fetchall()

        if not rows:
            return None

        for row in rows:
            existing_sig = build_qa_signature(
                row[1], row[2], row[3], row[4]
            )
            if existing_sig and existing_sig == qa_signature:
                return row[0]
        return None
    except Exception as e:
        logging.error(f"QA signature dedup check failed: {e}")
        return None
    finally:
        conn.close()

def get_topics_for_category(source_material_filter: Optional[str], category_filter: str) -> List[str]:
    """Map a category name to its topic list from the library JSON."""
    if not category_filter:
        return []

    library = get_library_structure()
    if not library:
        return []

    category_variants = {normalize_text(v) for v in get_variants(category_filter)}

    def matches_category(cat: str) -> bool:
        return cat and normalize_text(cat) in category_variants

    def collect_from_source(source_name: str) -> List[str]:
        source_data = library.get(source_name)
        if not source_data:
            return []
        topics = []
        for t in source_data.get("topics", []):
            category = t.get("category", "")
            if matches_category(category):
                topic_name = t.get("topic")
                if topic_name:
                    topics.append(topic_name)
        return topics

    if source_material_filter:
        # Try direct match first, then fall back to case-insensitive search.
        topics = collect_from_source(source_material_filter)
        if topics:
            return topics
        for source_name in library.keys():
            if normalize_text(source_name) == normalize_text(source_material_filter):
                return collect_from_source(source_name)

    # No source filter; aggregate across all sources.
    topics = []
    for source_name in library.keys():
        topics.extend(collect_from_source(source_name))
    return topics

def get_next_card(
    user_id=1,
    topic_filter=None,
    source_material_filter=None,
    category_filter=None,
    mode="standard"
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    now = datetime.now()
    
    def build_where_clause(prefix=""):
        clauses = []
        params = []

        if topic_filter:
            variants = get_variants(topic_filter)
            placeholders = ",".join(["?"] * len(variants))
            clauses.append(f"{prefix}topic IN ({placeholders})")
            params.extend(variants)

        if source_material_filter:
            variants = get_variants(source_material_filter)
            placeholders = ",".join(["?"] * len(variants))
            clauses.append(f"{prefix}source_material IN ({placeholders})")
            params.extend(variants)

        if category_filter:
            category_variants = get_variants(category_filter)
            topic_list = get_topics_for_category(source_material_filter, category_filter)
            or_clauses = []
            if category_variants:
                placeholders = ",".join(["?"] * len(category_variants))
                or_clauses.append(f"{prefix}category IN ({placeholders})")
                params.extend(category_variants)
            if topic_list:
                placeholders = ",".join(["?"] * len(topic_list))
                or_clauses.append(f"{prefix}topic IN ({placeholders})")
                params.extend(topic_list)
            if or_clauses:
                clauses.append("(" + " OR ".join(or_clauses) + ")")

        return clauses, params

    # 1. Check Due Review (Repetitions > 0)
    if mode in ["standard", "review_only"]:
        query = '''
            SELECT q.*, r.ease_factor, r.interval, r.repetitions, r.next_review_date, r.flags, r.last_review_date
            FROM reviews r
            JOIN questions q ON r.question_id = q.id
            WHERE r.user_id = ? 
              AND r.next_review_date <= ?
              AND r.repetitions > 0
              AND (r.flags IS NULL OR r.flags NOT LIKE '%suspended%')
        '''
        params = [user_id, now]
        
        filter_clauses, filter_params = build_where_clause(prefix="q.")
        if filter_clauses:
            query += " AND " + " AND ".join(filter_clauses)
            params.extend(filter_params)
            
        query += " ORDER BY r.next_review_date ASC, RANDOM() LIMIT 1"
        
        c.execute(query, tuple(params))
        row = c.fetchone()
        if row:
            conn.close()
            return process_row(row)

    if mode == "review_only":
        conn.close()
        return None

    # 2. Check New Questions (No Review Row OR Repetitions = 0)
    # Exclude suspended cards (even if reps=0)
    query = '''
        SELECT q.*, r.ease_factor, r.interval, r.repetitions, r.next_review_date, r.flags, r.last_review_date
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        WHERE (r.question_id IS NULL OR (r.repetitions = 0 AND (r.flags IS NULL OR r.flags NOT LIKE '%suspended%')))
    '''
    params = [user_id]
    
    filter_clauses, filter_params = build_where_clause(prefix="q.")
    if filter_clauses:
        query += " AND " + " AND ".join(filter_clauses)
        params.extend(filter_params)
        
    if mode == "latest":
        query += " ORDER BY q.created_at DESC, q.id DESC LIMIT 1"
    else:
        query += " ORDER BY RANDOM() LIMIT 1"
    
    c.execute(query, tuple(params))
    row = c.fetchone()
    conn.close()
    
    if row:
        d = process_row(row)
        # If LEFT JOIN returned NULLs for review data, set defaults
        if d.get('repetitions') is None:
            d['ease_factor'] = 2.5
            d['interval'] = 0
            d['repetitions'] = 0
            d['next_review_date'] = None
            d['last_review_date'] = None
        else:
             # Ensure explicit 0 if it came back as 0 (just to be safe, though DB does it)
             pass
             
        return d
        
    return None

def update_card_stats(question_id: int, review_data: Dict[str, Any], user_id: int = 1):
    """
    Update review state in DB.
    review_data should contain: interval, ease_factor, repetitions, next_review_date
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT 1 FROM reviews WHERE question_id = ? AND user_id = ?", (question_id, user_id))
    exists = c.fetchone()
    
    if exists:
        c.execute('''
            UPDATE reviews
            SET interval = ?, ease_factor = ?, repetitions = ?, next_review_date = ?, last_review_date = ?
            WHERE question_id = ? AND user_id = ?
        ''', (
            review_data['interval'], 
            review_data['ease_factor'], 
            review_data['repetitions'], 
            review_data['next_review_date'], 
            datetime.now(), 
            question_id, 
            user_id
        ))
    else:
        c.execute('''
            INSERT INTO reviews (question_id, user_id, interval, ease_factor, repetitions, next_review_date, last_review_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            question_id, 
            user_id, 
            review_data['interval'], 
            review_data['ease_factor'], 
            review_data['repetitions'], 
            review_data['next_review_date'], 
            datetime.now()
        ))
        
    conn.commit()
    conn.close()

def get_library_structure():
    """Reads the JSON taxonomy."""
    try:
        with open(LIBRARY_JSON_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_topic_question_counts() -> Dict[str, int]:
    """Returns a dictionary mapping topic names to their question counts."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT topic, COUNT(*) as count FROM questions GROUP BY topic")
        rows = c.fetchall()
        return {row['topic']: row['count'] for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()

def get_topic_question_counts_by_source() -> Dict[tuple, int]:
    """Returns a dictionary mapping (source, topic) to their question counts."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT source_material, topic, COUNT(*) as count FROM questions GROUP BY source_material, topic")
        rows = c.fetchall()
        return {(row['source_material'], row['topic']): row['count'] for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()

def normalize_turkish(text: str, aggressive: bool = False) -> str:
    """
    Properly handles Turkish text normalization.
    Inlined from utils.text_processing to remove dependency.
    """
    if not text:
        return ""
    
    # Turkish-specific case conversion
    # İ -> i, I -> ı for proper lowercase
    translation_table = str.maketrans("İI", "iı")
    result = text.translate(translation_table).lower()
    
    if aggressive:
        # Remove special characters except alphanumeric and spaces
        result = re.sub(r'[^\w\s]', '', result)
        # Collapse whitespace
        result = re.sub(r'\s+', ' ', result).strip()
    
    return result

def normalize_topic_name(conn, proposed_topic: str, source_material: str = None, main_header: str = None) -> str:
    """
    Checks if a similar topic already exists in the database OR in the library.
    Returns the canonical topic name if a match is found.
    Adapted for new backend structure.
    """
    if not proposed_topic:
        return proposed_topic
    
    def simplify(text):
        import re
        text = re.sub(r'^\d+[\.\s]+', '', text)
        text = re.sub(r'[^\w\s]', ' ', text)
        return re.sub(r'\s+', ' ', text).strip().lower()

    try:
        # 1. Get topics from DB
        c = conn.cursor()
        c.execute("SELECT DISTINCT topic FROM questions WHERE topic IS NOT NULL")
        existing_topics = [r[0] for r in c.fetchall()]
        
        # 2. Add canonical topics from library JSON
        if os.path.exists(LIBRARY_JSON_PATH):
             with open(LIBRARY_JSON_PATH, "r") as f:
                 lib = json.load(f)
                 subjects_to_scan = [source_material] if source_material and source_material in lib else lib.keys()
                 
                 for subj_key in subjects_to_scan:
                     subject = lib[subj_key]
                     for t in subject.get("topics", []):
                         if main_header and t.get('category') != main_header:
                             continue
                         existing_topics.append(t['topic'])
        
        # Deduplicate
        existing_topics = list(set([t for t in existing_topics if t]))

        # Exact Match
        if proposed_topic in existing_topics:
            return proposed_topic
            
        # Basic Clean
        proposed_topic = proposed_topic.strip()
        if proposed_topic.startswith("Topic:"): proposed_topic = proposed_topic[6:].strip()
        
        if proposed_topic in existing_topics:
            return proposed_topic
            
        def eng_to_tr(text):
            mapping = {'u':'ü', 'U':'Ü', 'o':'ö', 'O':'Ö', 'c':'ç', 'C':'Ç', 's':'ş', 'S':'Ş', 'g':'ğ', 'G':'Ğ'}
            for k, v in mapping.items():
                text = text.replace(k, v)
            return text

        tr_proposed = eng_to_tr(proposed_topic)
        if tr_proposed in existing_topics:
            return tr_proposed

        # Similarity Check
        def simplify_base(text, keep_numbers=False):
            if not keep_numbers:
                text = re.sub(r'^\d+[\.\s]+', '', text) 
            text = re.sub(r'[^\w\s]', ' ', text)
            return re.sub(r'\s+', ' ', text).strip().lower()

        proposed_strict = simplify_base(proposed_topic, keep_numbers=True)
        # Check strict simplified
        for existing in existing_topics:
            if simplify_base(existing, keep_numbers=True) == proposed_strict:
                 return existing

        # Fallback: Fuzzy
        existing_simple_map = {simplify_base(t, False): t for t in existing_topics}
        matches = difflib.get_close_matches(simplify_base(proposed_topic, False), existing_simple_map.keys(), n=1, cutoff=0.8)
        if matches:
            return existing_simple_map[matches[0]]
            
        return proposed_topic 
            
    except Exception as e:
        logging.error(f"⚠️ Topic normalization failed: {e}")
        
    return proposed_topic

def _normalize_question_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.lower()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized

def _strip_part_suffix(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s*\(\s*part\s*\d+\s*\)\s*$", "", text, flags=re.IGNORECASE).strip()

def find_exact_duplicate_question_id(
    source_material: str,
    category: str,
    question_text: str,
    *,
    category_prefix: Optional[str] = None,
    limit: int = 400
) -> Optional[int]:
    if not source_material or not category or not question_text:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if category_prefix:
            c.execute(
                "SELECT id, question_text FROM questions WHERE source_material = ? AND category LIKE ? ORDER BY id DESC LIMIT ?",
                (source_material, f"{category_prefix}%", limit)
            )
        else:
            c.execute(
                "SELECT id, question_text FROM questions WHERE source_material = ? AND category = ? ORDER BY id DESC LIMIT ?",
                (source_material, category, limit)
            )
        rows = c.fetchall()

        if not rows:
            return None

        new_norm = _normalize_question_text(question_text)
        if not new_norm:
            return None

        for row in rows:
            existing_text = row[1] or ""
            existing_norm = _normalize_question_text(existing_text)
            if not existing_norm:
                continue
            if existing_norm == new_norm:
                return row[0]
        return None
    except Exception as e:
        logging.error(f"Near-duplicate text check failed: {e}")
        return None
    finally:
        conn.close()

def add_question(data: Dict[str, Any]) -> Optional[int]:
    """
    Inserts a question into the DB and initializes its review state.
    """
    conn = get_db_connection()
    c = conn.cursor()

    try:
        ensure_question_topic_links_table()

        # 1. Topic normalization disabled to avoid cross-part misassignment.
        original_topic = data.get("topic")
        normalized_topic = original_topic
        
        # Deduplication Check (concept + answer pair)
        tags_list = data.get("tags", [])
        qa_signature = build_qa_signature(
            data.get("question_text"),
            data.get("options"),
            data.get("correct_answer_index"),
            tags_list
        )

        # Strict near-duplicate text check per category
        category = data.get("category")
        source_material = data.get("source_material")
        question_text = data.get("question_text")
        if qa_signature and source_material and category:
            base_category = _strip_part_suffix(category)
            if base_category and base_category != category:
                match_id = find_duplicate_qa_signature(
                    source_material,
                    category,
                    qa_signature,
                    category_prefix=base_category
                )
            else:
                match_id = find_duplicate_qa_signature(
                    source_material,
                    category,
                    qa_signature
                )
            if match_id:
                logging.info(
                    "Skipping duplicate concept+answer in category scope "
                    f"(matched id {match_id})."
                )
                conn.close()
                return None

        # QA Tag Generation Removed to prevent UI clutter
        # We now compute signatures dynamically during retrieval.
        # if qa_tag: ... removed
        if source_material and category and question_text:
            base_category = _strip_part_suffix(category)
            if base_category and base_category != category:
                match_id = find_exact_duplicate_question_id(
                    source_material,
                    category,
                    question_text,
                    category_prefix=base_category
                )
            else:
                match_id = find_exact_duplicate_question_id(
                    source_material,
                    category,
                    question_text
                )
            if match_id:
                logging.info(
                    "Skipping near-duplicate question_text in category scope "
                    f"(matched id {match_id})."
                )
                conn.close()
                return None
        
        # Insert Question
        c.execute('''
            INSERT INTO questions (source_material, category, topic, question_text, options, correct_answer_index, explanation_data, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        ''', (
            source_material,
            category,
            normalized_topic,
            question_text,
            json.dumps(data.get("options")),
            data.get("correct_answer_index"),
            json.dumps(data.get("explanation_data")),
            json.dumps(data.get("tags"))
        ))
        
        inserted = c.fetchone()
        question_id = None
        if inserted:
            try:
                question_id = int(inserted["id"])
            except Exception:
                question_id = int(inserted[0])

        topic_links = _dedupe_topics(data.get("topic_links"))
        normalized_topic_clean = _normalize_topic_value(normalized_topic)
        if normalized_topic_clean and normalized_topic_clean not in topic_links:
            topic_links.insert(0, normalized_topic_clean)
        if topic_links:
            link_question_to_topics(
                question_id=question_id,
                topics=topic_links,
                source_material=source_material,
                category=category,
                conn=conn
            )
        
        # Initialize Review State (User 1)
        c.execute('''
            INSERT INTO reviews (question_id, user_id, ease_factor, interval, repetitions, next_review_date, last_review_date)
            VALUES (?, 1, 2.5, 0, 0, ?, ?)
        ''', (question_id, datetime.now(), None))
        
        conn.commit()
        return question_id
    except Exception as e:
        print(f"Error adding question: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def check_concept_exists(concept_text: str, topic: str) -> bool:
    """
    Checks if a question with this concept already exists in the given topic (fuzzy match).
    """
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # 1. Exact Tag Match (Fast)
        c.execute("SELECT id FROM questions WHERE topic = ? AND tags LIKE ?", (topic, f'%{concept_text}%'))
        if c.fetchone():
            return True
            
        # 2. Fuzzy Text Match (Expensive)
        c.execute("SELECT question_text FROM questions WHERE topic = ? ORDER BY id DESC LIMIT 50", (topic,))
        rows = c.fetchall()
        
        for r in rows:
            similarity = difflib.SequenceMatcher(None, concept_text, r['question_text']).ratio()
            if similarity > 0.8:
                return True
                
        return False
    except Exception as e:
        logging.error(f"Dedup check failed: {e}")
        return False
    finally:
        conn.close()

def get_topic_concepts_data(topic: str) -> List[Dict[str, Any]]:
    """
    Fetches all concepts for a topic, effectively joining with embeddings.
    Returns list of dicts: {'id': id, 'concept': text, 'embedding': [floats] or None}
    """
    conn = get_db_connection()
    try:
        # Get all concept tags from questions
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, tags, question_text, options, correct_answer_index FROM questions WHERE topic = ?", (topic,))
        rows = c.fetchall()
        
        # Get existing embeddings
        c.execute("SELECT concept_text, embedding_json FROM concept_embeddings WHERE topic = ?", (topic,))
        emb_rows = c.fetchall()
        emb_map = {r['concept_text']: json.loads(r['embedding_json']) for r in emb_rows}
        
        results = []
        seen_concepts = set()
        
        for r in rows:
            # Reconstruct QA Signature (Answer-First Format: Answer: ... | Question: ...)
            q_text = r['question_text'] or ""
            answer_text = _extract_correct_answer_text(r['options'], r['correct_answer_index'])
            if not answer_text:
                continue
                
            # Note: We do NOT include concept name in this signature anymore
            signature = f"Answer: {answer_text} | Question: {q_text}"
            
            if signature and signature not in seen_concepts:
                seen_concepts.add(signature)
                results.append({
                    'id': r['id'],
                    'concept': signature, # This is the key for embedding lookup
                    'embedding': emb_map.get(signature)
                })
        return results
    except Exception as e:
        logging.error(f"Failed to fetch topic concepts: {e}")
        return []
    finally:
        conn.close()

def get_category_concepts_data(source_material: str, category: str) -> List[Dict[str, Any]]:
    """
    Fetches all concepts for a given CATEGORY (and Source Material), joining with embeddings.
    Used for wider deduplication scope (e.g. check duplicate across entire 'Kardiyoloji' not just 'MI' topic).
    """
    conn = get_db_connection()
    try:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # 1. Get all questions in this category
        c.execute("SELECT id, topic, question_text, options, correct_answer_index FROM questions WHERE source_material = ? AND category = ?", 
                 (source_material, category))
        rows = c.fetchall()
        
        if not rows:
            return []
            
        # 2. Extract unique topics involved
        topics = set(r['topic'] for r in rows)
        
        # 3. Get existing embeddings for ALL these topics
        # SQLite doesn't support arrays in IN clause easily for many items, but topics typically < 20 per category
        if topics:
            placeholders = ','.join(['?'] * len(topics))
            query = f"SELECT topic, concept_text, embedding_json FROM concept_embeddings WHERE topic IN ({placeholders})"
            c.execute(query, list(topics))
            emb_rows = c.fetchall()
        else:
            emb_rows = []
            
        # Map: topic -> concept -> embedding_json
        # Or simpler: concept -> embedding_json (assuming concept text is unique identifier across topics, which is safe enough)
        # Better: (topic, concept) -> embedding
        emb_map = {}
        for r in emb_rows:
            key = (r['topic'], r['concept_text'])
            emb_map[key] = json.loads(r['embedding_json'])
            
        results = []
        seen_concepts = set() # To avoid checking same concept twice if multiple questions have it
        
        for r in rows:
            current_topic = r['topic']
            
            # Reconstruct QA Signature
            q_text = r['question_text'] or ""
            answer_text = _extract_correct_answer_text(r['options'], r['correct_answer_index'])
            if not answer_text:
                continue
                
            signature = f"Answer: {answer_text} | Question: {q_text}"
            
            # Dedupe within this result set
            if signature and signature not in seen_concepts:
                seen_concepts.add(signature)
                
                # Find embedding
                # Try exact topic match first
                emb = emb_map.get((current_topic, signature))
                
                # If not found, maybe same QA exists in another topic in this category? 
                if not emb:
                        # Search in other topics (fallback)
                        for (t_key, c_key), e_val in emb_map.items():
                            if c_key == signature:
                                emb = e_val
                                break
                
                results.append({
                    'id': r['id'],
                    'topic': current_topic, # Needed for saving new embedding
                    'concept': signature,
                    'embedding': emb
                })
        return results
    except Exception as e:
        logging.error(f"Failed to fetch category concepts: {e}")
        return []
    finally:
        conn.close()

def save_concept_embedding(topic: str, concept: str, embedding: List[float]):
    """Saves a concept embedding to the database."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO concept_embeddings (topic, concept_text, embedding_json)
            VALUES (?, ?, ?)
        ''', (topic, concept, json.dumps(embedding)))
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to save embedding for {concept}: {e}")
    finally:
        conn.close()

def get_all_visual_tags() -> List[str]:
    """
    Fetches all distinct tags starting with 'visual:' from the database.
    Used to prompt the model with existing schemas to encourage reuse.
    """
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # SQLite doesn't have a native JSON array unnesting until recent versions.
        # We'll fetch all tags and filter in Python for safety/compatibility.
        c.execute("SELECT tags FROM questions WHERE tags LIKE '%visual:%'")
        rows = c.fetchall()
        
        visual_tags = set()
        for row in rows:
            tags_list = safe_json_parse(row['tags'], [])
            for t in tags_list:
                if t.startswith("visual:"):
                    visual_tags.add(t)
        
        return sorted(list(visual_tags))
    except Exception as e:
        logging.error(f"Failed to fetch visual tags: {e}")
        return []
    finally:
        conn.close()


# ─── Prompt Templates ───────────────────────────────────────────────

def ensure_prompt_templates_table():
    """Create prompt_templates table if it doesn't exist."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if get_db_engine() == "postgres":
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    sections TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            c.execute('''
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sections TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    finally:
        conn.close()


def get_prompt_templates() -> List[Dict[str, Any]]:
    """Return all saved prompt templates."""
    ensure_prompt_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, sections, is_default, created_at, updated_at FROM prompt_templates ORDER BY updated_at DESC")
        rows = c.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "name": row["name"],
                "sections": safe_json_parse(row["sections"], {}),
                "is_default": bool(row["is_default"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            })
        return results
    finally:
        conn.close()


def save_prompt_template(name: str, sections: dict, is_default: bool = False) -> int:
    """Insert a new prompt template and return its id."""
    ensure_prompt_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        now = datetime.now()
        if is_default:
            c.execute("UPDATE prompt_templates SET is_default = 0")
        c.execute(
            "INSERT INTO prompt_templates (name, sections, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (name, json.dumps(sections, ensure_ascii=False), int(is_default), now, now),
        )
        row = c.fetchone()
        conn.commit()
        if not row:
            return 0
        try:
            return int(row["id"])
        except Exception:
            return int(row[0])
    finally:
        conn.close()


def update_prompt_template(template_id: int, name: str, sections: dict, is_default: bool = False) -> bool:
    """Update an existing prompt template."""
    ensure_prompt_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        now = datetime.now()
        if is_default:
            c.execute("UPDATE prompt_templates SET is_default = 0")
        c.execute(
            "UPDATE prompt_templates SET name = ?, sections = ?, is_default = ?, updated_at = ? WHERE id = ?",
            (name, json.dumps(sections, ensure_ascii=False), int(is_default), now, template_id),
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def delete_prompt_template(template_id: int) -> bool:
    """Delete a prompt template by id."""
    ensure_prompt_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM prompt_templates WHERE id = ?", (template_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


# ─── Per-Section Favorites ──────────────────────────────────────────

def ensure_section_favorites_table():
    """Create section_favorites table if it doesn't exist."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if get_db_engine() == "postgres":
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS section_favorites (
                    id BIGSERIAL PRIMARY KEY,
                    section_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            c.execute('''
                CREATE TABLE IF NOT EXISTS section_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    section_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    finally:
        conn.close()


def get_section_favorites(section_key: str = None) -> List[Dict[str, Any]]:
    """Return section favorites, optionally filtered by section_key."""
    ensure_section_favorites_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if section_key:
            c.execute("SELECT id, section_key, name, content, created_at FROM section_favorites WHERE section_key = ? ORDER BY created_at DESC", (section_key,))
        else:
            c.execute("SELECT id, section_key, name, content, created_at FROM section_favorites ORDER BY section_key, created_at DESC")
        rows = c.fetchall()
        return [{"id": r["id"], "section_key": r["section_key"], "name": r["name"], "content": r["content"], "created_at": str(r["created_at"])} for r in rows]
    finally:
        conn.close()


def save_section_favorite(section_key: str, name: str, content: str) -> int:
    """Insert a new section favorite and return its id."""
    ensure_section_favorites_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO section_favorites (section_key, name, content, created_at) VALUES (?, ?, ?, ?) RETURNING id",
            (section_key, name, content, datetime.now()),
        )
        row = c.fetchone()
        conn.commit()
        if not row:
            return 0
        try:
            return int(row["id"])
        except Exception:
            return int(row[0])
    finally:
        conn.close()


def delete_section_favorite(fav_id: int) -> bool:
    """Delete a section favorite by id."""
    ensure_section_favorites_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM section_favorites WHERE id = ?", (fav_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


# ─── Difficulty Templates ──────────────────────────────────────────

def ensure_difficulty_templates_table():
    """Create difficulty_templates table if it doesn't exist."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if get_db_engine() == "postgres":
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS difficulty_templates (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    levels TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            c.execute('''
                CREATE TABLE IF NOT EXISTS difficulty_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    levels TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    finally:
        conn.close()


def get_difficulty_templates() -> List[Dict[str, Any]]:
    """Return all saved difficulty templates."""
    ensure_difficulty_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, levels, is_default, created_at, updated_at FROM difficulty_templates ORDER BY updated_at DESC")
        rows = c.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "name": row["name"],
                "levels": safe_json_parse(row["levels"], {}),
                "is_default": bool(row["is_default"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            })
        return results
    finally:
        conn.close()


def save_difficulty_template(name: str, levels: dict, is_default: bool = False) -> int:
    """Insert a new difficulty template and return its id."""
    ensure_difficulty_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        now = datetime.now()
        if is_default:
            c.execute("UPDATE difficulty_templates SET is_default = 0")
        c.execute(
            "INSERT INTO difficulty_templates (name, levels, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (name, json.dumps(levels, ensure_ascii=False), int(is_default), now, now),
        )
        row = c.fetchone()
        conn.commit()
        if not row:
            return 0
        try:
            return int(row["id"])
        except Exception:
            return int(row[0])
    finally:
        conn.close()


def update_difficulty_template(template_id: int, name: str, levels: dict, is_default: bool = False) -> bool:
    """Update an existing difficulty template."""
    ensure_difficulty_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        now = datetime.now()
        if is_default:
            c.execute("UPDATE difficulty_templates SET is_default = 0")
        c.execute(
            "UPDATE difficulty_templates SET name = ?, levels = ?, is_default = ?, updated_at = ? WHERE id = ?",
            (name, json.dumps(levels, ensure_ascii=False), int(is_default), now, template_id),
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def delete_difficulty_template(template_id: int) -> bool:
    """Delete a difficulty template by id."""
    ensure_difficulty_templates_table()
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM difficulty_templates WHERE id = ?", (template_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()
