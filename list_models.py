
import os
from dotenv import load_dotenv
load_dotenv()

import google.genai as genai

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Try alternate name
    api_key = os.environ.get("GOOGLE_API_KEY")

print(f"🔑 API Key found: {'Yes' if api_key else 'No'}")

try:
    client = genai.Client(api_key=api_key)
    print("📋 Listing Available Models (v1beta)...")
    # Some SDK versions use iterate models, let's try standard list
    for m in client.models.list():
        print(f"- {m.name}")
        
    print("\n📋 Listing Available Models (v1alpha)...")
    # Check if we can switch version or if it's just different endpoints
    # standard client might default to v1beta.
    
except Exception as e:
    print(f"❌ Error: {e}")
