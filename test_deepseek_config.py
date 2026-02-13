
import os
import time
from new_web_app.core.deepseek_client import DeepSeekClient

print("🧪 Testing DeepSeek Model Config...")
try:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key or "your_key_here" in api_key:
        print("❌ DEEPSEEK_API_KEY is missing or invalid in .env")
        exit(1)
        
    client = DeepSeekClient()
    print(f"   ✅ Client initialized.")
    print(f"   ℹ️ Default Model: {client.default_model}")
    print(f"   ℹ️ Reasoning Model: {client.reasoning_model}")
    
    print("   📡 Sending test request (Chat)...")
    # Using internal _call_api for raw test
    response = client._call_api(
        system_prompt="You are a test bot.", 
        user_prompt="Reply with JSON: {'status': 'OK'}",
        model="deepseek-chat"
    )
    print(f"   🎉 Response: {response}")
    
    print("✅ DeepSeek Configuration Verified!")
    
except Exception as e:
    print(f"❌ Error: {e}")
