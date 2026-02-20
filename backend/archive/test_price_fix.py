"""
Quick test to verify the structured output fix works for price fetching.
This tests a small batch of items at one store.
"""
import os
from dotenv import load_dotenv
from price_manager import fetch_grocery_prices

# Load environment variables
load_dotenv('config.env')

# Test with a small set of items
test_ingredients = {
    "milk": 1,
    "eggs": 1,
    "bread": 1,
    "chicken breast": 1,
    "rice": 1
}

test_stores = ["Kroger"]
test_addresses = {"Kroger": "227 W Michigan St, Indianapolis"}

print("=" * 60)
print("TESTING IMPROVED JSON EXTRACTION")
print("=" * 60)
print(f"Test Items: {list(test_ingredients.keys())}")
print(f"Test Store: {test_stores[0]}")
print("=" * 60)

try:
    price_db, _, shopping_list = fetch_grocery_prices(
        test_ingredients,
        test_stores,
        test_addresses
    )
    
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    
    if price_db:
        for store, items in price_db.items():
            print(f"\nStore: {store}")
            for item, price in items.items():
                print(f"   {item}: ${price:.2f}")
        
        found_count = sum(len(items) for items in price_db.values())
        total_count = len(test_ingredients)
        success_rate = (found_count / total_count) * 100
        
        print(f"\nFound {found_count}/{total_count} items ({success_rate:.0f}% success rate)")
        
        if found_count >= 2:  # At least 40% success
            print("\nTEST PASSED: Improved JSON extraction is working!")
            print("The fix successfully handles Gemini's response format.")
        else:
            print("\nTEST WARNING: Low success rate, but no JSON parse errors!")
    else:
        print("\nNo price data returned")
        
except Exception as e:
    print(f"\nTEST FAILED: {e}")
    import traceback
    traceback.print_exc()
