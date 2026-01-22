import os
import time
from typing import Dict, List
from price_manager import fetch_grocery_prices
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config.env')

def test_price_fetching():
    print("==========================================")
    print("🧪 TESTING GEMINI PRICE FETCHING FIX")
    print("==========================================")

    # 1. Check API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY not found in config.env")
        return

    print(f"✅ Found API Key: {api_key[:5]}...{api_key[-5:]}")

    # 2. Define dummy data
    ingredients: Dict[str, int] = {
        "apple": 1,
        "milk": 1,
        "bread": 1
    }
    
    stores: List[str] = [
        "Kroger",
        "Walmart",
        "Target"
    ]
    
    addresses: Dict[str, str] = {
        "Kroger": "123 Main St",
        "Walmart": "456 Market Blvd",
        "Target": "789 Broadway"
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
        for store, items in price_db.items():
            print(f"\n📍 {store}:")
            if not items:
                print("   (No items found)")
            for item, price in items.items():
                print(f"   - {item}: ${price}")

        print("\n❌ Missing Items:", missing)

    except Exception as e:
        print("\n==========================================")
        print(f"💥 FAILED! Exception occurred: {e}")
        print("==========================================")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_price_fetching()
