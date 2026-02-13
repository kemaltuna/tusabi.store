import logging
import sys
import os

# FORCE PATHS
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app")
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/new_web_app")
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/new_web_app/core")
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app/backend")

# Try importing directly
try:
    from new_web_app.core.generation_engine import GenerationEngine
except ImportError:
    # Try local import if paths messed up
    import generation_engine
    GenerationEngine = generation_engine.GenerationEngine

logging.basicConfig(level=logging.INFO)

def test():
    print("🚀 Starting Repro Gen...")
    # Initialize engine
    engine = GenerationEngine(dry_run=True) # Dry run prevents DB save, but I want to verify validation passes
    
    concept = "Orak Hücreli Anemi"
    topic = "Büyüme ve Gelişme"
    source = "Pediatri"
    
    fake_evidence = """
    Orak hücreli anemi (SCA), hemoglobin S (HbS) üretimi ile karakterize otozomal resesif bir hastalıktır.
    Valin -> Glutamik asit mutasyonu vardır (Beta zinciri 6. pozisyon).
    Oraklaşma hipoksi, asidoz ve dehidratasyonla tetiklenir.
    Klinik: Ağrılı krizler (vazooklüzif), hemolitik anemi, splenik sekestrasyon.
    Oto-splenektomi görülür (Howell-Jolly cisimcikleri).
    Tanı: Hb elektroforezi.
    Tedavi: Hidroksiüre (HbF'i artırır), folik asit, penisilin profilaksisi.
    En sık osteomyelit nedeni Salmonella'dır.
    """
    
    try:
        q = engine.generate_question(
            concept=concept,
            topic=topic,
            source_material=source,
            evidence_override=fake_evidence,
            source_pdf=None # Override allows skipping PDF
        )
        
        if q:
            print("\n✅ Verification SUCCESS! Question Generated.")
            print(f"Question Text: {q.get('question_text')[:50]}...")
            if 'explanation_data' in q:
                print("Blocks found:", [b['type'] for b in q['explanation_data'].get('blocks', [])])
        else:
            print("\n❌ Verification FAILED: Result is None")

    except Exception as e:
        print(f"\n❌ Pipeline Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
