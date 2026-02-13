def calculate_sm2(quality: int, previous_interval: float, previous_ease_factor: float, previous_repetitions: int):
    """
    Implements SuperMemo-2 Algorithm.
    Ratings:
    0-2: Fail (Reset)
    3-5: Pass (Success)
    """
    if quality >= 3:
        if previous_repetitions == 0:
            interval = 1
        elif previous_repetitions == 1:
            interval = 6
        else:
            interval = int(previous_interval * previous_ease_factor)
        
        repetitions = previous_repetitions + 1
        ease_factor = previous_ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    else:
        repetitions = 0
        interval = 0 # Reset to 0 for immediate review? Or 1? DB default is 0. 
        # App logic uses 1 usually on fail. Let's use 0 to signal "Due Now".
        interval = 0
        ease_factor = previous_ease_factor 
    
    if ease_factor < 1.3:
        ease_factor = 1.3
        
    return interval, ease_factor, repetitions

def normalize_turkish(text: str) -> str:
    """
    Properly lowercases Turkish strings handling I/ı and İ/i.
    Ex: 'DIYARBAKIR' -> 'diyarbakır', 'İSTANBUL' -> 'istanbul'
    """
    translation_table = str.maketrans("İI", "iı")
    return text.translate(translation_table).lower()

from functools import lru_cache
from typing import Optional
from pathlib import Path
import json
import os

@lru_cache(maxsize=1)
def get_manifest_map() -> dict:
    """
    Scans processed_pdfs once and returns a map of {topic_name: pdf_path}.
    Cached wrapper to prevent frequent IO.
    """
    processed_dir = Path(__file__).parent.parent.parent / "shared" / "processed_pdfs"
    if not processed_dir.exists():
        return {}
        
    topic_map = {}
    
    for subject_dir in processed_dir.iterdir():
        if not subject_dir.is_dir(): continue
        
        for volume_dir in subject_dir.iterdir():
            if not volume_dir.is_dir(): continue
            
            manifest_path = volume_dir / "manifest.json"
            if not manifest_path.exists(): continue
            
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                
                # Check segments
                for seg in manifest.get("segments", []):
                    title = seg.get("title")
                    file_path = seg.get("file")
                    if title and file_path:
                        topic_map[title] = file_path
                        
                    # Check sub-segments
                    for sub in seg.get("sub_segments", []):
                        sub_title = sub.get("title")
                        sub_file = sub.get("file")
                        if sub_title and sub_file:
                            topic_map[sub_title] = sub_file
                            
            except Exception:
                continue
                
    return topic_map

def find_pdf_for_topic(topic_name: str) -> Optional[str]:
    """
    Cached look up for topic PDF.
    """
    mapping = get_manifest_map()
    return mapping.get(topic_name)
