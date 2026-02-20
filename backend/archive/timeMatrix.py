import os
import requests
from typing import List, Dict, Union, Tuple, Any, Set
import json
import time 
import random 
from itertools import combinations, permutations
from dotenv import load_dotenv

# Load environment variables from the config.env file
load_dotenv('config.env') 

# --- 1. API KEY SETUP AND CONFIGURATION ---
ORS_API_KEY = os.getenv("ORS_API_KEY")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST")

if not ORS_API_KEY or not RAPID_API_KEY or not RAPID_API_HOST:
    print("FATAL ERROR: One or more API keys/hosts missing in 'config.env'.")
    exit(1)

# OpenRouteService Endpoints
ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
ORS_ISOCHRONE_URL = "https://api.openrouteservice.org/v2/isochrones/driving-car"

# Overpass API Endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter" 
# ------------------------------------

# --- NEW: API LIMIT CONSTANT ---
MAX_MATRIX_LOCATIONS = 50 
# -------------------------------

RAPID_API_PRICE_URL = f"https://{RAPID_API_HOST}/products/search" 

# --- PRICE MODEL CONSTANTS (Used for Missing/Fallback Data) ---
# NOTE: Fallback pricing has been removed. Items not priced by the API are now excluded.
MAX_PRICE_VARIANCE_FACTOR = 0.05 # +/- 5% variance per store
# -------------------------------------------------------------

# --- 2. DYNAMIC SEARCH CONFIG & CONSTANTS ---
USER_START_LOCATION: Tuple[float, float] = (40.0033, -86.1366) 

# User's Shopping List (L) - Now includes quantities (QTY)
SHOPPING_LIST: List[Dict[str, Union[str, int]]] = [
    {"name": "milk", "qty": 2}, 
    {"name": "eggs", "qty": 1}, 
    {"name": "bread", "qty": 3}, 
    {"name": "cheese", "qty": 1}, 
    {"name": "mangos", "qty": 2}, 
    {"name": "bananas", "qty": 1}, 
    {"name": "butter", "qty": 1}, 
    {"name": "apples", "qty": 4}, 
    {"name": "flour", "qty": 1}, 
    {"name": "tomatoes", "qty": 3}, 
    {"name": "oranges", "qty": 2}, 
    {"name": "coke", "qty": 1}, 
    {"name": "sprite", "qty": 1},  
    {"name": "garbage bags", "qty": 1}, 
    {"name": "garbanzo beans", "qty": 2}, 
    {"name": "organic salmon", "qty": 1}, 
    {"name": "lays chips magic masala", "qty": 1}, 
    {"name": "saffron", "qty": 1} 
]
TOTAL_LIST_SIZE = len(SHOPPING_LIST) 

# --- OPTIMIZATION CONFIGURATION (Time Cap & Estimates) ---
TIME_TARGET_HOURS = 2.0 
MAX_TIME_SECONDS = TIME_TARGET_HOURS * 3600 * 1.1 

# --- ACCURACY B: STORE-SPECIFIC TIME WEIGHTS (New) ---
STORE_TIME_MULTIPLIERS: Dict[str, float] = {
    "Aldi": 0.8,         
    "Trader Joe's": 0.9, 
    "Kroger": 1.0,       
    "Meijer": 1.1,       
    "Whole Foods": 1.2,  
    "Walmart": 1.2,      
    "Costco": 1.5         
}

# --- REVISED TIME MODEL CONSTANTS (in minutes, converted to seconds) ---
BASE_CHECKOUT_TIME_MINUTES = 7 
BASE_PARK_ENTRANCE_TIME_MINUTES = 5
TIME_PER_ITEM_MINUTES = 1

BASE_FIXOUT_OVERHEAD = (BASE_CHECKOUT_TIME_MINUTES + BASE_PARK_ENTRANCE_TIME_MINUTES) * 60 
TIME_PER_UNIT_SECONDS = TIME_PER_ITEM_MINUTES * 60 
# ------------------------------------------------------------------------

# --- REMOVED HELPER FUNCTION: Synthetic Price Generation (No more fallbacks) ---

