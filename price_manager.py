import os
import re
import requests
from typing import List, Dict, Tuple, Any
from dotenv import load_dotenv

load_dotenv("config.env")
SEARCHAPI_KEY = os.getenv("SEARCHAPI_API_KEY")

def fetch_grocery_prices(
    ingredient_data: Dict[str, Dict[str, Any]], 
    store_names: List[str], 
    store_addresses: Dict[str, str]
) -> Tuple[Dict[str, float], List[str], List[Dict[str, Any]]]:
    
    price_database = {}
    removed_items = []
    
    # Improved regex for prices and retail units
    PRICE_RE = r'\$\s?(\d+)\s?\.?(\d{2})?'
    UNIT_RE = r'(\d+(?:\.\d+)?)\s?(oz|ounce|fl\s?oz|lb|pound|g|gram|kg|ml|l|liter|gal|gallon|ct|count|each|pk|pack|bag|box)'

    for store in store_names:
        price_database[store] = {}
        full_address = store_addresses.get(store, "")
        
        # Format location for SearchApi.io (e.g., "Zanesville, OH, US")
        addr_parts = full_address.split(",")
        canonical_location = ", ".join(addr_parts[-3:]).strip() if len(addr_parts) >= 3 else full_address

        print(f"\n📡 Fetching live prices for {store} in {canonical_location}...")

        for item_name, metadata in ingredient_data.items():
            search_term = metadata.get("query", item_name)
            query = f"{search_term} price at {store}"
            
            try:
                url = "https://www.searchapi.io/api/v1/search"
                params = {
                    "engine": "google",
                    "q": query,
                    "api_key": SEARCHAPI_KEY,
                    "location": canonical_location,
                    "gl": "us",
                    "hl": "en"
                }
                
                response = requests.get(url, params=params, timeout=15)
                
                if response.status_code == 400:
                    params.pop("location", None)
                    response = requests.get(url, params=params, timeout=15)

                if response.status_code != 200:
                    print(f"   ❌ Error {response.status_code} for {item_name}")
                    continue
                
                results = response.json().get("organic_results", [])
                
                found_item = False
                for res in results[:5]: 
                    snippet = res.get("snippet", "").lower()
                    price_match = re.search(PRICE_RE, snippet)
                    
                    if price_match:
                        # Total price found in snippet
                        total_price = float(f"{price_match.group(1)}.{price_match.group(2) or '00'}")
                        
                        if total_price > 0.10:
                            # Find unit size in snippet to normalize
                            u_match = re.search(UNIT_RE, snippet)
                            u_size = float(u_match.group(1)) if u_match else 1.0
                            
                            # NORMALIZATION: Calculate price per 1 unit (e.g., $ per 1 lb)
                            # This makes it compatible with optimizer.py's math
                            price_per_unit = total_price / u_size

                            price_database[store][item_name] = price_per_unit
                            
                            print(f"   ✅ {item_name.capitalize():<15} | ${price_per_unit:>6.2f} per {metadata.get('unit', 'unit')}")
                            found_item = True
                            break
                
                if not found_item:
                    print(f"   ❕ No price data in snippets for: {item_name}")

            except Exception as e:
                print(f"   ⚠️ Error processing {item_name}: {e}")

    # Prepare shopping list for optimizer (converting dict to list of dicts)
    shopping_list = [{"name": k, "qty": v.get("qty", 1)} for k, v in ingredient_data.items()]
    return price_database, removed_items, shopping_list

if __name__ == "__main__":
    # Test block
    test_ingredients = {
        "watermelon": {"query": "whole seedless watermelon", "unit": "each", "qty": 1},
        "paprika": {"query": "ground paprika 2oz", "unit": "oz", "qty": 2}
    }
    test_stores = ["Kroger"]
    test_addr = {"Kroger": "Zanesville, Ohio, United States"}
    
    db, _, _ = fetch_grocery_prices(test_ingredients, test_stores, test_addr)