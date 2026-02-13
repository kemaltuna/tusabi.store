
import sys
import os
from new_web_app.core.gemini_client import GeminiClient
from new_web_app.backend.database import save_concept_embedding, get_topic_concepts_data

# Ensure we can import from core
sys.path.append(os.getcwd())

def test_embedding_flow():
    client = GeminiClient()
    test_concept = "Hiperkalemi ve EKG Değişiklikleri"
    topic = "Sıvı Elektrolit Test"
    
    print(f"Testing embedding generation for: {test_concept}")
    
    # 1. Generate
    model_names = ["text-embedding-004", "models/text-embedding-004", "publishers/google/models/text-embedding-004"]
    embedding = None
    
    for m in model_names:
        print(f"Trying model: {m}...")
        try:
            # We need to hack the client momentarily or assume client has a method that accepts model name
            # The client hardcodes it. Let's modify the client instance or call the sdk directly.
            # Client has client.models.embed_content.
            result = client.client.models.embed_content(
                model=m,
                contents=test_concept
            )
            embedding = result.embeddings[0].values
            print(f"✅ Success with {m}")
            break
        except Exception as e:
             print(f"❌ Failed with {m}: {e}")
             
    if not embedding:
        print("❌ Failed to generate embedding with all candidates.")
        return
    
    print(f"✅ Generated embedding (len={len(embedding)})")
    
    # 2. Save
    try:
        save_concept_embedding(topic, test_concept, embedding)
        print("✅ Saved to database.")
    except Exception as e:
        print(f"❌ Failed to save: {e}")
        return

    # 3. Read back directly from concept_embeddings
    import sqlite3
    conn = sqlite3.connect("shared/data/quiz_v2.db")
    c = conn.cursor()
    c.execute("SELECT embedding_json FROM concept_embeddings WHERE concept_text = ?", (test_concept,))
    row = c.fetchone()
    conn.close()
    
    if row:
        print("✅ Verified: Concept found in 'concept_embeddings' table.")
        if row[0]:
            print(f"✅ Verified: Embedding blob present (len={len(row[0])} chars).")
        else:
             print("❌ Error: Embedding JSON is empty.")
    else:
        print("❌ Error: Concept not found in DB table.")

if __name__ == "__main__":
    try:
        test_embedding_flow()
    except Exception as e:
        print(f"Crash: {e}")
