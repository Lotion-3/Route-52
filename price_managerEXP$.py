import os
import re
from typing import List, Dict, Tuple, Any
from serpapi import GoogleSearch
from dotenv import load_dotenv

load_dotenv("config.env")
SERPAPI_KEY = os.getenv("GOOGLE_SEARCH_KEY")

def fetch_grocery_prices(
    ingredient_data: Dict[str, Dict[str, Any]], 
    store_names: List[str], 
    store_addresses: Dict[str, str]
) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    
    price_database = {}
    removed_items = []
    
    # regex for price: handles "$4.99", "$ 4.99", and "$2 .99"
    PRICE_RE = r'\$\s?(\d+)\s?\.?(\d{2})?'
    # Comprehensive units logic
    UNIT_RE = r'(\d+(?:\.\d+)?)\s?(oz|ounce|fl\s?oz|lb|pound|g|gram|kg|ml|l|liter|gal|gallon|ct|count|each|pk|pack|bag|box)'

    for store in store_names:
        price_database[store] = {}
        full_address = store_addresses.get(store, "")
        city_area = ", ".join(full_address.split(",")[-2:]).strip() if "," in full_address else full_address

        for item_name, metadata in ingredient_data.items():
            search_term = metadata.get("query", item_name)
            
            # Initial contextual fallback from your Meal Plan
            current_best = {
                "price": None, 
                "unit_size": metadata.get("qty", 1.0), 
                "unit_type": metadata.get("unit", "unit")
            }

            # Try exact address first, then city fallback
            queries = [f"{search_term} price at {store} {full_address}", f"{search_term} price at {store} {city_area}"]
            
            found_valid_price = False
            for q in queries:
                if found_valid_price: break 
                
                try:
                    # Fetching top 5 results for the same credit cost as 1
                    search = GoogleSearch({"engine": "google", "q": q, "api_key": SERPAPI_KEY, "num": 5})
                    results = search.get_dict().get("organic_results", [])
                    
                    # --- NEW: LOOP THROUGH ALL 5 RESULTS ---
                    for res in results:
                        snippet = res.get("snippet", "").lower()
                        
                        price_match = re.search(PRICE_RE, snippet)
                        if price_match:
                            # 1. Capture the price
                            whole = price_match.group(1)
                            dec = price_match.group(2) if price_match.group(2) else "00"
                            price_val = float(f"{whole}.{dec}")
                            
                            if price_val > 0:
                                current_best["price"] = price_val
                                
                                # 2. Capture the unit from THIS specific snippet
                                u_match = re.search(UNIT_RE, snippet)
                                if u_match:
                                    current_best["unit_size"] = float(u_match.group(1))
                                    current_best["unit_type"] = u_match.group(2)
                                elif any(x in snippet for x in ["/lb", "per lb", "lb.", "pound"]):
                                    current_best["unit_size"] = 1.0
                                    current_best["unit_type"] = "lb"
                                
                                found_valid_price = True
                                break # Exit the 5-result loop
                except:
                    continue

            if current_best["price"]:
                price_database[store][item_name] = current_best
            else:
                print(f"   ⚠️  Skipping {item_name}: No valid price found in top 5 results.")

    shopping_list = [{"name": k, "qty_data": v} for k, v in ingredient_data.items()]
    return price_database, removed_items, shopping_list

# --- SEAMLESS TEST CALL ---
if __name__ == "__main__":
    # 1. Define the ingredients as requested
    test_ingredients = {
        "watermelon": {
            "qty": 4.0, 
            "unit": "lb", 
            "query": "seedless watermelon", 
            "strategy": "weighted"
        },
        "banana": {
            "qty": 3.0, 
            "unit": "lb", 
            "query": "fresh bananas", 
            "strategy": "weighted"
        },
        "paprika": {
            "qty": 3.0, 
            "unit": "oz", 
            "query": "ground paprika", 
            "strategy": "unit"
        },
        "chicken thigh": {
            "qty": 4.0, 
            "unit": "lb", 
            "query": "boneless chicken thighs", 
            "strategy": "weighted"
        }
    }
    
    # 2. Define the store and address as requested
    test_stores = ["Kroger"]
    test_addresses = {
        "Kroger": "3387 Maple Ave, Zanesville, OH 43701"
    }
    
    # 3. Execute the fetch
    # This matches the signature expected by main.py
    price_db, removed_items, shopping_list = fetch_grocery_prices(
        test_ingredients, 
        test_stores, 
        test_addresses
    )
    
    # 4. Print results for verification
    print("\n" + "=" * 60)
    print("TEST EXECUTION RESULTS")
    print("=" * 60)
    for store in price_db:
        print(f"📍 Store: {store}")
        for item, data in price_db[store].items():
            price = data['price']
            size = data['unit_size']
            utype = data['unit_type']
            print(f"   ✅ {item.capitalize():<15} | ${price:>5.2f} / {size} {utype}")
    
    if not price_db["Kroger"]:
        print("❌ No price data could be retrieved for this store.")
    print("=" * 60)