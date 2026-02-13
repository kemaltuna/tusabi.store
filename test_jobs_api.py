
import requests
import json
import jwt
import datetime
import os

# Configuration matching backend/routers/auth.py
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"

def create_admin_token():
    payload = {
        "sub": "1",
        "username": "admin",
        "role": "admin",
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

URL = "http://localhost:8000/admin/jobs"
TOKEN = create_admin_token()

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

print(f"Testing API at {URL}...")

try:
    response = requests.get(URL, headers=headers, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Success. Found {len(data)} jobs.")
        for job in data[:3]:
            print(f"- Job {job.get('id')} [{job.get('status')}]: {job.get('topic')} (Header: {job.get('main_header')}) Progress: {job.get('progress')}/{job.get('total_items')}")
    else:
        print("Error:", response.text)
except Exception as e:
    print(f"Failed: {e}")
