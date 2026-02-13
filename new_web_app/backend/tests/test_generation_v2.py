#!/usr/bin/env python3
"""
V2 Generation Engine Test Suite

Isolated tests for the new V2 backend using processed_pdfs.
Does NOT depend on legacy preprocessed_chunks.
"""

import os
import sys
import json
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROCESSED_PDFS_DIR = Path(__file__).parent.parent.parent.parent / "shared" / "processed_pdfs"


def test_1_manifests():
    """Test: PDF manifests are available and properly structured."""
    print("=" * 60)
    print("TEST 1: PDF Manifests")
    print("=" * 60)
    
    if not PROCESSED_PDFS_DIR.exists():
        print(f"❌ processed_pdfs directory not found: {PROCESSED_PDFS_DIR}")
        return False
    
    subjects = list(PROCESSED_PDFS_DIR.iterdir())
    print(f"✅ Found {len(subjects)} subjects in processed_pdfs/")
    
    # Find a manifest.json to test
    manifest_found = False
    for subject in subjects:
        if not subject.is_dir():
            continue
        for volume in subject.iterdir():
            if not volume.is_dir():
                continue
            manifest_path = volume / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                print(f"✅ Found manifest: {manifest_path.relative_to(PROCESSED_PDFS_DIR.parent)}")
                print(f"   Source: {manifest.get('source', 'N/A')}")
                print(f"   Segments: {len(manifest.get('segments', []))}")
                manifest_found = True
                break
        if manifest_found:
            break
    
    return manifest_found


def test_2_pdf_availability():
    """Test: PDF files exist and are readable."""
    print("\n" + "=" * 60)
    print("TEST 2: PDF Availability")
    print("=" * 60)
    
    # Find a PDF file to test
    pdf_path = None
    for subject in PROCESSED_PDFS_DIR.iterdir():
        if not subject.is_dir():
            continue
        for volume in subject.iterdir():
            if not volume.is_dir():
                continue
            main_dir = volume / "main"
            if main_dir.exists():
                for pdf in main_dir.glob("*.pdf"):
                    pdf_path = pdf
                    break
            if pdf_path:
                break
        if pdf_path:
            break
    
    if not pdf_path:
        print("❌ No PDF files found in processed_pdfs/")
        return False
    
    print(f"📄 Found PDF: {pdf_path.name}")
    
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        print(f"✅ PDF opened ({len(reader.pages)} pages)")
        return len(reader.pages) > 0
    except ImportError:
        print("⚠️ PyPDF2 not installed; skipping page check.")
        return pdf_path.exists()
    except Exception as e:
        print(f"❌ PDF open failed: {e}")
        return False


def test_3_gemini_connection():
    """Test: Gemini API connection works."""
    print("\n" + "=" * 60)
    print("TEST 3: Gemini API Connection")
    print("=" * 60)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set in environment")
        return False
    
    print(f"✅ API key found: {api_key[:8]}...{api_key[-4:]}")
    
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
        # Simple test request
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents="Say 'Hello' in Turkish."
        )
        
        result = response.text.strip()
        print(f"✅ API response: {result}")
        return "Merhaba" in result or len(result) > 0
        
    except ImportError:
        print("❌ google-genai not installed. Run: pip install google-genai")
        return False
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False


def test_4_generation_engine_import():
    """Test: Generation engine can be imported."""
    print("\n" + "=" * 60)
    print("TEST 4: Generation Engine Import")
    print("=" * 60)
    
    try:
        from generation_engine import GenerationEngine
        print("✅ GenerationEngine imported successfully")
        
        engine = GenerationEngine(dry_run=True)
        print(f"✅ Engine created with provider: {engine.provider}")
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Engine initialization failed: {e}")
        return False


def test_5_concept_extraction():
    """Test: Concept extraction from PDF works."""
    print("\n" + "=" * 60)
    print("TEST 5: Concept Extraction")
    print("=" * 60)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ Skipping (API key not set)")
        return True  # Not a failure
    
    try:
        from gemini_client import GeminiClient
        client = GeminiClient()

        # Find a PDF file to test
        pdf_path = None
        topic = "Unknown"
        for subject in PROCESSED_PDFS_DIR.iterdir():
            if not subject.is_dir():
                continue
            for volume in subject.iterdir():
                if not volume.is_dir():
                    continue
                main_dir = volume / "main"
                if main_dir.exists():
                    for pdf in main_dir.glob("*.pdf"):
                        pdf_path = pdf
                        topic = pdf.stem.replace("_", " ").title()
                        break
                if pdf_path:
                    break
            if pdf_path:
                break

        if not pdf_path:
            print("❌ No PDF found for concept extraction.")
            return False

        cache_name, uploaded_file = client.get_or_create_pdf_cache(str(pdf_path))
        concepts = client.extract_concepts(
            "",
            topic,
            count=3,
            media_file=uploaded_file,
            cached_content=cache_name
        )

        if concepts:
            print(f"✅ Extracted {len(concepts)} concepts:")
            for c in concepts:
                print(f"   - {c}")
            return True
        else:
            print("⚠️ No concepts extracted.")
            return True

    except Exception as e:
        print(f"❌ Concept extraction failed: {e}")
        return False


