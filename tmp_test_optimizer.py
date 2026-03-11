import sys
import os

# Append both root and backend to sys.path to handle config import
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from backend import optimizer
import config

def test_optimizer():
    # Mock data
    durations_matrix = [
        [0, 10, 20],   # Start -> Store1, Store2
        [10, 0, 15],   # Store1 -> Start, Store2
        [20, 15, 0]    # Store2 -> Start, Store1
    ]
    
    # Optimizer now looks for lowercase keys in price_database
    price_database = {
        "Store 1": {"milk": 3.0, "bread": 2.0},
        "Store 2": {"milk": 2.5, "bread": 2.5}
    }
    
    location_names = ["Start", "Store 1", "Store 2"]
    
    shopping_list = [
        {"name": "milk", "qty": 1},
        {"name": "bread", "qty": 1}
    ]
    
    config.MAX_TIME_SECONDS = 3600
    config.BASE_FIXOUT_OVERHEAD = 300
    config.TIME_PER_UNIT_SECONDS = 30
    
    print("Running find_optimal_store...")
    res = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    print(f"Result length: {len(res)}")
    print(f"Optimal Route: {res[0]}")
    print(f"Total Cost: {res[1]}")
    print(f"Total Time: {res[2]}")
    print(f"Assignments: {res[3]}")
    print(f"Cheapest Single Store Cost: {res[4]}")
    print(f"Cheapest Single Store Name: {res[5]}")
    
    if res[5] == "Store 1" or res[5] == "Store 2":
        print("✅ SUCCESS: Benchmark found!")
    else:
        print("❌ FAILURE: Benchmark missing!")

if __name__ == "__main__":
    test_optimizer()
