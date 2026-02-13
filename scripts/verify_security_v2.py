
import requests
import sys

BASE_URL = "http://localhost:8000"  # Backend runs on 8000 usually, wait, Frontend is 3000, Backend?
# I need to check backend port. Usually main.py runs on 8000.

def login(username, password):
    url = f"{BASE_URL}/auth/login"
    data = {"username": username, "password": password}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json()["access_token"]
    print(f"Login failed for {username}: {response.text}")
    return None

def test_endpoint(token, endpoint, method="POST", expected_status=200):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    if method == "POST":
        response = requests.post(url, headers=headers, json={"limit": 10, "max_cards": 10}) # Dummy payload for flashcards
    else:
        response = requests.get(url, headers=headers)
    
    if response.status_code == expected_status:
        print(f"✅ Access to {endpoint} returned {response.status_code} as expected.")
        return True
    else:
        print(f"❌ Access to {endpoint} returned {response.status_code}, expected {expected_status}. Body: {response.text}")
        return False

def main():
    print("--- Verifying Security ---")
    
    import time
    timestamp = int(time.time() * 1000)
    username = f"verify_user_{timestamp}"
    password = "testpassword123"

    # 1. Register new user (Role: user)
    print(f"Registering new user: {username}")
    reg_url = f"{BASE_URL}/auth/register"
    reg_res = requests.post(reg_url, json={"username": username, "password": password})
    if reg_res.status_code != 200:
        print(f"Registration failed: {reg_res.text}")
        return

    # 2. Login
    token = login(username, password)
    if not token:
        print("Login failed after registration. Aborting.")
        return
    print(f"Logged in as {username}")

    # 3. Test Restricted Endpoint
    print("\nTesting /flashcards/generate as USER (Expect 403 Forbidden):")
    success = test_endpoint(token, "/flashcards/generate", expected_status=403)
    
    if success:
        print("\n✅ SUCCESS: Restricted endpoint blocked non-admin user.")
    else:
        print("\n❌ FAILURE: Restricted endpoint did NOT block non-admin user.")

if __name__ == "__main__":
    main()
