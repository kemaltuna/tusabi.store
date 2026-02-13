import sqlite3
import json
import os
import difflib
from datetime import datetime
import logging
from pathlib import Path
def normalize_turkish(text: str) -> str:
    """Properly lowercases Turkish strings handling I/ı and İ/i."""
    if not text:
        return ""
    translation_table = str.maketrans("İI", "iı")
    return text.translate(translation_table).lower()

# Path configuration - use shared/data/ after app separation
_ROOT_DIR = Path(__file__).parent
DB_PATH = str(_ROOT_DIR / "shared" / "data" / "quiz_v2.db")
TAXONOMY_PATH = str(_ROOT_DIR / "shared" / "data" / "taxonomy.json")

def get_db_connection():
    # Only connect if the directory exists, otherwise it might fail or create weird paths if init_db wasn't run
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize all database tables."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Questions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_material TEXT,
            topic TEXT,
            question_text TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_answer_index INTEGER NOT NULL,
            explanation_data TEXT,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Reviews table (user-specific spaced repetition state)
    c.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            question_id INTEGER,
            user_id INTEGER,
            ease_factor REAL DEFAULT 2.5,
            interval REAL DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review_date TIMESTAMP,
            last_review_date TIMESTAMP,
            flags TEXT DEFAULT '[]',
            PRIMARY KEY (question_id, user_id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Sessions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Highlights table
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_highlights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question_id INTEGER,
            text_content TEXT,
            context_type TEXT,
            word_index INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Content requests table (Soru Hazırlat)
    c.execute('''
        CREATE TABLE IF NOT EXISTS content_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            request_type TEXT,
            content_path TEXT,
            description TEXT,
            target_topic TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Visual explanations table
    c.execute('''
        CREATE TABLE IF NOT EXISTS visual_explanations (
            question_id INTEGER PRIMARY KEY,
            image_path TEXT,
            prompt TEXT,
            verification_status TEXT DEFAULT 'pending',
            user_request_note TEXT,
            user_feedback TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')
    
    # Extended explanations table
    c.execute('''
        CREATE TABLE IF NOT EXISTS extended_explanations (
            question_id INTEGER PRIMARY KEY,
            content TEXT,
            verification_status TEXT DEFAULT 'pending',
            user_request_note TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')
    
    # Content feedback table
    c.execute('''
        CREATE TABLE IF NOT EXISTS content_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            section TEXT,
            selected_text TEXT,
            user_note TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')
    
    # User settings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # User Sessions for persistence
    c.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
                 user_id INTEGER PRIMARY KEY,
                 active_page TEXT,
                 active_topic TEXT,
                 active_mode TEXT,
                 current_card_id INTEGER,
                 last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                 )''')

    conn.commit()
    conn.close()

# --- Topic Normalization Helper ---
def normalize_topic_name(conn, proposed_topic, source_material=None, main_header=None):
    """
    Checks if a similar topic already exists in the database OR in the library.
    Matches are found by normalizing both strings (lowercasing, removing special chars/prefixes).
    Returns the canonical topic name if a match is found.
    """
    if not proposed_topic:
        return proposed_topic
    
    # CRITICAL: Never fuzzy-match Chunk topics
    def simplify(text):
        """Removes numbers, punctuation, and lowercases for comparison."""
        import re
        # Remove leading numbers/dots/spaces (e.g., "05. ", "01 ")
        text = re.sub(r'^\d+[\.\s]+', '', text)
        # Remove all non-alphanumeric chars (keep spaces)
        text = re.sub(r'[^\w\s]', ' ', text)
        # Collapse spaces
        return re.sub(r'\s+', ' ', text).strip().lower()

    try:
        # 1. Get topics from DB
        c = conn.cursor()
        c.execute("SELECT DISTINCT topic FROM questions WHERE topic IS NOT NULL")
        existing_topics = [r[0] for r in c.fetchall()]
        
        # 2. Add canonical topics from library JSON
        lib_json = TAXONOMY_PATH.replace("taxonomy.json", "medquiz_library.json")
        if os.path.exists(lib_json):
             with open(lib_json, "r") as f:
                 lib = json.load(f)
                 # SCOPED LOADING: Only load topics relevant to the context

                 subjects_to_scan = [source_material] if source_material and source_material in lib else lib.keys()
                 
                 for subj_key in subjects_to_scan:
                     subject = lib[subj_key]
                     for t in subject.get("topics", []):
                         # If main_header is provided, enforce strictly
                         if main_header and t.get('category') != main_header:
                             continue
                         existing_topics.append(t['topic'])
        
        # Deduplicate while preserving case
        existing_topics = list(set([t for t in existing_topics if t]))

        # Check exact match first
        if proposed_topic in existing_topics:
            return proposed_topic
            
        # 0. Basic Clean
        proposed_topic = proposed_topic.strip()
        if proposed_topic.startswith("Topic:"): proposed_topic = proposed_topic[6:].strip()
        if proposed_topic.startswith('"') and proposed_topic.endswith('"'): proposed_topic = proposed_topic[1:-1].strip()
        if proposed_topic.startswith("'") and proposed_topic.endswith("'"): proposed_topic = proposed_topic[1:-1].strip()

        # Check exact match first
        if proposed_topic in existing_topics:
            return proposed_topic
            
        def eng_to_tr(text):
            # Safe mappings only. skipped 'i'/'I' because they are ambiguous (Silgi vs Sikik)
            # Assuming 'i' in input matches 'i' in DB is safer than forcing 'ı'
            mapping = {'u':'ü', 'U':'Ü', 'o':'ö', 'O':'Ö', 'c':'ç', 'C':'Ç', 's':'ş', 'S':'Ş', 'g':'ğ', 'G':'Ğ'}
            for k, v in mapping.items():
                text = text.replace(k, v)
            return text

        # 1. Apply Eng->Tr conversion globally to create a normalized variant
        tr_proposed = eng_to_tr(proposed_topic)
        
        # Check strict TR match
        if tr_proposed in existing_topics:
            logging.info(f"✨ Topic Normalization (Eng->Tr): '{proposed_topic}' -> '{tr_proposed}'")
            return tr_proposed

        # Helper for loose simplified (NO NUMBERS) vs strict simplified (WITH NUMBERS)
        def simplify_base(text, keep_numbers=False):
            import re
            if not keep_numbers:
                # Remove leading numbers/dots/spaces (e.g., "05. ", "01 ")
                text = re.sub(r'^\d+[\.\s]+', '', text) 
            
            # Normalize dots/punctuation to spaces
            text = re.sub(r'[^\w\s]', ' ', text)
            # Collapse spaces
            return re.sub(r'\s+', ' ', text).strip().lower()

        # Prepare variants
        # We test both the specific TR input and the raw input (just in case)
        proposed_strict = simplify_base(proposed_topic, keep_numbers=True)
        proposed_strict_tr = simplify_base(tr_proposed, keep_numbers=True)
        
        proposed_loose = simplify_base(proposed_topic, keep_numbers=False)
        proposed_loose_tr = simplify_base(tr_proposed, keep_numbers=False)
        
        # 2. Strict Simplified Match (Preserving Numbers)
        #    Prioritizes "02 Enzimler" over "07 Enzimler"
        for existing in existing_topics:
            exist_strict = simplify_base(existing, keep_numbers=True)
            if proposed_strict == exist_strict:
                 logging.info(f"✨ Topic Normalization (Strict-Simple): '{proposed_topic}' -> '{existing}'")
                 return existing
            if proposed_strict_tr == exist_strict:
                 logging.info(f"✨ Topic Normalization (Strict-Simple-Tr): '{proposed_topic}' -> '{existing}'")
                 return existing

        # 3. Loose Simplified Match (No Numbers) & Eng->Tr variants
        for existing in existing_topics:
            exist_loose = simplify_base(existing, keep_numbers=False)
            if proposed_loose == exist_loose:
                logging.info(f"✨ Topic Normalization (Loose-Simple): '{proposed_topic}' -> '{existing}'")
                return existing
            if proposed_loose_tr == exist_loose:
                logging.info(f"✨ Topic Normalization (Loose-Simple-Tr): '{proposed_topic}' -> '{existing}'")
                return existing

        # 4. SUBSTRING match (Strict length > 5)
        #    Check both Original and TR variants
        if len(proposed_loose) > 5:
            # Sort existing topics by length (descending) to match LONGEST substring first
            sorted_existing = sorted(existing_topics, key=len, reverse=True)
            
            for existing in sorted_existing:
                exist_loose = simplify_base(existing, keep_numbers=False)
                
                # Check forwards and backwards containment for Original
                if proposed_loose in exist_loose:
                     logging.info(f"✨ Topic Normalization (Forward-Substring): '{proposed_topic}' -> '{existing}'")
                     return existing
                if exist_loose in proposed_loose:
                     logging.info(f"✨ Topic Normalization (Reverse-Substring): '{proposed_topic}' -> '{existing}'")
                     return existing
                     
                # Check forwards and backwards containment for TR Variant
                if proposed_loose_tr in exist_loose:
                     logging.info(f"✨ Topic Normalization (Forward-Substring-Tr): '{proposed_topic}' -> '{existing}'")
                     return existing
                if exist_loose in proposed_loose_tr:
                     logging.info(f"✨ Topic Normalization (Reverse-Substring-Tr): '{proposed_topic}' -> '{existing}'")
                     return existing

        # 5. Fallback: Fuzzy
        existing_simple_map = {simplify_base(t, False): t for t in existing_topics}
        
        # Try original
        matches = difflib.get_close_matches(proposed_loose, existing_simple_map.keys(), n=1, cutoff=0.8)
        if matches:
            canonical = existing_simple_map[matches[0]]
            logging.info(f"✨ Topic Normalization (Fuzzy-Simple): '{proposed_topic}' -> '{canonical}'")
            return canonical
            
        # Try TR variant
        if proposed_loose_tr != proposed_loose:
            matches_tr = difflib.get_close_matches(proposed_loose_tr, existing_simple_map.keys(), n=1, cutoff=0.8)
            if matches_tr:
                canonical = existing_simple_map[matches_tr[0]]
                logging.info(f"✨ Topic Normalization (Fuzzy-Simple-Tr): '{proposed_topic}' -> '{canonical}'")
                return canonical
        
        logging.warning(f"⚠️ No normalization match for: '{proposed_topic}'")
        return proposed_topic # Return original if failed
            
    except Exception as e:
        logging.error(f"⚠️ Topic normalization failed: {e}")
        
    return proposed_topic

# --- Content Request (Soru Hazırlat) Utils ---

def add_question(data):
    """
    Inserts a question into the DB and initializes its review state.
    Data matches the JSON structure:
    {
        "source_material": ...,
        "topic": ...,
        "question_text": ...,
        "options": [...],
        "correct_answer_index": ...,
        "explanation_data": {...},
        "tags": [...]
    }
    """
    conn = get_db_connection()
    c = conn.cursor()

    try:
        # 1. Normalize Topic
        original_topic = data.get("topic")
        normalized_topic = normalize_topic_name(conn, original_topic)
        
        # Deduplication Check
        tags_list = data.get("tags", [])
        concept_tag = next((t for t in tags_list if t.startswith("concept:")), None)
        
        if concept_tag:
            # Check if this concept already exists
            c.execute("SELECT id FROM questions WHERE topic = ? AND tags LIKE ?", (normalized_topic, f'%"{concept_tag}"%',))
            existing = c.fetchone()
            if existing:
                logging.info(f"Skipping duplicate concept: {concept_tag} (Question ID: {existing['id']})")
                conn.close()
                return existing['id']
        
        # --- SOURCE NORMALIZATION START ---
        source = data.get("source_material")
        try:
            with open(TAXONOMY_PATH, "r") as f:
                taxonomy = json.load(f)
            valid_sources = taxonomy.get("sources", [])
            
            if source and source not in valid_sources:
                source_input_norm = normalize_turkish(source, aggressive=True).lower().replace("_","").replace(" ","")
                for vs in valid_sources:
                    vs_norm = normalize_turkish(vs, aggressive=True).lower().replace("_","").replace(" ","")
                    if vs_norm == source_input_norm:
                        logging.info(f"✨ Source Normalization: '{source}' -> '{vs}'")
                        data['source_material'] = vs
                        break
        except Exception as e:
            logging.warning(f"Source normalization failed: {e}")
        # --- SOURCE NORMALIZATION END ---

        # Insert Question
        c.execute('''
            INSERT INTO questions (source_material, category, topic, question_text, options, correct_answer_index, explanation_data, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get("source_material"),
            data.get("category"), # Insert Category
            normalized_topic, # Used Normalized Topic
            data.get("question_text"),
            json.dumps(data.get("options")),
            data.get("correct_answer_index"),
            json.dumps(data.get("explanation_data")),
            json.dumps(data.get("tags"))
        ))
        
        question_id = c.lastrowid
        
        # Initialize Review State (New card) for Admin (User 1) by default
        # Other users will get their state created on-the-fly or via logic in get_next_card
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


def submit_content_request(user_id, request_type, content_path, description, target_topic):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO content_requests (user_id, request_type, content_path, description, target_topic, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (user_id, request_type, content_path, description, target_topic))
    conn.commit()
    conn.close()

def get_user_content_requests(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM content_requests WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_pending_image_requests(user_id=None, limit=5):
    """
    Fetch pending image requests for processing.
    If user_id is None, fetches all pending requests (for admin batch processing).
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    if user_id:
        c.execute('''
            SELECT * FROM content_requests 
            WHERE user_id = ? AND request_type = 'image' AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
        ''', (user_id, limit))
    else:
        c.execute('''
            SELECT * FROM content_requests 
            WHERE request_type = 'image' AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
        ''', (limit,))
    
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_request_processed(request_id):
    """Mark a content request as processed."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE content_requests SET status = 'processed' WHERE id = ?", (request_id,))
    conn.commit()
    conn.close()

def move_to_processed(file_path):
    """
    Move a processed file to the processed/ folder.
    Returns the new path or None if file doesn't exist.
    """
    import shutil
    
    if not os.path.exists(file_path):
        return None
    
    # Create processed directory
    processed_dir = "uploads/processed"
    os.makedirs(processed_dir, exist_ok=True)
    
    # Move file
    filename = os.path.basename(file_path)
    new_path = os.path.join(processed_dir, filename)
    shutil.move(file_path, new_path)
    return new_path

def get_queue_stats(user_id=None):
    """
    Get queue statistics for display.
    Returns: {'pending': int, 'processed': int, 'total': int}
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    if user_id:
        c.execute('''
            SELECT status, COUNT(*) as count 
            FROM content_requests 
            WHERE user_id = ? AND request_type = 'image'
            GROUP BY status
        ''', (user_id,))
    else:
        c.execute('''
            SELECT status, COUNT(*) as count 
            FROM content_requests 
            WHERE request_type = 'image'
            GROUP BY status
        ''')
    
    rows = c.fetchall()
    conn.close()
    
    stats = {'pending': 0, 'processed': 0, 'total': 0}
    for row in rows:
        stats[row['status']] = row['count']
        stats['total'] += row['count']
    
    return stats

# --- Stats Updates (User Aware) ---

def get_dashboard_stats(user_id=1):
    conn = get_db_connection()
    c = conn.cursor()
    stats = {}
    now = datetime.now()
    
    # Filter reviews by user_id
    # LEFT JOIN needs a condition for user_id on reviews, but questions exist regardless.
    # We want: All questions, joined with THIS user's reviews.
    c.execute('''
        SELECT q.source_material, q.topic, q.id, r.next_review_date, r.repetitions, r.last_review_date
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
    ''', (user_id,))
    
    rows = c.fetchall()
    
    for r in rows:
        source = r['source_material'] if r['source_material'] else "Uncategorized"
        topic = r['topic']
        
        if source not in stats:
            stats[source] = {}
        
        if topic not in stats[source]:
            stats[source][topic] = {'topic': topic, 'total': 0, 'due': 0, 'learned': 0}
            
        stats[source][topic]['total'] += 1
        
        # Check review status (User Specific)
        if r['last_review_date']: # If record exists and has date
             stats[source][topic]['learned'] += 1
             
             nd = None
             if r['next_review_date']:
                 if isinstance(r['next_review_date'], str):
                     try:
                         nd = datetime.fromisoformat(r['next_review_date'])
                     except:
                         nd = datetime.max
                 else:
                     nd = r['next_review_date']
             
             if nd and nd <= now:
                 stats[source][topic]['due'] += 1
            
    conn.close()
    return stats

def get_topic_counts(source_material):
    """Returns a dict mapping topic names to question counts for a source."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT topic, COUNT(*) as count FROM questions WHERE source_material = ? GROUP BY topic", (source_material,))
    rows = c.fetchall()
    conn.close()
    return {r['topic']: r['count'] for r in rows}

    conn.close()
    return {r['topic']: r['count'] for r in rows}

def get_variants(text):
    """Generate case variants for robust matching (handling Turkish I/İ)."""
    if not text:
        return []
    variants = {text}
    variants.add(text.upper())
    variants.add(text.lower())
    # Turkish specific casing
    variants.add(text.replace('i', 'İ').upper())
    variants.add(text.replace('I', 'ı').lower())
    variants.add(text.replace('İ', 'i').lower())
    return list(variants)

def get_questions_for_duplicate_check(topic=None, source_material=None, category=None, limit=2000):
    """
    Fetches recent questions for duplicate checking.
    Returns lightweight objects: {id, question_text, correct_answer_text}
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    # Base query
    query = "SELECT id, question_text, correct_answer_index, options FROM questions"
    conditions = []
    params = []
    
    # Optional filters
    if topic:
        conditions.append("topic = ?")
        params.append(topic)
        
    if source_material:
        conditions.append("source_material = ?")
        params.append(source_material)
    
    if category:
        conditions.append("category = ?")
        params.append(category)
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    try:
        c.execute(query, tuple(params))
        rows = c.fetchall()
        
        results = []
        for r in rows:
            try:
                # Parse options to get correct answer text
                opts = json.loads(r['options'])
                idx = r['correct_answer_index']
                correct_text = "Unknown"
                
                if isinstance(opts, list) and len(opts) > 0 and 0 <= idx < len(opts):
                    selected = opts[idx]
                    if isinstance(selected, dict):
                        correct_text = selected.get('text', '')
                    else:
                        correct_text = str(selected)
                
                results.append({
                    "id": r['id'],
                    "question": r['question_text'],
                    "correct_answer": correct_text
                })
            except Exception as e:
                # Skip malformed rows
                continue
                
        return results
    except Exception as e:
        logging.error(f"Duplicate check query failed: {e}")
        return []
    finally:
        conn.close()

def get_next_card(user_id=1, topic_filter=None, source_material_filter=None, category_filter=None, mode="standard"):
    conn = get_db_connection()
    c = conn.cursor()
    now = datetime.now()
    
    # --- Dynamic Query Construction Helpers ---
    def build_where_clause(prefix=""):
        clauses = []
        params = []
        
        if topic_filter:
            variants = get_variants(topic_filter)
            placeholders = ','.join(['?'] * len(variants))
            clauses.append(f"{prefix}topic IN ({placeholders})")
            params.extend(variants)
            
        if source_material_filter:
            # Source usually doesn't need as many variants but safer to include
            variants = get_variants(source_material_filter)
            placeholders = ','.join(['?'] * len(variants))
            clauses.append(f"{prefix}source_material IN ({placeholders})")
            params.extend(variants)
            
        if category_filter:
            variants = get_variants(category_filter)
            placeholders = ','.join(['?'] * len(variants))
            clauses.append(f"{prefix}category IN ({placeholders})")
            params.extend(variants)
            
        return clauses, params

    # 1. Check Due (If mode allows)
    if mode in ["standard", "review_only"]:
        base_query = '''
            SELECT q.*, r.ease_factor, r.interval, r.repetitions, r.next_review_date, r.flags, r.last_review_date
            FROM reviews r
            JOIN questions q ON r.question_id = q.id
            WHERE r.user_id = ? 
              AND r.next_review_date <= ?
              AND (r.flags IS NULL OR r.flags NOT LIKE '%"suspended"%')
        '''
        base_params = [user_id, now]
        
        filter_clauses, filter_params = build_where_clause(prefix="q.")
        
        if filter_clauses:
            base_query += " AND " + " AND ".join(filter_clauses)
            base_params.extend(filter_params)
            
        base_query += " ORDER BY r.next_review_date ASC LIMIT 1"
        
        c.execute(base_query, tuple(base_params))
        due_card = c.fetchone()
        
        if due_card:
            return dict(due_card)
            
    # If mode is review_only and we didn't find a due card, return None
    if mode == "review_only":
        return None

    # 2. Check New (If mode allows)
    query = '''
        SELECT q.*
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        WHERE r.question_id IS NULL
    '''
    params = [user_id]
    
    filter_clauses, filter_params = build_where_clause(prefix="q.")
    
    if filter_clauses:
        query += " AND " + " AND ".join(filter_clauses)
        params.extend(filter_params)
        
    query += " LIMIT 1"
    
    c.execute(query, tuple(params))
    new_card = c.fetchone()
    
    if new_card:
        # Initialize review record on the fly? No, the App logic usually expects 'ease_factor' etc in the dict.
        # We should return the dict with default values.
        # AND we should probably insert the record now? Or wait until they confirm?
        # Let's just return dict with defaults. The `update_card_stats` logic will need to handle Insert vs Update.
        d = dict(new_card)
        d['ease_factor'] = 2.5
        d['interval'] = 0
        d['repetitions'] = 0
        d['last_review_date'] = None
        d['next_review_date'] = None
        d['flags'] = '[]'
        return d
        
    return None

def update_card_stats(question_id, new_interval, new_ease_factor, new_repetitions, next_review_date, user_id=1):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if record exists
    c.execute("SELECT 1 FROM reviews WHERE question_id = ? AND user_id = ?", (question_id, user_id))
    exists = c.fetchone()
    
    if exists:
        c.execute('''
            UPDATE reviews
            SET interval = ?, ease_factor = ?, repetitions = ?, next_review_date = ?, last_review_date = ?
            WHERE question_id = ? AND user_id = ?
        ''', (new_interval, new_ease_factor, new_repetitions, next_review_date, datetime.now(), question_id, user_id))
    else:
        c.execute('''
            INSERT INTO reviews (question_id, user_id, interval, ease_factor, repetitions, next_review_date, last_review_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (question_id, user_id, new_interval, new_ease_factor, new_repetitions, next_review_date, datetime.now()))
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

def restore_review_state(question_id, interval, ease_factor, repetitions, next_review_date, last_review_date):
    """
    Restores the review state of a card (Undo feature).
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE reviews
        SET interval = ?, ease_factor = ?, repetitions = ?, next_review_date = ?, last_review_date = ?
        WHERE question_id = ?
    ''', (interval, ease_factor, repetitions, next_review_date, last_review_date, question_id))
    conn.commit()
    conn.close()

def save_visual_explanation(question_id, image_path, prompt, status="pending", user_request_note=None):
    conn = get_db_connection()
    c = conn.cursor()
    # Upsert logic (replace if exists)
    # We need to preserve user_request_note if not provided, but INSERT OR REPLACE makes that hard.
    # Logic: If overwriting, usually we are the Agent fulfilling the request. The agent doesn't send the note back.
    # So we should probably check existence or use UPDATE for fulfillment.
    
    # Revised strategy:
    # If fulfilled (image_path provided), we update image_path, prompt, status.
    # If requested (no image), we set question_id, status='pending', user_req_note.
    
    # But to keep it simple and match original logic:
    if user_request_note is not None:
        c.execute('''
            INSERT OR REPLACE INTO visual_explanations (question_id, image_path, prompt, verification_status, created_at, user_request_note)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (question_id, image_path, prompt, status, datetime.now(), user_request_note))
    else:
        # Agent fulfilling request, try to update without losing note, or Insert if somehow missing
        # For safety, let's just do an UPDATE if exists, else Insert.
        c.execute("SELECT user_request_note FROM visual_explanations WHERE question_id = ?", (question_id,))
        row = c.fetchone()
        existing_note = row['user_request_note'] if row else None
        
        c.execute('''
            INSERT OR REPLACE INTO visual_explanations (question_id, image_path, prompt, verification_status, created_at, user_request_note)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (question_id, image_path, prompt, status, datetime.now(), existing_note))
        
    conn.commit()
    conn.close()

def request_visual_explanation(question_id, user_note):
    """
    User initiates a request. Sets status to pending and saves the note.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO visual_explanations (question_id, verification_status, user_request_note, created_at)
        VALUES (?, 'pending', ?, ?)
    ''', (question_id, user_note, datetime.now()))
    conn.commit()
    conn.close()