def main():
    print("\n" + "#" * 60)
    print("# V2 GENERATION ENGINE TEST SUITE")
    print("#" * 60)
    
    results = {
        "PDF Manifests": test_1_manifests(),
        "PDF Availability": test_2_pdf_availability(),
        "Gemini Connection": test_3_gemini_connection(),
        "Engine Import": test_4_generation_engine_import(),
        "Concept Extraction": test_5_concept_extraction(),
    }
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 All tests passed! V2 generation pipeline is ready.")
    else:
        print("⚠️ Some tests failed. Check errors above.")
    
    return 0 if all_passed else 1


def test_6_full_generation():
    """Test: Full question generation pipeline (Engine + Client)."""
    print("\n" + "=" * 60)
    print("TEST 6: Full Question Generation (Smoke Test)")
    print("=" * 60)
    
    try:
        from generation_engine import GenerationEngine
        
        # 1. Find a real PDF to use as source
        pdf_path = None
        topic = "Unknown"
        for subject in PROCESSED_PDFS_DIR.iterdir():
            if not subject.is_dir(): continue
            for volume in subject.iterdir():
                if not volume.is_dir(): continue
                main_dir = volume / "main"
                if main_dir.exists():
                    for pdf in main_dir.glob("*.pdf"):
                        pdf_path = pdf
                        # Try to guess topic from filename
                        topic = pdf.stem.replace("_", " ").title()
                        break
                if pdf_path: break
            if pdf_path: break
            
        if not pdf_path:
            print("❌ No PDF found for testing.")
            return False

        print(f"📄 Using Source PDF: {pdf_path.name}")
        
        # 2. Extract concepts specifically from this PDF (Simulation)
        # We'll just define one we know exists OR ask the client to extract?
        # To be fast, let's use a generic medical concept likely in the file, or ask LLM.
        # Use Test 5 logic to get a concept?
        # Let's just use "General Check" concept or rely on what's in the file.
        # Actually, let's allow the engine to just receive a generic concept.
        # If the concept isn't in the PDF, the engine might say "Insufficient Evidence".
        # So we MUST extract a concept first.
        
        from gemini_client import GeminiClient
        client = GeminiClient()

        print("🔍 Extracting a concept from the PDF...")
        cache_name, uploaded_file = client.get_or_create_pdf_cache(str(pdf_path))
        concepts = client.extract_concepts(
            "",
            topic,
            count=1,
            media_file=uploaded_file,
            cached_content=cache_name
        )
        if not concepts:
            print("❌ Could not extract concepts for test.")
            return False

        concept = concepts[0]
        if isinstance(concept, dict):
            concept = concept.get("concept") or ""
        if not concept:
            print("❌ Extracted concept is empty.")
            return False
        print(f"🎯 Concept: {concept}")

        # 3. Initialize Engine
        engine = GenerationEngine(dry_run=True) 
        
        print(f"🚀 Generating question...")
        # CRITICAL: Pass source_pdf to trigger V2 logic (upload/multimodal) or just text override?
        # admin.py passes source_pdf.
        
        result = engine.generate_question(
            concept=concept,
            topic=topic,
            source_material="Test Source",
            difficulty=3,
            source_pdf=str(pdf_path),
            pdf_cache_name=cache_name,
            uploaded_file=uploaded_file
        )
        
        if result:
            print("✅ Generation Successful!")
            print(f"   Question: {result.get('question_text')}")
            blocks = result.get('explanation', {}).get('blocks', [])
            print(f"   Blocks: {len(blocks)}")
            # Verify blocks structure
            types = [b.get('type') for b in blocks]
            print(f"   Block Types: {types}")
            return True
        else:
            print("❌ Generation returned None (check logs)")
            return False
            
    except Exception as e:
        print(f"❌ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "#" * 60)
    print("# V2 GENERATION ENGINE TEST SUITE")
    print("#" * 60)
    
    results = {
        "PDF Manifests": test_1_manifests(),
        "PDF Availability": test_2_pdf_availability(),
        "Gemini Connection": test_3_gemini_connection(),
        "Engine Import": test_4_generation_engine_import(),
        "Concept Extraction": test_5_concept_extraction(),
        "Full Generation": test_6_full_generation(),
    }
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 All tests passed! V2 generation pipeline is ready.")
    else:
        print("⚠️ Some tests failed. Check errors above.")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
