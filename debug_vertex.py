
import os
import sys

# Fix path
sys.path.insert(0, os.path.abspath("new_web_app/core"))
try:
    from gemini_client import GeminiClient
except ImportError:
    sys.path.insert(0, os.path.abspath("new_web_app"))
    from core.gemini_client import GeminiClient

PROJECT = "project-2e39002d-6c92-451c-940"
LOCATION = "us-central1"

print(f"🔎 Probing Models for: {PROJECT} in {LOCATION} ...")

client = GeminiClient(vertex_enabled=True, vertex_project=PROJECT, vertex_location=LOCATION)

# Probe common names
CANDIDATES = [
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash",
    "gemini-1.0-pro",
    "gemini-pro",
    "gemini-1.0-pro-001",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro-002"
]

for model in CANDIDATES:
    print(f"\n--- Probing: {model} ---")
    try:
        response = client.client.models.generate_content(
            model=model,
            contents="Connectivity test."
        )
        print(f"✅ SUCCESS! Model '{model}' works.")
        print(f"   Response: {response.text}")
        break
    except Exception as e:
        if "NOT_FOUND" in str(e):
             print(f"❌ Not Found")
        elif "PERMISSION_DENIED" in str(e):
             print(f"❌ Permission Denied (API/Billing?)")
        else:
             print(f"❌ Error: {e}")