def get_visual_explanation(question_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM visual_explanations WHERE question_id = ?", (question_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_visual_feedback(question_id, feedback_text):
    """Adds a feedback string to the list."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_feedback FROM visual_explanations WHERE question_id = ?", (question_id,))
    row = c.fetchone()
    if row:
        current_fb = json.loads(row['user_feedback']) if row['user_feedback'] else []
        current_fb.append(feedback_text)
        c.execute("UPDATE visual_explanations SET user_feedback = ? WHERE question_id = ?", (json.dumps(current_fb), question_id))
        conn.commit()
    conn.close()
    
def update_visual_status(question_id, status):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE visual_explanations SET verification_status = ? WHERE question_id = ?", (status, question_id))
    conn.commit()
    conn.close()

def update_flags(question_id, flag, user_id=1):
    """
    Toggles a flag in the flags JSON list for a review.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if review exists for this user
    c.execute("SELECT flags FROM reviews WHERE question_id = ? AND user_id = ?", (question_id, user_id))
    row = c.fetchone()
    
    current_flags = []
    if row:
        if row['flags']:
            try:
                current_flags = json.loads(row['flags'])
            except:
                current_flags = []
    else:
        # If no review exists, we might need to create one? 
        # Usually flags are toggled on cards being viewed (so they likely have a review entry or we should create it).
        pass

    if flag in current_flags:
        current_flags.remove(flag)
    else:
        current_flags.append(flag)
        
    new_flags_json = json.dumps(current_flags)
    
    if row:
        c.execute("UPDATE reviews SET flags = ? WHERE question_id = ? AND user_id = ?", (new_flags_json, question_id, user_id))
    else:
        # Create new review record with default values + this flag
        # Defaults: interval=0, ef=2.5, reps=0, next_due=now
        c.execute('''
            INSERT INTO reviews (question_id, user_id, interval, ease_factor, repetitions, next_review_date, last_review_date, flags)
            VALUES (?, ?, 0, 2.5, 0, ?, ?, ?)
        ''', (question_id, user_id, datetime.now(), datetime.now(), new_flags_json))
        
    conn.commit()
    conn.close()
    return current_flags

# --- Extended Explanations Utils ---

def save_extended_explanation(question_id, content, status="done"):
    conn = get_db_connection()
    c = conn.cursor()
    # Preserve note
    c.execute("SELECT user_request_note FROM extended_explanations WHERE question_id = ?", (question_id,))
    row = c.fetchone()
    note = row['user_request_note'] if row else None
    
    c.execute('''
        INSERT OR REPLACE INTO extended_explanations (question_id, content, verification_status, user_request_note, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (question_id, content, status, note, datetime.now()))
    conn.commit()
    conn.close()

def request_extended_explanation(question_id, user_note):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO extended_explanations (question_id, verification_status, user_request_note, created_at)
        VALUES (?, 'pending', ?, ?)
    ''', (question_id, user_note, datetime.now()))
    conn.commit()
    conn.close()

def get_extended_explanation_data(question_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM extended_explanations WHERE question_id = ?", (question_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_extended_explanation(question_id):
    """Legacy wrapper"""
    row = get_extended_explanation_data(question_id)
    return row['content'] if row else None

def submit_content_feedback(question_id, section, selected_text, user_note):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO content_feedback (question_id, section, selected_text, user_note)
        VALUES (?, ?, ?, ?)
    ''', (question_id, section, selected_text, user_note))
    conn.commit()
    conn.close()


def get_pending_content_feedbacks():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT cf.id, cf.user_note, cf.created_at, q.question_text, q.options, q.explanation_data
        FROM content_feedback cf
        JOIN questions q ON cf.question_id = q.id
        WHERE cf.status = 'pending'
    ''')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_content_feedback_processed(feedback_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE content_feedback SET status = 'processed' WHERE id = ?", (feedback_id,))
    conn.commit()
    conn.commit()
    conn.close()

def save_setting(key, value):
    """Saves a single user setting (upsert)."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

def get_setting(key, default_value=None):
    """Retrieves a single user setting."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT value FROM user_settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default_value


def update_user_role(username, role):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
    conn.commit()
    conn.close()
    return True

def get_user_by_username(username):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    return c.fetchone()

def get_all_users():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT username, role, created_at FROM users")
    return c.fetchall()


def create_session(user_id):
    import uuid
    token = str(uuid.uuid4())
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return token

def get_user_by_session(token):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT u.* FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.token = ?
    ''', (token,))
    user = c.fetchone()
    conn.close()
    return user

def delete_session(token):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")

def get_generation_logs(limit=50):
    """
    Returns background job logs for the Generation History panel.
    Maps background_jobs table to the expected format.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT 
            id,
            status,
            payload,
            error_message as log_message,
            progress as questions_generated,
            total_items as question_count,
            created_at
        FROM background_jobs 
        WHERE type = 'generation_batch'
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    
    logs = []
    for r in rows:
        d = dict(r)
        # Extract topic from payload
        try:
            payload = json.loads(r['payload']) if r['payload'] else {}
            d['topic'] = payload.get('topic', 'Unknown')
        except:
            d['topic'] = 'Unknown'
        logs.append(d)
    return logs

def get_all_cards_for_browse(user_id=1):
    """
    Returns all cards for the Browse panel with review state.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT q.*, r.repetitions, r.flags
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        ORDER BY q.id DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        d['repetitions'] = d.get('repetitions') or 0
        d['flags'] = d.get('flags') or '[]'
        results.append(d)
    return results

def get_starred_status(user_id, question_id):
    """
    Returns True if the question is starred by the user.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT flags FROM reviews WHERE user_id = ? AND question_id = ?", (user_id, question_id))
    row = c.fetchone()
    conn.close()
    
    if row and row['flags']:
        try:
            flags = json.loads(row['flags'])
            return '⭐' in flags or 'starred' in flags
        except:
            pass
    return False

def set_starred_status(user_id, question_id, starred):
    """
    Sets or removes the starred flag for a question.
    """
    flag = '⭐'
    if starred:
        update_flags(question_id, flag, user_id)
    else:
        # Remove the flag if it exists
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT flags FROM reviews WHERE user_id = ? AND question_id = ?", (user_id, question_id))
        row = c.fetchone()
        if row and row['flags']:
            try:
                flags = json.loads(row['flags'])
                if flag in flags:
                    flags.remove(flag)
                    c.execute("UPDATE reviews SET flags = ? WHERE user_id = ? AND question_id = ?", 
                              (json.dumps(flags), user_id, question_id))
                    conn.commit()
            except:
                pass
        conn.close()

def toggle_star(user_id, question_id):
    """
    Toggles the starred status for a question.
    """
    is_starred = get_starred_status(user_id, question_id)
    flag = '⭐'
    update_flags(question_id, flag, user_id)  # update_flags already toggles

def check_concept_exists(concept_text, topic):
    """
    Checks if a question with this concept already exists in the given topic (fuzzy match).
    """
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # 1. Exact Tag Match (Fast)
        c.execute("SELECT id FROM questions WHERE topic = ? AND tags LIKE ?", (topic, f'%"{concept_text}"%'))
        if c.fetchone():
            return True
            
        # 2. Fuzzy Text Match (Expensive)
        # Only check recent questions for this topic to check for near-duplicates
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

# --- Session Persistence ---
def save_user_session(user_id, page, topic, mode, card_id):
    """Save the user's current UI state."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO user_sessions 
                 (user_id, active_page, active_topic, active_mode, current_card_id, last_updated)
                 VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''', 
              (user_id, page, topic, mode, card_id))
    conn.commit()
    conn.close()

def get_user_session(user_id):
    """Retrieve the last saved session state."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def clear_user_session(user_id):
    """Clear session when user explicitly leaves quiz."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- Highlight Persistence ---
def add_highlight(user_id, question_id, text_content, context_type, word_index):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO user_highlights (user_id, question_id, text_content, context_type, word_index) VALUES (?, ?, ?, ?, ?)",
                  (user_id, question_id, text_content, context_type, word_index))
        conn.commit()
    except Exception as e:
        print(f"Error adding highlight: {e}")
    finally:
        conn.close()

def get_highlights(user_id, question_id):
    conn = get_db_connection()
    c = conn.cursor()
    highlights = []
    try:
        # Return list of dicts
        rows = c.execute("SELECT context_type, word_index, text_content FROM user_highlights WHERE user_id=? AND question_id=?", (user_id, question_id)).fetchall()
        for r in rows:
            highlights.append({
                "context_type": r[0],
                "word_index": r[1],
                "text": r[2]
            })
    except Exception as e:
        print(f"Error getting highlights: {e}")
    finally:
        conn.close()
    return highlights

def clear_highlights(user_id, question_id):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM user_highlights WHERE user_id=? AND question_id=?", (user_id, question_id))
        conn.commit()
    except Exception as e:
        print(f"Error clearing highlights: {e}")
    finally:
        conn.close()
