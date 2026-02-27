import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_caching():
    payload = {
        "preferences": {
            "address": "100 Monument Circle, Indianapolis, IN",
            "shopping_time_hours": 3.0,
            "days_plan": 3, # Short plan for speed
            "meals_per_day": 3
        }
    }

    print("--- FIRST REQUEST (Expecting API Calls) ---")
    start_1 = time.time()
    resp1 = requests.post(f"{BASE_URL}/generate_plan", json=payload)
    end_1 = time.time()
    print(f"Status: {resp1.status_code}")
    print(f"Time: {end_1 - start_1:.2f}s")

    print("\n--- SECOND REQUEST (Expecting Cache) ---")
    start_2 = time.time()
    resp2 = requests.post(f"{BASE_URL}/generate_plan", json=payload)
    end_2 = time.time()
    print(f"Status: {resp2.status_code}")
    print(f"Time: {end_2 - start_2:.2f}s")
    
    saved_time = (end_1 - start_1) - (end_2 - start_2)
    print(f"\n✅ Savings: {saved_time:.2f}s")

if __name__ == "__main__":
    try:
        test_caching()
    except Exception as e:
        print(f"Error: {e}. Is the server running?")
