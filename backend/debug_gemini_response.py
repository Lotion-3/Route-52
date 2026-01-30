import os
import json
from google import genai
from google.genai import types

# Test script to see what Gemini actually returns
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

store_name = "Kroger"
store_address = "227 W Michigan St, Indianapolis"
item_batch = ["oatmeal", "milk", "eggs"]

prompt = (
    f"Use Google Search to find current retail prices for these items at: {store_name} located at {store_address}.\n"
    f"Items: {', '.join(item_batch)}.\n\n"
    f"Return a JSON object: {{'stores': [{{'store_name': '{store_name}', 'items': [{{'item_name': 'Name', 'price': 0.00}}]}}]}}.\n\n"
    f"CRITICAL RULES:\n"
    f"1. Search for prices SPECIFICALLY at this address.\n"
    f"2. ONLY include an item if you find a REAL, NON-ZERO price. DO NOT use 0.0 or null as a placeholder. If not found, omit the item.\n"
    f"3. Return ONLY valid JSON."
)

print("=" * 60)
print("SENDING PROMPT TO GEMINI:")
print("=" * 60)
print(prompt)
print("\n" + "=" * 60)

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
)

print("RAW RESPONSE:")
print("=" * 60)
print(response.text)
print("=" * 60)

# Try to extract JSON
response_text = response.text
json_start = response_text.find('{')
json_end = response_text.rfind('}') + 1

if json_start != -1 and json_end > json_start:
    json_str = response_text[json_start:json_end]
else:
    json_str = response_text

print("\nEXTRACTED JSON STRING:")
print("=" * 60)
print(json_str)
print("=" * 60)

# Try to parse
try:
    parsed = json.loads(json_str)
    print("\n✅ JSON PARSED SUCCESSFULLY!")
    print(json.dumps(parsed, indent=2))
except json.JSONDecodeError as e:
    print(f"\n❌ JSON PARSE FAILED: {e}")
    print(f"Error at position {e.pos}")
    if e.pos < len(json_str):
        start = max(0, e.pos - 50)
        end = min(len(json_str), e.pos + 50)
        print(f"\nContext around error:\n{json_str[start:end]}")
