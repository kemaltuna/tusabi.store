#!/usr/bin/env python3
"""
Test script to trigger flashcard generation manually.
"""
import sys
import os

# Add paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "new_web_app"))

from new_web_app.backend.routers.flashcards import (
    get_unused_highlight_stats,
    run_flashcard_generation,
    MIN_FLASHCARD_QUESTIONS
)

if __name__ == "__main__":
    # Use the known user_id from the DB
    user_id = 3
    
    print(f"Threshold settings:")
    print(f"  MIN_FLASHCARD_QUESTIONS = {MIN_FLASHCARD_QUESTIONS}")
    print("  MIN_FLASHCARD_CHARS = n/a (not used)")
    print()
    
    stats = get_unused_highlight_stats(user_id)
    print(f"Current unused highlight stats for user {user_id}:")
    print(f"  Question count: {stats['question_count']}")
    print(f"  Total chars: {stats['total_chars']}")
    print()
    
    # Check if thresholds are met
    if stats["question_count"] >= MIN_FLASHCARD_QUESTIONS:
        print("Thresholds met! Running flashcard generation...")
        try:
            result = run_flashcard_generation(user_id, limit=200, max_cards=50)
            print(f"Result: {result}")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Thresholds NOT met yet.")
        print(f"  Need: {MIN_FLASHCARD_QUESTIONS} questions")
        print(f"  Have: {stats['question_count']} questions")
