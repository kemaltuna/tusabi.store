
# Test Vertex AI with gemini-2.0-flash (the working model from ListModels)
from google import genai
import os

PROJECT = "project-2e39002d-6c92-451c-940"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash"

print(f"Testing {MODEL} on Vertex AI ({PROJECT} / {LOCATION})...")

try:
    client = genai.Client(
        vertexai=True,
        project=PROJECT,
        location=LOCATION
    )
    
    response = client.models.generate_content(
        model=MODEL,
        contents="Hello."
    )
    print(f"✅ SUCCESS: {response.text}")
except Exception as e:
    print(f"❌ Failed: {e}")
