import os
import requests
from typing import List, Dict, Union, Tuple, Any, Set
import json
import time 
import sys
from dotenv import load_dotenv

# Import project modules
import config
import geo_utils
import data_loader
import price_managerOG as price_manager
import optimizer

# --- 1. LOCAL CONFIGURATION (Overrides or specific to Alan) ---
# Load environment variables (though config.py also does this)
load_dotenv('config.env') 

# Alan's Shopping List (L)
SHOPPING_LIST_RAW: List[Dict[str, Union[str, int]]] = [
    {"name": "carrots", "qty": 2}, 
    {"name": "okra", "qty": 1},
    {"name": "beets", "qty": 4},
    {"name": "zucchini", "qty": 3}
]

# Convert SHOPPING_LIST_RAW to the format expected by price_manager
# Format: {name: {"qty": quantity}}
SHOPPING_LIST_DATA = {item["name"]: {"qty": item["qty"]} for item in SHOPPING_LIST_RAW}

# --- 2. MAIN EXECUTION ---
if __name__ == "__main__":
    print("=" * 60)
    print("ALAN'S VEGGIES BUDDY - OPTIMIZED")
    print("=" * 60)
    
    # Use config values but allow local overrides if needed
    USER_LOC = config.USER_START_LOCATION
    MAX_TIME_SECS = config.MAX_TIME_SECONDS
    
    # STEP 0a: Get the Isochrone (The reachable area)
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(USER_LOC, ONE_WAY_TIME_SECONDS)
    
    if not isochrone_geometry:
        print("FATAL ERROR: Could not determine the reachable area for the search.")
        sys.exit(1)

    # Calculate bounding box for Overpass API
    bbox = geo_utils.get_geojson_bounding_box(isochrone_geometry)
        
    # STEP 0b: Find Stores within the Bounding Box
    STORE_LOCATIONS = geo_utils.find_eligible_stores_overpass(bbox)
    
    if not STORE_LOCATIONS:
        print("\nFATAL ERROR: No stores were found in the reachable area.")
        sys.exit(1)
             
    # STEP 0c: Filter Stores using Gemini (AI Filtering) via geo_utils
    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        print(f"\n--- STEP 0c: AI Store Filtering (Gemini) ---")
        STORE_LOCATIONS = geo_utils.filter_stores_with_gemini(
            STORE_LOCATIONS, 
            list(SHOPPING_LIST_DATA.keys()), 
            config.MAX_STORES_TO_USE,
            USER_LOC
        )

    # STEP 1: Get Prices
    print("\n--- Fetching Grocery Prices ---")
    # price_managerOG expects a list of store_ids
    store_ids = list(STORE_LOCATIONS.keys())
    
    # We don't have addresses from Overpass in the same format as Google, so we pass None
    price_database, removed_items, successful_shopping_list = price_manager.fetch_grocery_prices(
        SHOPPING_LIST_DATA, store_ids
    )
    
    if not successful_shopping_list:
        print("ERROR: No items could be priced. Exiting.")
        sys.exit(1)

    # STEP 2: Get Travel Matrix
    print("\n--- Calculating Travel Matrix ---")
    all_coords = [USER_LOC] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    
    if not durations_matrix:
        print("ERROR: Could not get distance matrix. Exiting.")
        sys.exit(1)

    # STEP 3: Run Optimization
    print("\n--- Running Optimization ---")
    optimal_route, min_cost, total_time_seconds, item_assignments = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, successful_shopping_list
    )
    
    # STEP 4: Display Results
    print("\n" + "=" * 60)
    print("FINAL OPTIMIZED PLAN")
    print("=" * 60)
    
    if optimal_route:
        print(f"✅ Route: Start -> {' -> '.join(optimal_route)} -> Start")
        print(f"💰 Total Cost: ${min_cost:.2f}")
        print(f"⏱️  Total Time: {int(total_time_seconds / 60)} minutes")
        
        print("\n🛒 SHOPPING BREAKDOWN:")
        for store in optimal_route:
            items = item_assignments.get(store, [])
            print(f"📍 {store}:")
            for item in items:
                print(f"   - {item}")
    else:
        print("❌ No feasible route found within the time limit.")
    print("=" * 60)