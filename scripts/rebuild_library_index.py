#!/usr/bin/env python3
"""
Rebuild Library Index
Scans the preprocessed/ directory and rebuilds data/medquiz_library.json.
Reads the title from the first line of each .txt file.
NOW WITH HIERARCHY SUPPORT: Assigns 'category' from TOC.
"""

import os
import json
import re
from pathlib import Path

def slugify(value):
    """
    Converts string to slug (matching split_by_toc.py logic).
    """
    value = str(value)
    tr_map = {
        'ı': 'i', 'İ': 'i', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u', 
        'ş': 's', 'Ş': 's', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c'
    }
    for k, v in tr_map.items():
        value = value.replace(k, v)
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '_', value)
    return value

def parse_toc_hierarchy(toc_path):
    """
    Parses TOC file to map slugified_topic -> category_name.
    """
    hierarchy_map = {}
    current_category = "Genel" 
    
    if not os.path.exists(toc_path):
        return {}

    with open(toc_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    merged_lines = []
    buffer = ""
    
    # 1. Merge Multilines and Detect Categories
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("---") or line.startswith("Source Type:"):
            i += 1
            continue
            
        has_dots_or_num = ("..." in line or ". . ." in line) or re.search(r'\d+$', line)
        
        # Check strict uppercase for category (allowing common conjunctions)
        temp_cat = line.replace(" VE ", " ").replace(" İLE ", " ").replace(" VEYA ", " ")
        temp_cat = temp_cat.replace(" ve ", " ").replace(" ile ", " ").replace(" veya ", " ")
        # Heuristic: Uppercase and valid length, NO dots/num
        is_upper_cat = (not has_dots_or_num) and temp_cat.isupper() and len(line) > 3
        
        if is_upper_cat:
            # It IS a category
            if buffer:
                # Flush buffer strictly as a Straggler Topic (rare) or append to merged?
                # If buffer exists here, it was a topic part without punctuation.
                # Assuming it was a topic line.
                merged_lines.append(buffer)
                buffer = ""
            merged_lines.append(f"CAT:{line}")
        elif not has_dots_or_num:
            # Likely part of a topic (or a Category that failed the Upper check?)
            # If we assume Categories MUST be Upper, then this is topic part.
            if buffer: buffer += " " + line
            else: buffer = line
        else:
            # Topic line (has dots)
            if buffer:
                merged_lines.append(buffer + " " + line)
                buffer = ""
            else:
                merged_lines.append(line)
        i += 1
        
    if buffer: merged_lines.append(buffer)
    
    # 2. Process Lines to Map
    for line in merged_lines:
        if line.startswith("CAT:"):
            current_category = line[4:].strip()
            # AUTO-MAP: Map the category name itself to the category
            # This ensures files named like the category (Intro chapters) are assigned correctly
            cat_slug = slugify(current_category)
            hierarchy_map[cat_slug] = current_category
        else:
            # Extract topic name
            match = re.search(r'^(.*?)(?:\.{2,}|\s{2,})(\d+)$', line)
            if match:
                raw_name = match.group(1).strip()
            else:
                 # Fallback
                 parts = line.rsplit(None, 1)
                 if len(parts) == 2 and parts[1].isdigit():
                     raw_name = parts[0].strip()
                 else:
                     raw_name = line.strip()
            
            # Slugify for mapping
            slug = slugify(raw_name)
            hierarchy_map[slug] = current_category
            # print(f"DEBUG: Map {slug} -> {current_category}")
            
    return hierarchy_map

def get_title_from_file(filepath):
    """Read the first line of the file to extract the title."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            # Remove '# ' prefix if present (markdown header)
            if first_line.startswith('# '):
                title = first_line[2:].strip()
                # Fix Collisions: If generic Chunk title, append filename to make unique
                if title.startswith("Chunk:"):
                    title = f"{title} -- {os.path.basename(filepath)}"
                return title
            return first_line
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def rebuild_index(base_dir='preprocessed_chunks', pdf_dir='shared/processed_pdfs', output_file='shared/data/medquiz_library.json'):
    library = {}
    base_path = Path(base_dir)
    pdf_path = Path(pdf_dir)
    root_dir = base_path.parent 
    
    # --- 1. Identify PDF Sources first ---
    pdf_sources = set()
    if pdf_path.exists():
        for d in pdf_path.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                pdf_sources.add(d.name)
    
    # --- 2. Scan Preprocessed Text Chunks (Legacy/Fallback) ---
    if base_path.exists():
        for source_dir in sorted(base_path.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith('.'):
                continue
                
            source_name = source_dir.name
            
            # SKIPPING Logic: If we have PDFs for this source, ignore text chunks!
            if source_name in pdf_sources:
                print(f"Skipping Text Scan for {source_name} (PDFs available)")
                continue

            # print(f"Processing Text source: {source_name}")
            
            # Parse TOC for this source
            toc_filename = f"toc_{source_name.lower()}.txt"
            toc_path = root_dir / toc_filename
            
            if not toc_path.exists():
                 toc_path = Path(f"/home/yusuf-kemal-tuna/medical_quiz_app/{toc_filename}")
    
            hierarchy = {}
            if toc_path.exists():
                hierarchy = parse_toc_hierarchy(toc_path)
            
            topics = []
            
            for file_path in sorted(source_dir.glob('*.txt')):
                # SKIP SMALL FILES (Likely just headers)
                if file_path.stat().st_size < 100:
                    continue
    
                title = get_title_from_file(file_path)
                if not title:
                    title = file_path.stem.replace('_', ' ').title()
                    
                relative_path = f"{base_dir}/{source_name}/{file_path.name}"
                
                # Determine Category by slug matching
                category = "Genel" 
                f_slug = file_path.stem.lower() 
                
                best_match_len = 0
                for t_slug, cat in hierarchy.items():
                    if t_slug in f_slug and len(t_slug) > best_match_len:
                         category = cat
                         best_match_len = len(t_slug)
                
                topics.append({
                    "topic": title,
                    "file": file_path.name,
                    "path": relative_path,
                    "category": category,
                    "type": "text"
                })
                
            if topics:
                human_readable_name = source_name.replace('_', ' ')
                library[source_name] = {
                    "ders": human_readable_name,
                    "topic_count": len(topics),
                    "topics": topics
                }

    # --- 2. Scan Processed PDFs (New Semantic Chapters) ---
    if pdf_path.exists():
        print(f"Scanning PDF Directory: {pdf_path}")
        for source_dir in sorted(pdf_path.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith('.'):
                continue

            source_name = source_dir.name
            
            # If source already exists in library (from text scan), we append to it. 
            # Otherwise create new entry.
            if source_name not in library:
                library[source_name] = {
                    "ders": source_name.replace('_', ' '),
                    "topic_count": 0,
                    "topics": []
                }
            
            pdf_topics = []
            
            # Recursive Walk
            # Structure: processed_pdfs/{Subject}/output_{...}/[sub|main]/{Category}/{Topic}.pdf
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    if file.lower().endswith('.pdf'):
                        full_path = Path(root) / file
                        
                        # Determine Category and Topic from Path
                        # Example path: .../sub/01_Hucre_Zedelenmesi/02_Adaptasyon.pdf
                        # Category: 01_Hucre_Zedelenmesi
                        # Topic: 02_Adaptasyon
                        
                        parent_folder = full_path.parent.name
                        grandparent_folder = full_path.parent.parent.name
                        
                        # Logic to clean names
                        # If parent is 'sub' or 'main', then category is likely just "Genel" or derived from grandparent?
                        # Actually structure is: output_X / sub / CategoryName / File.pdf
                        
                        if parent_folder in ['sub', 'main']:
                            # File is directly in sub/main? Usually not based on structure description.
                            # Structure: output.../main/Chapter.pdf
                            category = "Ana Bölümler" if parent_folder == 'main' else "Alt Bölümler"
                        else:
                            # Parent is likely the Category Name (e.g. SANTRAL_SINIR_SISTEMI)
                            category = parent_folder.replace('_', ' ').title()
                        
                        # Topic Name from Filename
                        topic_name = file.replace('.pdf', '').replace('_', ' ')
                        # Remove leading numbers if present (e.g. "01 Topic" -> "Topic")
                        # topic_name = re.sub(r'^\d+\s*', '', topic_name) 
                        
                        # Relative path for storage? Or Absolute?
                        # Library usually stores relative to app root.
                        rel_path = str(full_path.relative_to(root_dir))
                        
                        # Get Page Count
                        page_count = 0
                        try:
                            # Use PyMuPDF (fitz) as it is available
                            import fitz
                            doc = fitz.open(full_path)
                            page_count = doc.page_count
                            doc.close()
                        except ImportError:
                            print("Error: fitz (PyMuPDF) not found for page counting.")
                        except Exception as e:
                            print(f"Error reading PDF {file}: {e}")

                        pdf_topics.append({
                            "topic": topic_name,
                            "file": file,
                            "path": rel_path,
                            "category": category,
                            "type": "pdf",
                            "page_count": page_count
                        })
            
            if pdf_topics:
                print(f"  Found {len(pdf_topics)} PDFs for {source_name}")
                library[source_name]["topics"].extend(pdf_topics)
                library[source_name]["topic_count"] += len(pdf_topics)

    # Write the JSON output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(library, f, ensure_ascii=False, indent=2)
        
    print(f"\nSuccessfully rebuilt library index at {output_file}")
    print(f"Total sources: {len(library)}")
    total_topics = sum(d['topic_count'] for d in library.values())
    print(f"Total topics: {total_topics}")

if __name__ == "__main__":
    rebuild_index()
