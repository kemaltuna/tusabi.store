
from google import genai
import os

PROJECT = "project-2e39002d-6c92-451c-940"

REGIONS = ["us-central1", "us-east1", "us-west1", "europe-west1", "asia-southeast1"]
MODELS = ["gemini-1.5-flash-001", "gemini-1.5-flash", "gemini-1.0-pro", "gemini-1.5-pro-001"]

print(f"🌍 Starting Exhaustive Scan on {PROJECT}...")

working_config = None

for region in REGIONS:
    print(f"\n--- Checking Region: {region} ---")
    try:
        client = genai.Client(vertexai=True, project=PROJECT, location=region)
        for model in MODELS:
            try:
                print(f"  Probing {model}...", end="", flush=True)
                response = client.models.generate_content(
                    model=model,
                    contents="Hi"
                )
                print(f" ✅ SUCCESS!")
                working_config = (region, model)
                break
            except Exception as e:
                err = str(e)
                if "404" in err: print(" ❌ 404")
                elif "403" in err: print(" ❌ 403")
                else: print(f" ❌ Error: {err[:50]}...")
        if working_config: break
    except Exception as e:
         print(f"  Failed to init client for region: {e}")

if working_config:
    print(f"\n🎉 FOUND WORKING CONFIG: Region={working_config[0]}, Model={working_config[1]}")
else:
    print("\n❌ ALL REGIONS/MODELS FAILED.")
