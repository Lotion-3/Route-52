import data_manager
import optimizer
import config

def test_repro():
    ingredient_quantities = {
        "vegan ricotta cheese": {"qty": 2.0, "unit": "each"},
        "fresh spinach": {"qty": 1.0, "unit": "lb"}
    }
    store_names = ["Costco", "Walmart"]
    
    # 1. Generate market
    price_database, _, shopping_list = data_manager.generate_synthetic_market(
        ingredient_quantities, store_names
    )
    
    print(f"Price DB Keys: {list(price_database['Costco'].keys())}")
    print(f"Shopping List: {shopping_list}")
    
    # 2. Optimize
    location_names = ["Start"] + store_names
    durations_matrix = [[0, 100, 200], [100, 0, 150], [200, 150, 0]]
    config.MAX_TIME_SECONDS = 3600
    
    optimal_route, item_cost, total_time, item_assignments = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    print(f"Optimal Route: {optimal_route}")
    print(f"Item Cost: {item_cost}")
    print(f"Assignments: {item_assignments}")
    
    # 3. Simulate Server formatted_shopping_list
    for store in optimal_route:
        if store == "Start": continue
        items = item_assignments.get(store, [])
        for item_data in items:
            item_name = item_data["name"]
            item_qty = item_data["qty"]
            lookup_key = item_name.lower().strip()
            unit_price = price_database.get(store, {}).get(lookup_key, 0.0)
            print(f"Store: {store}, Item: {item_name}, Lookup: {lookup_key}, Price: {unit_price}")

if __name__ == "__main__":
    test_repro()
