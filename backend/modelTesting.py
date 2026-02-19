import os
import re
import time
import json
import ast
from typing import Dict, List, Tuple, Union
from google import genai
from google.genai import types

from dotenv import load_dotenv

# Load environment variables from config.env
load_dotenv('config.env')

# --- Configuration for the client ---
api_key = os.environ.get("GEMINI_API_KEY_L")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in config.env or environment variables. Please check your config.env file.")

client = genai.Client(api_key=api_key)

print("============================================================")
print("       TESTING GEMINI API WITH genai.Client (DIRECT CALL)")
print("============================================================")

# Directly specify a generative model name that appeared in your list
# Using 'models/gemini-2.0-flash-exp' as requested.
chosen_model_name = 'models/gemini-2.0-flash-exp'

print(f"\nAttempting to generate content directly using model: {chosen_model_name}")

try:
    # This is the call that failed for earlier experimental versions,
    # and should be the correct way to use the low-level client.
    prompt_content = "Briefly explain the concept of a 'Mediterranean Quinoa Bowl' and its main ingredients. Keep it concise."

    response = client.models.generate_content(
        model=chosen_model_name,
        contents=prompt_content
    )

    print("\n============================================================")
    print("                 GENERATION RESPONSE")
    print("============================================================")
    print(f"Prompt: {prompt_content}")
    print("\nResponse:")
    # Check if response has text, sometimes it can be empty or have parts
    if response and hasattr(response, 'text'):
        print(response.text)
    elif response and hasattr(response, 'parts'):
        print("Response has parts, but no direct text attribute. Parts:", response.parts)
    else:
        print("No direct text or parts found in response object.")
        print(f"Full response object: {response}")
    print("============================================================")

except Exception as e:
    print(f"❌ Error during content generation with {chosen_model_name}: {e}")
    print(f"   This means either the model '{chosen_model_name}' is not suitable for 'generateContent',")
    print(f"   or your API key doesn't have permissions for it, or there's a library configuration issue.")
    print(f"   Full error details: {e}")

print("\nScript finished.")