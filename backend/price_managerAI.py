import os
from typing import List, Dict, Tuple, Union
from google import genai
from google.genai import types
from pydantic import BaseModel

# --- 1. SCHEMA ---
class PriceRow(BaseModel):
    store_name: str
    item_name: str
    price: float

class GroceryTableResponse(BaseModel):
    items_found: List[PriceRow]

# --- 2. THE TWO-STEP FUNCTION ---

def fetch_grocery_prices(
    ingredient_quantities: Dict[str, int], 
    store_names: List[str],
    store_addresses: Dict[str, str] = {}
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_L"))
    search_items = list(ingredient_quantities.keys())
    price_database = {store: {} for store in store_names}
    
    # Process stores in batches
    BATCH_SIZE = 3
    for i in range(0, len(store_names), BATCH_SIZE):
        batch = store_names[i:i + BATCH_SIZE]
        location_targets = [f"{name} ({store_addresses.get(name, 'N/A')})" for name in batch]
        
        print(f"🔍 Step 1: Searching for items in {', '.join(batch)}...")

        # STEP 1: Search Grounding (No Schema allowed here)
        search_prompt = (
            f"Find current retail prices for: {', '.join(search_items)}.\n"
            f"Locations: {'; '.join(location_targets)}.\n"
            "List each found item with its store and price clearly."
        )

        try:
            search_res = client.models.generate_content(
                model="gemini-2.0-flash", # Best for search
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.0
                )
            )
            
            if not search_res.text:
                continue

            print(f"✨ Step 2: Formatting data with Flash-Lite...")

            # STEP 2: Use the ultra-fast 2.5 Flash-Lite for JSON structuring
            struct_prompt = f"Convert these search results into a JSON table:\n\n{search_res.text}"
            
            struct_res = client.models.generate_content(
                model="gemini-2.5-flash-lite", # Fastest & cheapest for formatting
                contents=struct_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GroceryTableResponse,
                )
            )

            if struct_res.parsed:
                for row in struct_res.parsed.items_found:
                    # Map back to the correct store key
                    matched_store = next((s for s in batch if s.lower() in row.store_name.lower()), None)
                    if matched_store:
                        price_database[matched_store][row.item_name.lower().strip()] = row.price
                
                print(f" ✅ Batch complete.")

        except Exception as e:
            print(f" ❌ Batch failed: {e}")
            continue

    # Clean up and return the 3 values main.py expects
    removed_items = [] 
    shopping_list = [{"name": k, "qty": v} for k, v in ingredient_quantities.items()]
    
    return price_database, removed_items, shopping_list