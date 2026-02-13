
import google.auth
from google.auth.transport.requests import Request
import requests
import json
import os

PROJECT_ID = "project-2e39002d-6c92-451c-940"
LOCATION = "us-central1"
API_ENDPOINT = f"https://{LOCATION}-aiplatform.googleapis.com"

print(f"getting credentials for {PROJECT_ID}...")
credentials, project = google.auth.default()
if not credentials.valid:
    credentials.refresh(Request())

token = credentials.token
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# List Publisher Models
url = f"{API_ENDPOINT}/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models"
print(f"Requesting: {url}")

try:
    response = requests.get(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        models = data.get("publisherModels", [])
        print(f"Found {len(models)} models.")
        for m in models[:10]: # Print first 10
            print(f" - {m.get('name')} ({m.get('displayName', 'No Display Name')})")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")
