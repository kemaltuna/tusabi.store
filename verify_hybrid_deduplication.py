
import os
import logging
from dotenv import load_dotenv
from new_web_app.core.gemini_client import GeminiClient

# Configure logging
logging.basicConfig(level=logging.INFO)

def verify_hybrid_deduplication():
    print("🚀 Verifying Hybrid Deduplication Setup...")
    
    # Load .env
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("❌ GEMINI_API_KEY not found in .env")
        return
        
    print(f"🔑 Found GEMINI_API_KEY: {gemini_key[:5]}...{gemini_key[-4:]}")
    
    try:
        # Initialize Client
        # Note: GeminiClient automatically picks up GEMINI_API_KEY from os.environ
        # provided we cleared the old key or it uses the new variable name.
        # Actually, let's check GeminiClient implementation. 
        # It typically iterates over keys or uses a specific env var.
        
        client = GeminiClient()
        print("✅ GeminiClient initialized.")
        
        # Test Embedding
        test_text = "Medical concept for verification."
        print(f"🧬 Generating embedding for: '{test_text}'")
        
        embedding = client.get_text_embedding(test_text)
        
        if embedding and isinstance(embedding, list) and len(embedding) > 0:
            print(f"✅ Success! Generated embedding with length: {len(embedding)}")
            print("🎉 Hybrid Deduplication is READY.")
        else:
            print("❌ Failed to generate embedding (returned empty/None).")
            
    except Exception as e:
        print(f"❌ Exception during verification: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_hybrid_deduplication()
