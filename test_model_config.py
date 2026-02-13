
import os
import time
from new_web_app.core.gemini_client import GeminiClient

print("🧪 Testing Gemini Model Config...")
try:
    client = GeminiClient()
    print(f"   ✅ Client initialized.")
    print(f"   ℹ️ Flash Model: {client.flash_model_name}")
    print(f"   ℹ️ Pro Model: {client.pro_model_name}")
    
    print("   📡 Sending test request...")
    response = client.client.models.generate_content(
        model=client.flash_model_name,
        contents="Hello, simply reply with 'OK' if you see this.",
    )
    print(f"   🎉 Response: {response.text}")
    print("✅ Model Config Verified!")
    
except Exception as e:
    print(f"❌ Error: {e}")
