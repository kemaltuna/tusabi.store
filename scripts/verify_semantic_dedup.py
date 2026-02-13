import sys
import os
import logging
import time

# Add project root to path
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/new_web_app")

from dotenv import load_dotenv
load_dotenv("/home/yusuf-kemal-tuna/medical_quiz_app/.env")

from core.deduplicator import check_duplicate_hybrid, cosine_similarity
from core.gemini_client import GeminiClient

def run_test_cases():
    client = GeminiClient()
    
    # Define Test Cases (Baseline vs Candidate)
    # Expected: True (Duplicate) or False (Distinct)
    
    test_suite = [
        {
            "name": "Paraphrase (High Severity)",
            "base_q": "Tip 2 diyabet patogenezindeki temel bozukluk hangisidir?",
            "base_a": "Periferik dokularda insülin direnci",
            "cand_q": "Hangisi Tip 2 DM gelişiminde rol oynayan ana mekanizmadır?",
            "cand_a": "İnsülin rezistansı",
            "expected": True
        },
        {
            "name": "Different Aspect (Diagnosis vs Treatment)",
            "base_q": "Akut bakteriyel menenjit tedavisinde ilk tercih hangi antibiyotiktir?",
            "base_a": "Seftriakson + Vankomisin",
            "cand_q": "Akut bakteriyel menenjit tanısında en değerli laboratuvar testi nedir?",
            "cand_a": "BOS kültürü ve analizi",
            "expected": False
        },
        {
            "name": "Negation Edge Case (Cause vs Not Cause)",
            "base_q": "Hangisi hiperkalsemi nedenlerinden biridir?",
            "base_a": "Primer hiperparatiroidizm",
            "cand_q": "Aşağıdakilerden hangisi hiperkalsemi nedenleri arasında yer almaz?",
            "cand_a": "Hipoparatiroidizm",
            "expected": False
        },
        {
            "name": "Specific vs General (Detail Difference)",
            "base_q": "Down sendromuna eşlik eden en sık konjenital kalp defekti nedir?",
            "base_a": "Atriyoventriküler septal defekt (AVSD)",
            "cand_q": "Down sendromunda görülen kromozom anomalisi nedir?",
            "cand_a": "Trizomi 21",
            "expected": False
        },
        {
            "name": "Slightly Different Phrasing (Low Severity)",
            "base_q": "Demir eksikliği anemisinde ferritin düzeyi nasıl değişir?",
            "base_a": "Düşer (<15 ng/mL)",
            "cand_q": "Demir eksikliği anemisi tanısında ferritin seviyesi ne olur?",
            "cand_a": "Azalır",
            "expected": True
        },
        {
            "name": "Specific Opposites (Hypercalcemia vs Hypocalcemia)",
            "base_q": "Hangisi hiperkalsemi nedenlerinden biridir?",
            "base_a": "Primer hiperparatiroidizm",
            "cand_q": "Hangisi hipokalsemi nedenlerindendir?",
            "cand_a": "Hipoparatiroidizm", 
            "expected": False
        }
    ]
    
    threshold = 0.72
    print(f"\n🚀 Starting Deduplication Tests (Threshold: {threshold})\n")
    
    passed_tests = 0
    total_tests = len(test_suite)
    
    for case in test_suite:
        time.sleep(2.0) # Avoid rate limits
        print(f"🔹 CASE: {case['name']}")
        
        # Build Signatures (Answer First for better differentiation)
        sig1 = f"Answer: {case['base_a']} | Question: {case['base_q']}"
        sig2 = f"Answer: {case['cand_a']} | Question: {case['cand_q']}"
        
        print(f"   Signature 1: {sig1}")
        print(f"   Signature 2: {sig2}")
        
        # Embed
        emb1 = client.get_text_embedding(sig1)
        emb2 = client.get_text_embedding(sig2)
        
        if not emb1 or not emb2:
            print("   ❌ Embedding failed.")
            continue
            
        # Compare
        score = cosine_similarity(emb1, emb2)
        is_dup = score > threshold
        
        # Result
        status = "✅ PASS" if is_dup == case['expected'] else "❌ FAIL"
        if status == "✅ PASS":
            passed_tests += 1
            
        print(f"   Score: {score:.4f}")
        print(f"   Detected: {'DUPLICATE' if is_dup else 'DISTINCT'}")
        print(f"   Expected: {'DUPLICATE' if case['expected'] else 'DISTINCT'}")
        print(f"   Result: {status}\n")

    print(f"🏁 Summary: {passed_tests}/{total_tests} tests passed.")

if __name__ == "__main__":
    run_test_cases()
