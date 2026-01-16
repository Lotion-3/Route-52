import os
import re
import time
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
    store_names: List[str]
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    
    # Track original names to map Gemini's output back correctly
    normalized_to_orig = {normalize_grocery_name(k): k for k in ingredient_quantities.keys()}
    search_items = list(normalized_to_orig.keys())
    print(search_items)
    price_database = {store: {} for store in store_names}
    batch_size = 15
    
    print(f"📦 Processing {len(search_items)} items in batches of {batch_size}...")

    for i in range(0, len(search_items), batch_size):
        batch = search_items[i:i + batch_size]
        print(f"🔄 Fetching Batch {int(i/batch_size) + 1}...")

        prompt = (f"Provide a JSON price table for grocery items. "
                  f"Group similar items together. "
                  f"Columns are the following adresses: {', '.join(store_names)} "
                  f"Rows are the following items: {', '.join(batch)} "
                  f"If retail price is unavailable online please leave price blank")

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_mime_type="application/json",
                    response_schema=GroceryPricesResponse,
                )
            )
            
            if response.parsed:
                for store_data in response.parsed.stores:
                    # Fuzzy match store name: "Walmart" -> "Walmart Supercenter 1"
                    matched_store = next((s for s in price_database.keys() 
                                         if store_data.store_name.lower() in s.lower() 
                                         or s.lower() in store_data.store_name.lower()), None)
                    
                    if matched_store:
                        for item in store_data.items:
                            gemini_norm = normalize_grocery_name(item.item_name)
                            # Link back to original recipe name
                            orig_name = normalized_to_orig.get(gemini_norm)
                            if not orig_name:
                                matches = get_close_matches(gemini_norm, normalized_to_orig.keys(), n=1, cutoff=0.7)
                                if matches: orig_name = normalized_to_orig[matches[0]]
                            
                            if orig_name:
                                price_database[matched_store][orig_name] = item.price
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Warning: Batch failed: {e}")
            continue

    # --- UPDATED: Final Summary with Missing Ingredient Tracking ---
    print("\n" + "="*50)
    print("STORE AVAILABILITY SUMMARY")
    print("="*50)
    
    all_required_names = list(ingredient_quantities.keys())
    
    for store in store_names:
        # Get what we actually found in this specific store
        found_in_this_store = price_database.get(store, {}).keys()
        found_normalized = {normalize_grocery_name(f) for f in found_in_this_store}
        
        # Determine exactly which original ingredients are missing
        missing_ingredients = [
            item for item in all_required_names 
            if normalize_grocery_name(item) not in found_normalized
        ]
        
        found_count = len(all_required_names) - len(missing_ingredients)
        print(f"\n📍 {store} | Found: {found_count}/{len(all_required_names)}")
        
        if missing_ingredients:
            # Display first 10 missing items so you can debug the list
            print(f"❌ Missing ({len(missing_ingredients)}): {', '.join(missing_ingredients[:10])}...")
        else:
            print("✅ 100% Items Available")

    # Clean empty stores and prepare outputs
    price_database = {k: v for k, v in price_database.items() if v}
    shopping_list = [{"name": k, "qty": v} for k, v in ingredient_quantities.items()]
    
    return price_database, [], shopping_list