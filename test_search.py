import os
import time
from typing import Dict, List
from price_manager import fetch_grocery_prices
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config.env')

def test_walmart_search():
    print("==========================================")
    print("🧪 TESTING WALMART PRICE SEARCH")
    print("==========================================")

    # 1. Check API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY not found in config.env")
        return

    # 2. Define targeted data
    ingredients: Dict[str, int] = {
        "milk": 1,
        "bread": 1,
        "banana": 1,
        "chicken breast": 1
    }
    
    stores: List[str] = [
        "Walmart",
        "Kroger"
    ]
    
    addresses: Dict[str, str] = {
        "Walmart": "12791 Truman Ct, Carmel, IN",
        "Kroger": "1217 S Rangeline Rd, Carmel, IN"
    }

    print(f"\n📝 Requesting prices for: {list(ingredients.keys())}")
    print(f"🏪 Stores: {stores}")

    # 3. Call the function
    try:
        start_time = time.time()
        price_db, missing, shopping_list = fetch_grocery_prices(ingredients, stores, addresses)
        end_time = time.time()
        
        print("\n==========================================")
        print("🎉 SUCCESS! No exceptions raised.")
        print(f"⏱️ Time taken: {end_time - start_time:.2f} seconds")
        print("==========================================")
        
        print("\n📊 Price Database Results:")
        for store in stores:
            items = price_db.get(store, {})
            print(f"\n📍 {store}:")
            if not items:
                print("   (No items found)")
            for item, price in items.items():
                print(f"   - {item}: ${price}")

    except Exception as e:
        print(f"\n💥 FAILED! Exception occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_walmart_search()
