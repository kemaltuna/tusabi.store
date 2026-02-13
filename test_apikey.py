
# Test API Key with specific model versions
from google import genai
import os

API_KEY = os.environ.get("GEMINI_API_KEY") or "AIzaSyCOfX3hzixrE9q_41uEgQS7J8y5BXxZuP4"

print(f"Testing with API Key: {API_KEY[:10]}...")

client = genai.Client(api_key=API_KEY)

# List available models first
print("\n--- Listing Available Models ---")
try:
    models = client.models.list()
    for m in list(models)[:15]:
        print(f"  - {m.name}")
except Exception as e:
    print(f"ListModels failed: {e}")

# Try specific versions
MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest",
    "gemini-pro"
]

print("\n--- Testing Individual Models ---")
for model in MODELS:
    try:
        print(f"Testing {model}... ", end="", flush=True)
        response = client.models.generate_content(
            model=model,
            contents="Hi"
        )
        print(f"✅ {response.text[:50]}")
        break
    except Exception as e:
        print(f"❌ {str(e)[:50]}")
