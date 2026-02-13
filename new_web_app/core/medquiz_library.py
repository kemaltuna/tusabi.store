#!/usr/bin/env python3
"""
MedQuiz Library Utility

Provides access to the medical quiz library structure (sources, categories, topics)
from the medquiz_library.json file. This module is used by the generation engine
to fetch available topics for a given source material.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

# Cache for library data
_library_cache: Optional["MedQuizLibrary"] = None


class MedQuizLibrary:
    """Wrapper class for the medquiz library JSON structure."""
    
    def __init__(self, data: Dict):
        self._data = data
    
    def get_sources(self) -> List[str]:
        """Get list of all available source materials (e.g., Anatomi, Biyokimya, etc.)"""
        return list(self._data.keys())
    
    def get_topics(self, source_material: str) -> List[Dict]:
        """Get list of topics for a given source material.
        
        Args:
            source_material: Name of the source (e.g., "Anatomi", "Biyokimya")
            
        Returns:
            List of topic dictionaries with keys: topic, file, path, category, type, page_count
        """
        if source_material not in self._data:
            return []
        return self._data[source_material].get("topics", [])
    
    def get_categories(self, source_material: str) -> List[str]:
        """Get unique list of categories for a given source material."""
        topics = self.get_topics(source_material)
        categories = set(t.get("category", "") for t in topics if t.get("category"))
        return sorted(categories)
    
    def get_topics_by_category(self, source_material: str, category: str) -> List[Dict]:
        """Get topics filtered by category."""
        topics = self.get_topics(source_material)
        return [t for t in topics if t.get("category") == category]
    
    def get_topic_count(self, source_material: str) -> int:
        """Get the total topic count for a source."""
        if source_material not in self._data:
            return 0
        return self._data[source_material].get("topic_count", len(self.get_topics(source_material)))
    
    def find_topic(self, source_material: str, topic_name: str) -> Optional[Dict]:
        """Find a specific topic by name (case-insensitive partial match)."""
        topics = self.get_topics(source_material)
        topic_name_lower = topic_name.lower()
        for t in topics:
            if topic_name_lower in t.get("topic", "").lower():
                return t
        return None


def get_library() -> MedQuizLibrary:
    """Load and return the MedQuiz library singleton.
    
    Caches the library data after first load for efficiency.
    
    Returns:
        MedQuizLibrary instance
    """
    global _library_cache
    
    if _library_cache is not None:
        return _library_cache
    
    # Determine the path to the library JSON file
    # Adjusted for location in new_web_app/core/
    # core -> new_web_app -> root -> shared
    possible_paths = [
        Path(__file__).parent.parent.parent / "shared" / "data" / "medquiz_library.json",
        Path.cwd() / "shared" / "data" / "medquiz_library.json", # Fallback if running from root
        Path.cwd() / ".." / "shared" / "data" / "medquiz_library.json",
    ]
    
    library_path = None
    for path in possible_paths:
        if path.exists():
            library_path = path
            break
    
    if library_path is None:
        raise FileNotFoundError(
            f"Could not find medquiz_library.json. Searched in: {[str(p) for p in possible_paths]}"
        )
    
    with open(library_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    _library_cache = MedQuizLibrary(data)
    return _library_cache


def reload_library() -> MedQuizLibrary:
    """Force reload of the library data (useful after updates)."""
    global _library_cache
    _library_cache = None
    return get_library()


# Allow direct testing
if __name__ == "__main__":
    lib = get_library()
    print(f"Sources: {lib.get_sources()}")
    for source in lib.get_sources()[:3]:
        print(f"\n{source}:")
        print(f"  Topic count: {lib.get_topic_count(source)}")
        print(f"  Categories: {lib.get_categories(source)[:5]}...")
