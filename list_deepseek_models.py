
import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("DEEPSEEK_API_KEY")

if not api_key:
    print("❌ DEEPSEEK_API_KEY not found in .env")
    exit(1)

url = "https://api.deepseek.com/models"
headers = {"Authorization": f"Bearer {api_key}"}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        models = response.json().get("data", [])
        print("✅ Available DeepSeek Models:")
        for m in models:
            print(f"- {m['id']} (owned by: {m['owned_by']})")
    else:
        print(f"❌ Failed to list models: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Error: {e}")
