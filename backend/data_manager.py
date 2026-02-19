import random
import json
import csv
import os
from typing import List, Dict, Any
from google import genai
from google.genai import types
from pydantic import BaseModel

# Initialize Gemini Client (using existing env var pattern)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY_V")
client = genai.Client(api_key=GEMINI_API_KEY)

def load_csv_prices(csv_path: str = "alanVeggies.csv") -> List[Dict[str, Any]]:
    """Loads all data from alanVeggies.csv."""
    data = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
    except FileNotFoundError:
        print(f"Warning: {csv_path} not found.")
    return data

class PriceResponse(BaseModel):
    prices: Dict[str, float]

def get_gemini_synthetic_prices(missing_items_with_units: List[str]) -> Dict[str, float]:
    """Asks Gemini for reasonable fresh produce/grocery prices for specific units."""
    if not missing_items_with_units:
        return {}
    
    prompt = (
        f"Provide reasonable average retail prices (in USD) for ALL items below. "
        "Each price must be for the EXACT unit specified:\n"
        f"{', '.join(missing_items_with_units)}\n\n"
        "Return the response as a JSON object where keys are the ingredient names (strip the unit from the key) and values are float prices."
    )
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PriceResponse,
            )
        )
        return response.parsed.prices
    except Exception as e:
        print(f"Gemini Price Fetch Error: {e}")
        # Fallback to random prices (parsing name from "Name (Unit)")
        return {item.split(' (')[0]: round(random.uniform(2.0, 8.0), 2) for item in missing_items_with_units}

def generate_synthetic_market(ingredient_data: Dict[str, Dict[str, Any]], store_names: List[str]):
    csv_data = load_csv_prices()
    
    # 1. Map ingredients to CSV items or mark as missing
    market_prices = {}
    matched_base_prices = {}
    missing_items_with_units = []
    shopping_list = []
    
    # Extract names and quantities
    for item_raw, metadata in ingredient_data.items():
        item_name = item_raw.strip()
        qty = metadata.get("qty", 1)
        unit = metadata.get("unit", "units")
        shopping_list.append({"name": item_name, "qty": qty})
        
        item_lower = item_name.lower()
        found = False
        for row in csv_data:
            if item_lower in row['Vegetable'].lower() or row['Vegetable'].lower() in item_lower:
                base = float(row.get('Indianapolis', row['RetailPrice']))
                matched_base_prices[item_name] = base
                found = True
                break
        if not found:
            missing_items_with_units.append(f"{item_name} ({unit})")
            
    # 2. Get missing prices from Gemini
    if missing_items_with_units:
        print(f"Fetching base prices for missing items from Gemini: {missing_items_with_units}")
        gemini_prices = get_gemini_synthetic_prices(missing_items_with_units)
        matched_base_prices.update(gemini_prices)
    
    # 3. Generate store-specific variations
    price_database = {}
    
    # Store archetypes for realistic pricing variations
    store_types = {
        "Aldi": 0.85,
        "Trader Joe's": 0.95,
        "Kroger": 1.0,
        "Meijer": 1.0,
        "Walmart": 0.9,
        "Whole Foods": 1.4,
        "Costco": 0.8  # Bulk usually means lower unit price
    }

    for store_raw in store_names:
        store = store_raw.strip()
        price_database[store] = {}
        # Determine multiplier based on name
        multiplier = 1.0
        for name, mult in store_types.items():
            if name.lower() in store.lower():
                multiplier = mult
                break
        
        for item, base_price in matched_base_prices.items():
            # Apply store multiplier + random variance (+/- 10%)
            # This satisfies "somehow come up with a random price" while keeping it grounded
            variance = random.uniform(0.9, 1.1)
            final_price = round(base_price * multiplier * variance, 2)
            price_database[store][item.lower().strip()] = final_price

    # Save to JSON as requested
    with open("market_data.json", "w") as f:
        json.dump(price_database, f, indent=4)
        
    # Return format compatible with optimizer: price_database, removed_items (empty), shopping_list
    return price_database, [], shopping_list

if __name__ == "__main__":
    # Test block
    test_ing = {"Carrots": {"qty": 1}, "Organic Spinach": {"qty": 2}, "Dragonfruit": {"qty": 1}, "Zucchini": {"qty": 3}}
    test_stores = ["Kroger 123", "Walmart Supercenter", "Whole Foods Market"]
    start_db, _, shop_list = generate_synthetic_market(test_ing, test_stores)
    print("✅ Synthetic market data generated in market_data.json")
    print(json.dumps(start_db, indent=2))
