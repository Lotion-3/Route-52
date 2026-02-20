
import os
import time
from dotenv import load_dotenv
load_dotenv('config.env')
from google import genai
from google.genai import types

def test_model():
    print("Testing gemini-2.0-flash-exp...")
    # Using the same key env var as price_manager.py
    api_key = os.environ.get("GEMINI_API_KEY_L")
    if not api_key:
        print("GEMINI_API_KEY_L not found.")
        return

    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents="Hello, this is a test.",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
        )
        print("Success!")
        print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_model()
