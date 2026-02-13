
import logging
from new_web_app.core.generation_engine import GenerationEngine

logging.basicConfig(level=logging.INFO)

def test_generation():
    print("🚀 Starting DeepSeek Verification Generation...")
    
    # Initialize Engine (Default is DeepSeek now)
    engine = GenerationEngine(dry_run=True, provider="deepseek")
    
    # Test Data
    concept = "Akut Pankreatit"
    topic = "Genel Cerrahi"
    source = "Test Source"
    
    # Fake Evidence (usually retrieved, but we override for testing)
    fake_evidence = """
    Akut pankreatit, pankreasın inflamatuar bir hastalığıdır. 
    En sık nedenler safra taşları ve alkoldür.
    Tanıda amilaz ve lipaz yükselir (Lipaz daha spesifiktir).
    Tedavide en önemli basamak agresif sıvı resüsitasyonudur.
    Ranson kriterleri şiddet belirlemede kullanılır.
    Komplikasyonlar: Psödokist, nekroz, abse.
    """
    
    try:
        result = engine.generate_question(
            concept=concept,
            topic=topic,
            source_material=source,
            difficulty=3,
            evidence_override=fake_evidence
        )
        
        if result:
            print("\n✅ Verification SUCCESS!")
            print(f"   Question: {result.get('question_text')}")
            print(f"   Model used (Provider): {engine.provider}")
            print(f"   Steps validated: Draft, Critique, Explanation, Schema Validation")
        else:
            print("\n❌ Verification FAILED: Result is None")
            
    except Exception as e:
        print(f"\n❌ Verification CRASHED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_generation()
