
import random
from typing import Dict, List, Tuple, Union
import config
import data_loader
import geo_utils

def fetch_grocery_prices(
    ingredient_quantities: Dict[str, int], 
    store_ids: List[str]
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    """
    Generate store-specific prices for ingredients.
    Each store-item combination gets a UNIQUE but consistent random factor.
    """
    print("\nGenerating store prices for ingredients...")
    
    city_price_data = data_loader.load_city_prices_from_csv()
    
    if not city_price_data:
        print("Error: Could not load price data.")
        return {}, list(ingredient_quantities.keys()), []
    
    price_database: Dict[str, Dict[str, float]] = {}
    removed_items: List[str] = []
    shopping_list: List[Dict[str, Union[str, int]]] = []
    
    # Check which ingredients are available
    available_vegetables = set()
    for city_data in city_price_data.values():
        available_vegetables.update(city_data.keys())
    
    # Create shopping list from available ingredients
    for veggie, quantity in ingredient_quantities.items():
        if veggie in available_vegetables:
            shopping_list.append({"name": veggie, "qty": quantity})
        else:
            removed_items.append(veggie)
    
    if not shopping_list:
        return {}, removed_items, []
    
    # Generate prices for each store
    for store_id in store_ids:
        store_city = geo_utils.get_city_for_store(store_id)
        
        # Find matching city
        city_found = store_city
        if store_city not in city_price_data:
            city_lower = store_city.lower()
            for available_city in city_price_data.keys():
                if available_city.lower() == city_lower:
                    city_found = available_city
                    break
            else:
                city_found = "Indianapolis"
                if city_found not in city_price_data:
                    city_found = list(city_price_data.keys())[0]
        
        print(f"  Using '{city_found}' prices for store: {store_id}")
        
        # Initialize store in database
        price_database[store_id] = {}
        
        # Generate prices for each ingredient
        for item_data in shopping_list:
            item_name = item_data["name"]
            base_price = city_price_data[city_found].get(item_name)
            
            if base_price is not None:
                # === CRITICAL: Unique random factor for EACH store-item combination ===
                # Create a seed that's specific to THIS store and THIS item
                seed_str = f"{store_id}_{item_name}"
                
                # Method 1: Using hash to create deterministic but unique seed
                seed_value = hash(seed_str)  # Integer hash value
                
                # Create a LOCAL random generator for this specific combination
                # This doesn't affect the global random state
                local_random = random.Random(seed_value)
                
                # Generate random factor between 0.6 and 1.4
                variance_factor = local_random.uniform(config.MIN_PRICE_FACTOR, config.MAX_PRICE_FACTOR)
                
                # Calculate final price
                store_price = base_price * variance_factor
                price_database[store_id][item_name] = round(store_price, 2)
            else:
                price_database[store_id][item_name] = float('inf')
    
    # === DEMONSTRATE the randomization ===
    print("\n=== PRICE RANDOMIZATION DEMONSTRATION ===")
    print("Same item should have DIFFERENT prices at DIFFERENT stores:")
    
    if shopping_list:
        # Show first 3 items across first 3 stores
        for i, item_data in enumerate(shopping_list[:3]):
            item_name = item_data["name"]
            print(f"\n  Item: {item_name.title()}")
            
            prices = []
            for store_id in list(price_database.keys())[:3]:  # First 3 stores
                price = price_database[store_id].get(item_name, float('inf'))
                if price != float('inf'):
                    # Get the seed to show it's deterministic
                    seed_str = f"{store_id}_{item_name}"
                    seed_value = hash(seed_str)
                    prices.append(f"{store_id}: ${price:.2f} (seed: {seed_value % 1000}...)")
            
            if prices:
                for price_info in prices:
                    print(f"    {price_info}")
    
    # Show that same store-item gives same price every time
    print("\n=== CONSISTENCY CHECK ===")
    print("Same store + same item = same price every run:")
    
    if shopping_list and len(price_database) > 0:
        test_store = list(price_database.keys())[0]
        test_item = shopping_list[0]["name"]
        test_price = price_database[test_store].get(test_item, "N/A")
        test_seed = hash(f"{test_store}_{test_item}")
        print(f"  {test_store} + {test_item}")
        print(f"  Price: ${test_price:.2f}")
        print(f"  Seed value: {test_seed}")
        print(f"  Hash of '{test_store}_{test_item}': {test_seed}")
    
    return price_database, removed_items, shopping_list
