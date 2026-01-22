import os
import re
import time
import json
import ast
from typing import Dict, List, Tuple, Union
from google import genai
from google.genai import types
from pydantic import BaseModel

# --- 1. DIRECT MATCHING LOGIC ---

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
    
    # Track original names for direct matching
    search_items = list(ingredient_quantities.keys())
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
            
            # Check if response is None
            if response_text is None:
                print(f"  ⚠️  No response text received for {store_name}")
                continue
            
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
                        
                        # Use the store name as provided by Gemini
                        matched_store = store_name_raw
                        
                        # Initialize store in database if not exists
                        if matched_store not in price_database:
                            price_database[matched_store] = {}
                        
                        for item in items_list:
                            name_raw = item.get('item_name')
                            price_raw = item.get('price')
                            
                            # Accept all items as returned by Gemini
                            try:
                                if name_raw is not None and price_raw is not None:
                                    price_float = float(price_raw)
                                    
                                    # Map Gemini's detailed name back to original ingredient name
                                    matched_ingredient = None
                                    for original_name in search_items:
                                        # Check if original ingredient is contained in Gemini's response
                                        if original_name.lower() in name_raw.lower() or name_raw.lower() in original_name.lower():
                                            matched_ingredient = original_name
                                            break
                                    
                                    # Use matched ingredient name, or fall back to Gemini's name
                                    final_name = matched_ingredient if matched_ingredient else name_raw
                                    price_database[matched_store][final_name] = price_float
                                    
                                    if matched_ingredient:
                                        print(f"      🛒 Accepted: {name_raw} -> {matched_ingredient} at ${price_float}")
                                    else:
                                        print(f"      🛒 Accepted: {name_raw} at ${price_float}")
                            except (ValueError, TypeError) as e:
                                print(f"      ⚠️  Error processing item: {e}")
                                continue
                except (json.JSONDecodeError, ValueError, SyntaxError) as e:
                    print(f"  ⚠️  JSON parse failed for {store_name}: {e}")
                    print(f"  📝 Extracted JSON (first 300 chars): {json_str[:300]}...")
            else:
                print(f"  ⚠️  Could not find JSON in response for {store_name}")
                print(f"  📝 Response (first 300 chars): {response_text[:300]}...")


            time.sleep(5)  # Increased delay to avoid rate limiting
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
        
        missing = [item for item in all_required_names if item not in found_in_store.keys()]
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