# --- HELPER FUNCTION: Get the GeoJSON Bounding Box ---
def get_geojson_bounding_box(geometry: Dict) -> Tuple[float, float, float, float]:
    """
    Calculates the minimum and maximum coordinates (bounding box) from the Isochrone geometry.
    Returns: (min_lat, min_lon, max_lat, max_lon)
    """
    if geometry['type'] != 'Polygon':
        return (0, 0, 0, 0)
    
    # Coordinates are [Lon, Lat]
    all_coords = [coord for ring in geometry['coordinates'] for coord in ring]
    
    lons = [c[0] for c in all_coords]
    lats = [c[1] for c in all_coords]
    
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    # Overpass QL expects (south_lat, west_lon, north_lat, east_lon)
    return (min_lat, min_lon, max_lat, max_lon)


# --- FUNCTION 0a: Get the GeoJSON Isochrone ---
def get_travel_isochrone(start_location: Tuple[float, float], time_limit_seconds: int) -> Union[Dict, None]:
    """
    Calculates the maximum area reachable within the time_limit_seconds.
    Returns the GeoJSON geometry of the reachable area.
    """
    print(f"\n--- STEP 0a: Calculating Isochrone Area (Reachability) ---")
    print(f"One-way time budget for search: {int(time_limit_seconds / 60)} minutes.")

    # Isochrone requires center in [Lon, Lat] format
    lon, lat = start_location[1], start_location[0]

    headers = {
        'Accept': 'application/geo+json',
        'Authorization': ORS_API_KEY,
        'Content-Type': 'application/json'
    }

    payload = {
        "locations": [[lon, lat]],
        "range": [time_limit_seconds],
        "range_type": "time",
    }

    try:
        response = requests.post(ORS_ISOCHRONE_URL, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        isochrone_feature = data.get('features', [{}])[0]
        if isochrone_feature and isochrone_feature.get('geometry'):
            print("Success! Isochrone geometry calculated.")
            return isochrone_feature.get('geometry')
        
        print("Error: Isochrone API returned no valid geometry.")
        return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Isochrone data: {e}")
        return None


# --- FUNCTION 0b: POI SEARCH using Overpass API ---
def find_eligible_stores_overpass(bbox: Tuple[float, float, float, float]) -> Dict[str, Tuple[float, float]]:
    """
    Calls the Overpass API to find grocery stores within the bounding box.
    bbox: (min_lat, min_lon, max_lat, max_lon)
    """
    print(f"\n--- STEP 0b: Searching for Stores within Bounding Box (Overpass API) ---")
    
    min_lat, min_lon, max_lat, max_lon = bbox
    
    overpass_query = f"""
        [out:json][timeout:25];
        node["shop"~"supermarket|convenience|grocer|grocery"]({min_lat},{min_lon},{max_lat},{max_lon});
        out center;
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                OVERPASS_URL, 
                data={"data": overpass_query}, 
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            stores = {}
            elements = data.get('elements', [])
            
            if not elements:
                print("No grocery stores found in the bounding box via Overpass API.")
                return {}

            for element in elements:
                if element['type'] == 'node':
                    lat = element.get('lat')
                    lon = element.get('lon')
                    
                    name = element.get('tags', {}).get('name')
                    if not name:
                        shop_type = element.get('tags', {}).get('shop', 'Store')
                        name = f"{shop_type.capitalize()} ({int(lat * 1000)})"
                        
                    original_name = name
                    count = 1
                    while name in stores:
                        name = f"{original_name} {count}"
                        count += 1
                        
                    if lat and lon:
                        stores[name] = (lat, lon) # Store as (Lat, Lon)

            print(f"Successfully found {len(stores)} eligible store(s) within the area via Overpass API.")
            return stores

        except requests.exceptions.HTTPError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Overpass Error ({response.status_code}). Retrying POI search in {wait_time} seconds (Attempt {attempt + 1}/{max_retries}).")
                time.sleep(wait_time)
            else:
                print(f"Error fetching POI data from Overpass: {e} (Max retries failed).")
                return {}
                
        except requests.exceptions.RequestException as e:
            print(f"Network Error fetching POI data: {e}")
            return {}
            
    return {} 


# --- FUNCTIONS FOR TRAVEL TIME MATRIX (M) ---
def convert_locations_to_ors_format(locations: List[Tuple[float, float]]) -> List[List[float]]:
    """Converts (Lat, Lon) list to the ORS-required [Lon, Lat] format."""
    return [[loc[1], loc[0]] for loc in locations]

def get_distance_matrix(
    locations: List[Tuple[float, float]]
) -> Union[Dict[str, Any], None]:
    """Calls the OpenRouteService Distance Matrix API to get travel times with retries."""
    
    ors_locations = convert_locations_to_ors_format(locations)
    headers = {
        'Accept': 'application/json',
        'Authorization': ORS_API_KEY,
        'Content-Type': 'application/json'
    }
    payload = {"locations": ors_locations}
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(ORS_MATRIX_URL, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code >= 500 and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Server Error ({response.status_code}). Retrying Matrix calculation in {wait_time} seconds (Attempt {attempt + 1}/{max_retries}).")
                time.sleep(wait_time)
            elif response.status_code == 400:
                print(f"Client Error (400 Bad Request): Input data size or format invalid. Max retries reached or non-retryable error.")
                return None
            else:
                print(f"Error fetching distance matrix: {e}. Max retries reached or non-retryable error.")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Network Error fetching distance matrix: {e}. Max retries reached.")
            return None
    return None

def process_matrix_result(matrix_response: Dict) -> List[List[float]]:
    """Extracts and returns the raw duration matrix from the ORS response."""
    durations_matrix = matrix_response.get('durations')
    if not durations_matrix:
        print("Error: 'durations' array not found in ORS response.")
        return []
    return durations_matrix

# --- FUNCTIONS FOR PRICE DATABASE (P) ---
def fetch_grocery_prices(
    items: List[Dict[str, Union[str, int]]], 
    store_ids: List[str]
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    """
    Attempts to fetch a real base price for every item from the RapidAPI.
    If API fails, the item is removed from the list (no fallback price is used).
    Applies minor variance to the base price across stores to enable optimization.
    
    Returns: (price_database, removed_items_report, successful_shopping_list)
    """
    print("\n--- STEP 1: Fetching Grocery Price Data (P) from RapidAPI ---")
    
    price_database: Dict[str, Dict[str, float]] = {}
    removed_items_report: List[str] = []
    successful_shopping_list: List[Dict[str, Union[str, int]]] = []

    headers = {
        "X-RapidAPI-Key": RAPID_API_KEY,
        "X-RapidAPI-Host": RAPID_API_HOST
    }
    
    for item_data in items:
        item = item_data["name"]
        item_base_price = None
        
        # --- 1. ATTEMPT REAL API CALL FOR ITEM BASE PRICE ---
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # Use a specific query string for the search
                params = {"query": item, "limit": 1}
                response = requests.get(RAPID_API_PRICE_URL, headers=headers, params=params, timeout=5)
                
                # Check for non-200 status codes (like 403 Forbidden for bad key)
                if response.status_code != 200:
                    print(f"  [API ERROR] Status Code {response.status_code}. Likely bad API key/host. Response snippet: {response.text[:100].replace(response.reason, '')}...")
                    response.raise_for_status() 
                
                # Handle empty/non-JSON response
                if not response.text:
                    raise json.JSONDecodeError("Empty response body", response.text, 0)
                    
                data = response.json()
                
                first_result_price = data.get('products', [{}])[0].get('price')

                if first_result_price is not None:
                    try:
                        price_value = float(first_result_price)
                        item_base_price = price_value
                        print(f"  [API SUCCESS] Item '{item}': Base price found: ${item_base_price:.2f}")
                        break # Exit retry loop on successful price extraction
                    except ValueError:
                        print(f"  [API WARNING] Price for '{item}' was found but not a valid number. Retrying...")
                        
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                # This catches both network errors, 4xx/5xx errors (via raise_for_status), and JSON parsing failure
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    if isinstance(e, json.JSONDecodeError):
                        print(f"  [API ERROR] **JSONDecodeError**. Check API key/host in config.env. Retrying in {wait_time}s (Attempt {attempt + 1}/{max_retries}).")
                    else:
                        print(f"  [API ERROR] Network/HTTP Error ({e.__class__.__name__}). Retrying in {wait_time}s (Attempt {attempt + 1}/{max_retries}).")
                    time.sleep(wait_time)
                else:
                    print(f"  [API FAILURE] Max retries failed for '{item}'. Final Error: {e.__class__.__name__}")
                    break # Break and fall through to strict removal logic
        
        # --- 2. CHECK FOR FAILURE AND REMOVE IF NO PRICE FOUND (STRICT MODE) ---
        if item_base_price is None:
            removed_items_report.append(item)
            print(f"  [REMOVED] Item '{item}' not found/priced by API. **REMOVING from list.**")
            continue # Skip to the next item
        
        # Item successfully priced by the API
        successful_shopping_list.append(item_data)

        # Apply minor store-specific variance to the base price
        item_prices: Dict[str, float] = {}
        for store_id in store_ids:
            # Generate a consistent, minor variance based on store name hash
            store_seed = sum(ord(c) for c in store_id)
            random.seed(store_seed)
            variance = random.uniform(1.0 - MAX_PRICE_VARIANCE_FACTOR, 1.0 + MAX_PRICE_VARIANCE_FACTOR)
            
            store_price = item_base_price * variance
            item_prices[store_id] = round(store_price, 2)
            
        price_database[item] = item_prices

    return price_database, removed_items_report, successful_shopping_list

# --- CORE OPTIMIZATION LOGIC ---

def calculate_split_shopping_price(
    shopping_list_to_use: List[Dict[str, Union[str, int]]],
    store_ids: List[str], 
    price_database: Dict[str, Dict[str, float]]
) -> Tuple[float, Dict[str, int]]:
    """
    Calculates the minimum total cost, considering item quantities, and returns 
    the total quantity of units assigned to each store.
    
    Uses the filtered list (shopping_list_to_use) passed from the main logic.
    Returns: (total_price, {store_id: total_unit_count})
    """
    total_price = 0.0
    item_assignment_counts: Dict[str, int] = {s: 0 for s in store_ids} 
    
    for item_data in shopping_list_to_use: 
        item = item_data["name"]
        quantity = item_data["qty"]
        
        min_item_cost = float('inf') 
        best_store = None
        
        # Find the cheapest price for this item among the selected stores
        for store_id in store_ids:
            unit_price = price_database.get(item, {}).get(store_id)
            if unit_price is not None:
                cost = unit_price * quantity
                if cost < min_item_cost:
                    min_item_cost = cost
                    best_store = store_id 
        
        if min_item_cost == float('inf'):
            # This should not happen if price_database only contains items in the successful list
            return float('inf'), item_assignment_counts 
            
        total_price += min_item_cost
        
        if best_store:
            item_assignment_counts[best_store] += int(quantity)
            
    return total_price, item_assignment_counts


def find_fastest_travel_permutation(
    store_indices_subset: Tuple[int, ...], 
    durations_matrix: List[List[float]], 
    start_index: int
) -> Tuple[Tuple[int, ...], float]:
    """
    For a given set of stores (subset), find the fastest order (permutation) to visit them.
    Returns: (best_route_indices, min_travel_time)
    """
    min_travel_time = float('inf')
    best_route_indices = store_indices_subset
    
    for route_indices in permutations(store_indices_subset):
        travel_time = 0.0
        current_index = start_index
        
        # Sum travel time: Start -> S1 -> S2 -> ...
        for next_index in route_indices:
            travel_time += durations_matrix[current_index][next_index]
            current_index = next_index
            
        # Add return trip: ... -> Sk -> Start
        travel_time += durations_matrix[current_index][start_index]
        
        if travel_time < min_travel_time:
            min_travel_time = travel_time
            best_route_indices = route_indices
            
    return best_route_indices, min_travel_time


def find_optimal_store(
    durations_matrix: List[List[float]],
    price_database: Dict[str, Dict[str, float]],
    location_names: List[str],
    successful_shopping_list: List[Dict[str, Union[str, int]]]
) -> Tuple[List[str], float, float]:
    """
    Finds the route (1 to N stores) with the lowest combined shopping price 
    that meets the total time constraint. Implements the new item-based filtering.
    """
    start_index = location_names.index("Start")
    optimal_route: List[str] = []
    min_cost = float('inf')
    best_total_time = 0.0
    
    # Check if there are any items to shop for
    if not successful_shopping_list:
        print("No items were successfully priced. Cannot run optimization.")
        return [], 0.0, 0.0
    
    max_time_minutes = MAX_TIME_SECONDS / 60
    print(f"CONSTRAINT: Route must be <= {max_time_minutes:.0f} minutes (2 hours + 10%)")
    
    store_indices = list(range(1, len(location_names)))
    
    # Set to store subsets (as frozensets of indices) that failed the time constraint 
    failed_time_subsets: Set[frozenset[int]] = set()
    
    k1_winner_store_id: Union[str, None] = None

    # --- Phase 1: Calculate Baseline (k=1) Costs and Find Best Single Stop ---
    print("\n--- Phase 1: Calculating Baseline (k=1) Costs ---")
    k = 1 
    
    for store_indices_subset in combinations(store_indices, k):
        current_store_index = store_indices_subset[0]
        route_store_ids = [location_names[current_store_index]]
        route_str = route_store_ids[0]

        # 1. Calculate Optimal Item Assignment and Cost
        item_cost, item_quantity_counts = calculate_split_shopping_price(
            successful_shopping_list, # Use filtered list
            route_store_ids, 
            price_database
        )
        
        if item_cost == float('inf'):
            continue
            
        # --- CALCULATE SHOPPING TIME (Accuracy B: Store-Specific Times) ---
        store_id = route_store_ids[0]
        store_type = store_id.split(' ')[0] 
        multiplier = STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
        quantity_s = item_quantity_counts.get(store_id, 0)
        total_shopping_time_seconds = (BASE_FIXOUT_OVERHEAD * multiplier) + (quantity_s * TIME_PER_UNIT_SECONDS)

        # 2. Find Fastest Travel Permutation 
        store_index = location_names.index(store_id)
        min_travel_time = durations_matrix[start_index][store_index] + durations_matrix[store_index][start_index]
        
        # 3. Calculate Full Time 
        total_time_seconds = min_travel_time + total_shopping_time_seconds

        # 4. Update Optimal
        if total_time_seconds <= MAX_TIME_SECONDS:
            if item_cost < min_cost:
                min_cost = item_cost 
                optimal_route = route_store_ids
                best_total_time = total_time_seconds
                k1_winner_store_id = store_id
                
                print(f"Route [1 Stop: {route_str}]: ✅ NEW BEST! Cost: ${item_cost:.2f} | Time: {int(total_time_seconds/60)}m")
        else:
            print(f"Route [1 Stop: {route_str}]: ❌ Time Exceeded ({int(total_time_seconds/60)}m)")

    # --- Phase 2: Store Filtering (Item-Based Pruning) ---

    if min_cost == float('inf') or k1_winner_store_id is None:
        print("\n--- Global Pruning: No single-stop route was time-feasible. Stopping search. ---")
        return optimal_route, min_cost, best_total_time
    
    
    winner_prices: Dict[str, float] = price_database.get(k1_winner_store_id, {})
    
    eligible_multistop_indices: List[int] = []

    print(f"\n--- Store Pruning (Based on Item Price vs. Winner: {k1_winner_store_id} @ ${min_cost:.2f}) ---")
    
    for index in store_indices:
        store_id = location_names[index]
        
        if store_id == k1_winner_store_id:
            eligible_multistop_indices.append(index)
            continue
            
        is_store_useful = False
        
        # Iterate over the successful list only
        for item_data in successful_shopping_list:
            item_name = item_data["name"]
            
            winner_unit_price = price_database.get(item_name, {}).get(k1_winner_store_id, float('inf'))
            store_unit_price = price_database.get(item_name, {}).get(store_id, float('inf'))
            
            if store_unit_price < winner_unit_price:
                is_store_useful = True
                break
        
        if is_store_useful:
            eligible_multistop_indices.append(index)
            # print(f"Store {store_id}: ✅ Kept (Found at least one cheaper item).")
        # else:
            # print(f"Store {store_id}: 🛑 Pruned (No item is strictly cheaper than the winner's price).")


    # --- Phase 3: Run k=2 to max_k using only eligible_multistop_indices ---
    print(f"\n--- Running k>1 Optimization on {len(eligible_multistop_indices)} Eligible Stores ---")
    
    max_k_eligible = len(eligible_multistop_indices)
    
    for k in range(2, max_k_eligible + 1):
        
        found_any_time_feasible_subset_at_k = False 
        
        for store_indices_subset in combinations(eligible_multistop_indices, k):
            
            # --- SUBSET PRUNING CHECK (Time Pruning) ---
            is_superset_of_failed = False
            current_set = frozenset(store_indices_subset)
            for failed_set in failed_time_subsets:
                if failed_set.issubset(current_set):
                    is_superset_of_failed = True
                    break
            
            route_store_ids = [location_names[i] for i in store_indices_subset]
            route_str = " -> ".join(route_store_ids)
            
            if is_superset_of_failed:
                continue

            # --- 1. Calculate Optimal Item Assignment and Cost (Once per SET) ---
            item_cost, item_quantity_counts = calculate_split_shopping_price(
                successful_shopping_list, # Use filtered list
                route_store_ids, 
                price_database
            )
            
            if item_cost == float('inf'):
                continue
            
            # --- CALCULATE SHOPPING TIME (Accuracy B: Store-Specific Times) ---
            total_shopping_time_seconds = 0.0
            min_one_way_travel = float('inf')

            for store_id in route_store_ids:
                store_type = store_id.split(' ')[0] 
                multiplier = STORE_TIME_MULTIPLIERS.get(store_type, 1.0)
                quantity_s = item_quantity_counts.get(store_id, 0)
                store_time = (BASE_FIXOUT_OVERHEAD * multiplier) + (quantity_s * TIME_PER_UNIT_SECONDS)
                total_shopping_time_seconds += store_time
                
                store_index = location_names.index(store_id)
                travel_to_store = durations_matrix[start_index][store_index]
                if travel_to_store < min_one_way_travel:
                    min_one_way_travel = travel_to_store

            # --- EFFICIENCY B: AGGRESSIVE TIME PRUNING (Lower Bound Check) ---
            lower_bound_travel_time = 2 * min_one_way_travel 
            lower_bound_total_time = lower_bound_travel_time + total_shopping_time_seconds
            
            if lower_bound_total_time > MAX_TIME_SECONDS:
                 continue
            
            found_any_time_feasible_subset_at_k = True 

            # **EARLY COST EXIT**: Prune if too expensive 
            if item_cost >= min_cost:
                continue 
            
            # --- 2. Find Fastest Travel Permutation (Travel Time Optimization) ---
            best_route_indices, min_travel_time = find_fastest_travel_permutation(
                store_indices_subset, durations_matrix, start_index
            )
            
            # --- 3. Calculate Full Time for this Fastest Route ---
            total_time_seconds = min_travel_time + total_shopping_time_seconds
            
            # --- 4. Check Constraint and Update Optimal ---
            if total_time_seconds > MAX_TIME_SECONDS:
                failed_time_subsets.add(current_set) 
                continue 
            
            # New best route found.
            min_cost = item_cost
            optimal_route = [location_names[i] for i in best_route_indices]
            best_total_time = total_time_seconds
            
            print(f"Route [{k} Stops: {route_str}]: ✅ NEW BEST! Cost: ${item_cost:.2f} | Time: {int(total_time_seconds/60)}m")
            
        # --- GLOBAL MAX K PRUNING (Purely time-based) ---
        if not found_any_time_feasible_subset_at_k and optimal_route:
            break
            
    return optimal_route, min_cost, best_total_time


# --- 3. MAIN EXECUTION ---
if __name__ == "__main__":
    
    # --- DYNAMIC SEARCH CALCULATION (Using Isochrone) ---
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECONDS / 4)
    
    # STEP 0a: Get the Isochrone (The reachable area)
    isochrone_geometry = get_travel_isochrone(USER_START_LOCATION, ONE_WAY_TIME_SECONDS)
    
    if not isochrone_geometry:
        print("FATAL ERROR: Could not determine the reachable area for the search.")
        exit(1)

    # Calculate bounding box for Overpass API
    bbox = get_geojson_bounding_box(isochrone_geometry)
        
    # --- STEP 0b: Find Stores within the Bounding Box (NO FALLBACK) ---
    STORE_LOCATIONS = find_eligible_stores_overpass(bbox)
    
    if not STORE_LOCATIONS:
        print("\nFATAL ERROR: POI search failed. No stores were found in the reachable area via the Overpass API.")
        print("Optimization cannot proceed without stores.")
        exit(1)
             
    
    # --- NEW: FILTERING LOGIC DUE TO MATRIX API SIZE LIMITS ---
    MAX_STORES_TO_USE = MAX_MATRIX_LOCATIONS - 1 
    
    if len(STORE_LOCATIONS) > MAX_STORES_TO_USE:
        print(f"\n--- STEP 0c: Filtering Stores (Limit: {MAX_STORES_TO_USE}) ---")
        print(f"Limiting {len(STORE_LOCATIONS)} stores to the {MAX_STORES_TO_USE} closest to the start location due to API limits...")
        
        distances = []
        start_lat, start_lon = USER_START_LOCATION
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - start_lat)**2 + (lon - start_lon)**2
            distances.append((dist_sq, name, (lat, lon)))
            
        distances.sort(key=lambda x: x[0])
        
        FILTERED_STORE_LOCATIONS = {name: loc for _, name, loc in distances[:MAX_STORES_TO_USE]}
        STORE_LOCATIONS = FILTERED_STORE_LOCATIONS
        
        print(f"Successfully reduced store count to {len(STORE_LOCATIONS)}.")
    # -----------------------------------------------------------

    # --- FINAL STORES LIST ---
    print("\n--- FINAL STORES SELECTED FOR OPTIMIZATION ---")
    print(f"Total Stores Selected: {len(STORE_LOCATIONS)}")
    # ---------------------------------------------
        
    all_coords = [USER_START_LOCATION] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())

    # 3a. Generate Travel Time Matrix (M) 
    print("\n--- STEP 1: Fetching Travel Time Matrix (M) ---")
    matrix_response = get_distance_matrix(all_coords) 
    
    if not matrix_response:
        print("Optimization failed: Could not generate Travel Time Matrix (M).")
        exit(1)
        
    durations_matrix = process_matrix_result(matrix_response)
    if not durations_matrix:
        print("Optimization failed: Matrix data is empty.")
        exit(1)
        
    # 3b. Fetch Price Database (P) - The function now returns a list of removed items 
    # and the list of items that were successfully priced.
    price_database, removed_items, successful_shopping_list = fetch_grocery_prices(SHOPPING_LIST, list(STORE_LOCATIONS.keys()))

    if not price_database:
        print("Optimization failed: Could not populate Price Database (P).")
        exit(1)
        
    # --- MISSING DATA REPORT ---
    print("\n====================================================")
    print("      DATA SOURCE REPORT (Price Database)")
    print("====================================================")
    
    TOTAL_REQUESTED_SIZE = len(SHOPPING_LIST)
    total_successful = len(successful_shopping_list)
    
    if removed_items:
        print(f"❌ ITEMS REMOVED: {len(removed_items)} Item(s) NOT FOUND/PRICED by the API.")
        print("These items were removed from the optimization list entirely:")
        for item in removed_items:
            print(f"- {item}")
        print("----------------------------------------------------")
    
    if total_successful > 0:
        print(f"✅ ITEMS PRICED: {total_successful} Item(s) are included in the final optimization.")
        print(f"({TOTAL_REQUESTED_SIZE - total_successful} item(s) were excluded as unpriced.)")
    else:
        print("FATAL: No items were successfully priced. Optimization halted.")
        exit(1)
    
    print("====================================================")

    # 3c. Perform Optimization (Step 2)
    print("\n--- STEP 2: Performing Optimization ---")
    
    # Pass the filtered list of successful items to the optimizer
    optimal_route, item_cost, total_time_seconds = find_optimal_store(
        durations_matrix,
        price_database,
        location_names,
        successful_shopping_list,
    )
    
    # 3d. Print Final Result
    print("\n====================================================")
    if optimal_route:
        route_display = " -> ".join(optimal_route)
        is_split = f" (Optimal Split - {len(optimal_route)} Stops)" if len(optimal_route) > 1 else ""
        
        print(f"✅ OPTIMAL SHOPPING RECOMMENDATION{is_split} (Cheapest within 132 Minute Cap)")
        print(f"Route: Start -> {route_display} -> End")
        print(f"Lowest Combined Shopping Price: ${item_cost:.2f}")
        print(f"Total Time (Travel + Shopping): {int(total_time_seconds / 60)}m {int(total_time_seconds % 60)}s")
    else:
        print("❌ Optimization could not find a suitable store or route that meets the time constraint.")
    print("====================================================")
