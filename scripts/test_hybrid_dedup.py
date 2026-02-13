import sys
import os
import logging

# Add project root to path
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/new_web_app")

from dotenv import load_dotenv
load_dotenv("/home/yusuf-kemal-tuna/medical_quiz_app/.env") # Try root .env

from core.deduplicator import check_duplicate_hybrid
from core.gemini_client import GeminiClient

# Mock or Real Client
# We need real embedding capability
try:
    from config import GEMINI_API_KEY
except ImportError:
    # Try getting from env or hardcoded fallback (unsafe for logs, better rely on env)
    GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("❌ No API KEY found. Cannot test embeddings.")
    # Try one more fallback if running in dev environment
    # GEMINI_API_KEY = "..." 
    # But better to just exit
    sys.exit(1)

logging.basicConfig(level=logging.INFO)

def test_dedup():
    print("🚀 Initializing Gemini Client...")
    client = GeminiClient(GEMINI_API_KEY)
    
    # Test Cases
    # 1. Exact Match Test
    # Existing: "Kompleks Bölgesel Ağrı Sendromu" (from recent job)
    topic = "Küçük Stajlar" # or topic from DB
    
    # Let's pick a known existing concept from previous `sqlite3` output or insert one
    # DB output showed: "concept:Munchausen_by_Proxy_Syndrome" in "05 Çocuk İstismarı"
    
    existing_concept = "Munchausen_by_Proxy_Syndrome"
    topic = "05 Çocuk İstismarı"
    
    print(f"\n🧪 Test 1: Exact Match ('{existing_concept}')")
    is_dup = check_duplicate_hybrid(existing_concept, topic, client)
    print(f"Result: {is_dup} (Expected: True)")
    
    # 2. Fuzzy Match Test
    # "Munchausen by Proxy" (approx match)
    fuzzy_concept = "Munchausen Syndrome by Proxy"
    print(f"\n🧪 Test 2: Fuzzy/Semantic Match ('{fuzzy_concept}')")
    is_dup = check_duplicate_hybrid(fuzzy_concept, topic, client)
    print(f"Result: {is_dup} (Expected: True via Fuzzy or Semantic)")
    
    # 3. Semantic Match Test (Cross Language or Synonym)
    # "Factitious Disorder Imposed on Another" (Clinical synonym)
    semantic_concept = "Factitious Disorder Imposed on Another"
    print(f"\n🧪 Test 3: Semantic Match ('{semantic_concept}')")
    is_dup = check_duplicate_hybrid(semantic_concept, topic, client)
    print(f"Result: {is_dup} (Expected: True via Semantic)")
    
    # 4. Non-Duplicate
    new_concept = "Fracture of Femur"
    print(f"\n🧪 Test 4: New Concept ('{new_concept}')")
    is_dup = check_duplicate_hybrid(new_concept, topic, client)
    print(f"Result: {is_dup} (Expected: False)")

if __name__ == "__main__":
    test_dedup()
