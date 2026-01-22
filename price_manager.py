import os
import re
import time
import json
import ast
from typing import Dict, List, Tuple, Union
from google import genai
from google.genai import types
from pydantic import BaseModel
from difflib import get_close_matches

# --- 1. SHARED NORMALIZATION LOGIC ---

def normalize_grocery_name(name: str) -> str:
    """Standardizes names so 'tomatoe' or 'tomatoes, diced' matches 'tomato'."""
    name = name.lower().strip()
    # Remove descriptors after commas
    name = re.split(r',', name)[0]
    # Remove common culinary adjectives
    culinary_terms = [r'\bboiled\b', r'\bcooked\b', r'\bfrozen\b', r'\bfresh\b', r'\bdiced\b', r'\bwhole\b']
    for term in culinary_terms:
        name = re.sub(term, '', name)
    # Fix spelling and plurals
    name = re.sub(r'tomatoe', 'tomato', name)
    name = re.sub(r'atoes\b', 'ato', name)
    name = re.sub(r's\b', '', name)
    return name.strip()

# --- 2. GEMINI SCHEMA DEFINITIONS ---

class ItemPrice(BaseModel):
    item_name: str
    price: float

class StoreInventory(BaseModel):
    store_name: str
    items: List[ItemPrice]

class GroceryPricesResponse(BaseModel):
    stores: List[StoreInventory]

# --- 3. MAIN PRICE FETCHING FUNCTION ---

def fetch_grocery_prices(
    ingredient_quantities: Dict[str, int], 
    store_names: List[str],
    store_addresses: Dict[str, str] = {}
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_L"))
    
    # Track original names to map Gemini's output back correctly
    normalized_to_orig = {normalize_grocery_name(k): k for k in ingredient_quantities.keys()}
    search_items = list(normalized_to_orig.keys())
    price_database = {store: {} for store in store_names}
    
    print(f"📦 Processing {len(search_items)} items across {len(store_names)} stores...")

    # Process one store at a time with ALL items in a single request
    for store_name in store_names:
        store_address = store_addresses.get(store_name, 'Unknown Address')
        
        print(f"\n🏪 Checking: {store_name} ({store_address})")
        print(f"  🔍 Searching for all {len(search_items)} items...")

        prompt = (
            f"Please use Search with grounding to find current retail prices for these items at: {store_name} located at {store_address}.\n"
            f"If absolutely current prices are not available, use the most recent prices you can find."
            f"If exact item is not available, find the closest match.\n"
            f"Items: {', '.join(search_items)}.\n\n"
            f"Return a JSON object: {{'stores': [{{'store_name': '{store_name}', 'items': [{{'item_name': 'Name', 'price': 0.00}}]}}]}}.\n\n"
            f"CRITICAL RULES:\n"
            f"1. Search for prices SPECIFICALLY at this address.\n"
            f"2. ONLY include an item if you find a REAL, NON-ZERO price. DO NOT use 0.0 or null as a placeholder. If not found, omit the item.\n"
            f"3. Return ONLY valid JSON."
        )

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )
            )
            
            response_text = response.text
            
            # Improved JSON extraction with multiple strategies
            json_str = None
            
            # Strategy 1: Look for JSON code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    json_str = response_text[start:end].strip()
            
            # Strategy 2: Look for raw JSON (curly braces)
            if not json_str:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
            
            if json_str:
                try:
                    # Try standard JSON parsing first
                    try:
                        parsed_data = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Fallback: Try parsing as Python dict (single quotes)
                        parsed_data = ast.literal_eval(json_str)
                    
                    stores_data = parsed_data.get('stores', [])
                    print(f"  ✅ Parsed JSON with {len(stores_data)} store(s)")
                    
                    if len(stores_data) == 0:
                        print(f"  📝 DEBUG - Full parsed data: {parsed_data}")
                    
                    for store_entry in stores_data:
                        store_name_raw = store_entry.get('store_name', '')
                        items_list = store_entry.get('items', [])
                        print(f"    📦 Store: {store_name_raw}, Items: {len(items_list)}")
                        
                        # Fuzzy match store name
                        matched_store = next((s for s in store_names 
                                              if store_name_raw.lower() in s.lower() 
                                              or s.lower() in store_name_raw.lower()), None)
                        
                        if matched_store:
                            found_count = 0
                            for item in items_list:
                                name_raw = item.get('item_name')
                                price_raw = item.get('price')
                                
                                # Filter out None, zero, or negative prices
                                try:
                                    if name_raw and price_raw is not None:
                                        price_float = float(price_raw)
                                        if price_float > 0:
                                            gemini_norm = normalize_grocery_name(name_raw)
                                            
                                            orig_name = normalized_to_orig.get(gemini_norm)
                                            if not orig_name:
                                                matches = get_close_matches(gemini_norm, normalized_to_orig.keys(), n=1, cutoff=0.7)
                                                if matches: orig_name = normalized_to_orig[matches[0]]
                                            
                                            if orig_name:
                                                print(f"      🛒 Found: {orig_name} at ${price_float}")
                                                price_database[matched_store][orig_name] = price_float
                                                found_count += 1
                                            else:
                                                print(f"      ⚠️  No match for '{name_raw}' (normalized: '{gemini_norm}')")
                                except (ValueError, TypeError) as e:
                                    print(f"      ⚠️  Error processing item: {e}")
                                    continue
                            
                            if found_count == 0 and len(items_list) > 0:
                                print(f"      ⚠️  No items matched from {len(items_list)} returned items")
                                print(f"      📝 Sample item: {items_list[0] if items_list else 'N/A'}")
                        else:
                             print(f"    ❌ No match for store: '{store_name_raw}'")
                except (json.JSONDecodeError, ValueError, SyntaxError) as e:
                    print(f"  ⚠️  JSON parse failed for {store_name}: {e}")
                    print(f"  📝 Extracted JSON (first 300 chars): {json_str[:300]}...")
            else:
                print(f"  ⚠️  Could not find JSON in response for {store_name}")
                print(f"  📝 Response (first 300 chars): {response_text[:300]}...")


            time.sleep(2)  # Increased delay to avoid rate limiting
        except Exception as e:
            print(f"  ⚠️  Request failed: {e}")
            import traceback
            traceback.print_exc()
            continue

    # --- Final Summary ---
    print("\n" + "="*50)
    print("STORE AVAILABILITY SUMMARY")
    print("="*50)
    
    all_required_names = list(ingredient_quantities.keys())
    for store in store_names:
        found_in_store = price_database.get(store, {})
        found_normalized = {normalize_grocery_name(f) for f in found_in_store.keys()}
        
        missing = [item for item in all_required_names if normalize_grocery_name(item) not in found_normalized]
        found_count = len(all_required_names) - len(missing)
        
        print(f"📍 {store} | Found: {found_count}/{len(all_required_names)}")
        if missing and found_count > 0:
            print(f"   Missing examples: {', '.join(missing[:5])}...")
        elif found_count == 0:
            print("   ❌ No items found for this location.")

    # Clean empty stores and prepare outputs
    price_database = {k: v for k, v in price_database.items() if v}
    shopping_list = [{"name": k, "qty": v} for k, v in ingredient_quantities.items()]
    
    return price_database, [], shopping_list
