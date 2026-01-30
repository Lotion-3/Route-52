import os
import requests
from typing import List, Dict, Union, Tuple, Any, Set
import json
import time 
import random 
from itertools import combinations, permutations
from dotenv import load_dotenv
import csv  # Added for CSV handling

# Load environment variables from the config.env file
load_dotenv('config.env') 

# --- 1. API KEY SETUP AND CONFIGURATION ---
ORS_API_KEY = os.getenv("ORS_API_KEY")

# We no longer need RapidAPI keys for pricing
if not ORS_API_KEY:
    print("FATAL ERROR: ORS_API_KEY missing in 'config.env'.")
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

# --- PRICE VARIANCE RANGE ---
MIN_PRICE_FACTOR = 0.2
MAX_PRICE_FACTOR = 2.5
# ----------------------------

# --- 2. DYNAMIC SEARCH CONFIG & CONSTANTS ---
USER_START_LOCATION: Tuple[float, float] = (40.0033, -86.1366)  # Near Indianapolis

# User's Shopping List (L) - Now includes quantities (QTY)
# CHANGED: Only carrots and okra
SHOPPING_LIST: List[Dict[str, Union[str, int]]] = [
    {"name": "carrots", "qty": 2}, 
    {"name": "okra", "qty": 1},
    {"name": "beets", "qty": 4},
    {"name": "zucchini", "qty": 3}
]
TOTAL_LIST_SIZE = len(SHOPPING_LIST) 

# --- OPTIMIZATION CONFIGURATION (Time Cap & Estimates) ---
TIME_TARGET_HOURS = 3.0 
MAX_TIME_SECONDS = TIME_TARGET_HOURS * 3600 * 1.1 

# --- ACCURACY B: STORE-SPECIFIC TIME WEIGHTS (New) ---
STORE_TIME_MULTIPLIERS: Dict[str, float] = {
    "Aldi": 1,         
    "Trader Joe's": 1, 
    "Kroger": 1,       
    "Meijer": 1,       
    "Whole Foods": 1,  
    "Walmart": 1,      
    "Costco": 1         
}

# --- REVISED TIME MODEL CONSTANTS (in minutes, converted to seconds) ---
BASE_CHECKOUT_TIME_MINUTES = 7 
BASE_PARK_ENTRANCE_TIME_MINUTES = 5
TIME_PER_ITEM_MINUTES = 1

BASE_FIXOUT_OVERHEAD = (BASE_CHECKOUT_TIME_MINUTES + BASE_PARK_ENTRANCE_TIME_MINUTES) * 60 
TIME_PER_UNIT_SECONDS = TIME_PER_ITEM_MINUTES * 60 
# ------------------------------------------------------------------------

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

# --- CITY-TO-STATE MAPPING ---
# Mapping store names to cities for price lookup
STORE_CITY_MAPPING = {
    # Common store name patterns to cities
    "Kroger": "Indianapolis",
    "Walmart": "Indianapolis",
    "Meijer": "Indianapolis",
    "Target": "Indianapolis",
    "Aldi": "Indianapolis",
    "Whole Foods": "Indianapolis",
    "Trader Joe's": "Indianapolis",
    "Costco": "Indianapolis",
    "Safeway": "Indianapolis",
    "Publix": "Indianapolis",
    "Giant": "Indianapolis",
    "Food Lion": "Indianapolis",
    "Harris Teeter": "Indianapolis",
    "Hy-Vee": "Indianapolis",
    "H-E-B": "Indianapolis",
    "Wegmans": "Indianapolis",
    "Stop & Shop": "Indianapolis",
    "ShopRite": "Indianapolis"
}

def get_city_for_store(store_name: str) -> str:
    """Extract city from store name or use default mapping."""
    store_lower = store_name.lower()
    
    # Check if store name contains a city
    common_cities = [
        "new york", "los angeles", "chicago", "houston", "phoenix",
        "philadelphia", "san antonio", "san diego", "dallas", "san jose",
        "austin", "jacksonville", "fort worth", "columbus", "charlotte",
        "san francisco", "indianapolis", "seattle", "denver", "washington",
        "boston", "el paso", "nashville", "detroit", "oklahoma city",
        "portland", "las vegas", "memphis", "louisville", "baltimore",
        "milwaukee", "albuquerque", "tucson", "fresno", "sacramento",
        "mesa", "atlanta", "kansas city", "colorado springs", "raleigh",
        "omaha", "miami", "tampa", "cleveland", "new orleans", "minneapolis",
        "orlando", "honolulu", "spokane", "vancouver", "pittsburgh",
        "cincinnati", "st. louis", "salt lake city", "wichita", "madison",
        "richmond", "columbia", "boise", "des moines", "providence"
    ]
    
    for city in common_cities:
        if city in store_lower:
            return city.title()
    
    # Use mapping for chain stores
    for store_pattern, city in STORE_CITY_MAPPING.items():
        if store_pattern.lower() in store_lower:
            return city
    
    # Default to Indianapolis (since that's where USER_START_LOCATION is)
    return "Indianapolis"

# --- FUNCTIONS FOR PRICE DATABASE (P) - UPDATED FOR NEW CSV FORMAT ---
def load_city_prices_from_csv(csv_filename: str = "alanVeggies.csv") -> Dict[str, Dict[str, float]]:
    """
    Loads price data from the new CSV format.
    Expected CSV format: Vegetable,Form,RetailPrice,RetailPriceUnit,New York,Honolulu,San Francisco,...
    Returns: Dict[city][vegetable] = price
    """
    print(f"\n--- STEP 1: Loading Grocery Price Data from {csv_filename} ---")
    
    city_price_data: Dict[str, Dict[str, float]] = {}
    
    try:
        with open(csv_filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # The CSV has columns: Vegetable, Form, RetailPrice, RetailPriceUnit, then city columns
            required_columns = ['Vegetable', 'Form', 'RetailPrice', 'RetailPriceUnit']
            if not all(col in reader.fieldnames for col in required_columns):
                print(f"Error: CSV file must have columns: {required_columns}")
                print(f"Found columns: {reader.fieldnames}")
                return {}
            
            # Get all city columns (all columns except the first 4)
            city_columns = [col for col in reader.fieldnames if col not in required_columns]
            print(f"Found price data for {len(city_columns)} cities")
            
            for row in reader:
                vegetable = row['Vegetable'].strip().lower()
                form = row['Form'].strip()
                
                # Skip if not the standard form (assuming we want fresh produce)
                if form.lower() not in ['fresh', 'raw', '']:
                    continue
                
                for city in city_columns:
                    price_str = row[city].strip()
                    if price_str:  # Only process if there's a price
                        try:
                            price = float(price_str)
                            # Initialize city dict if needed
                            if city not in city_price_data:
                                city_price_data[city] = {}
                            city_price_data[city][vegetable] = price
                        except ValueError:
                            # Skip invalid prices
                            pass
        
        print(f"Successfully loaded price data for {len(city_price_data)} cities.")
        return city_price_data
        
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_filename}' not found.")
        return {}
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return {}


def fetch_grocery_prices(
    items: List[Dict[str, Union[str, int]]], 
    store_ids: List[str]
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    """
    Loads prices from CSV and generates store-specific prices with random variance.
    Returns: (price_database, removed_items_report, successful_shopping_list)
    """
    print("\n--- STEP 1: Fetching Grocery Price Data (P) from CSV ---")
    
    # Load all city price data from CSV
    city_price_data = load_city_prices_from_csv()
    
    if not city_price_data:
        print("Error: Could not load price data from CSV.")
        return {}, items, []
    
    price_database: Dict[str, Dict[str, float]] = {}
    removed_items_report: List[str] = []
    successful_shopping_list: List[Dict[str, Union[str, int]]] = []

    # First, check which items are available in any city
    available_vegetables = set()
    for city_data in city_price_data.values():
        available_vegetables.update(city_data.keys())
    
    for item_data in items:
        item_name = item_data["name"].lower()
        
        if item_name not in available_vegetables:
            removed_items_report.append(item_data["name"])
            print(f"  [REMOVED] Vegetable '{item_data['name']}' not found in CSV. **REMOVING from list.**")
            continue
        
        # Item found in CSV
        successful_shopping_list.append(item_data)
    
    # If no items are available, return early
    if not successful_shopping_list:
        return {}, removed_items_report, []
    
    # Now generate prices for each store and item
    for store_id in store_ids:
        # Determine which city's prices to use for this store
        store_city = get_city_for_store(store_id)
        
        # Try to find the city in our data
        city_found = store_city
        if store_city not in city_price_data:
            # Try to find a matching city (case-insensitive)
            city_lower = store_city.lower()
            for available_city in city_price_data.keys():
                if available_city.lower() == city_lower:
                    city_found = available_city
                    break
            else:
                # Use Indianapolis as default (since that's the start location)
                city_found = "Indianapolis"
                if city_found not in city_price_data:
                    # If Indianapolis not found, use first available city
                    city_found = list(city_price_data.keys())[0]
        
        print(f"  Using '{city_found}' prices for store: {store_id}")
        
        # Initialize store in price database
        if store_id not in price_database:
            price_database[store_id] = {}
        
        # Generate prices for each successful item
        for item_data in successful_shopping_list:
            item_name = item_data["name"].lower()
            
            # Get base price from city data
            base_price = city_price_data[city_found].get(item_name)
            
            if base_price is not None:
                # Generate a unique random seed for this store-item combination
                seed_str = f"{store_id}_{item_name}"
                random.seed(hash(seed_str))  # Use hash for consistent but unique seeding
                
                # Apply random variance between 0.6 and 1.4
                variance_factor = random.uniform(MIN_PRICE_FACTOR, MAX_PRICE_FACTOR)
                store_price = base_price * variance_factor
                
                price_database[store_id][item_name] = round(store_price, 2)
            else:
                # Item not available in this city
                price_database[store_id][item_name] = float('inf')

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
        item = item_data["name"].lower()
        quantity = item_data["qty"]
        
        min_item_cost = float('inf') 
        best_store = None
        
        # Find the cheapest price for this item among the selected stores
        for store_id in store_ids:
            unit_price = price_database.get(store_id, {}).get(item, float('inf'))
            if unit_price != float('inf'):
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
            item_name = item_data["name"].lower()
            
            winner_unit_price = price_database.get(k1_winner_store_id, {}).get(item_name, float('inf'))
            store_unit_price = price_database.get(store_id, {}).get(item_name, float('inf'))
            
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
        print(f"❌ ITEMS REMOVED: {len(removed_items)} Item(s) NOT FOUND/PRICED in the CSV.")
        print("These items were removed from the optimization list entirely:")
        for item in removed_items:
            print(f"- {item}")
        print("----------------------------------------------------")
    
    if total_successful > 0:
        print(f"✅ ITEMS PRICED: {total_successful} Item(s) are included in the final optimization.")
        print(f"({TOTAL_REQUESTED_SIZE - total_successful} item(s) were excluded as unpriced.)")
        
        # Show sample prices
        print("\nSample generated prices (first 3 stores):")
        sample_stores = list(price_database.keys())[:3]
        for store in sample_stores:
            print(f"  {store}:")
            for item_data in successful_shopping_list:
                item_name = item_data["name"].lower()
                price = price_database[store].get(item_name, "N/A")
                if price != float('inf'):
                    print(f"    - {item_name}: ${price:.2f}")
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
        
        # Show item assignments
        if optimal_route:
            print(f"\nItem assignments:")
            # Calculate final assignment to show where each item should be bought
            for item_data in successful_shopping_list:
                item_name = item_data["name"]
                quantity = item_data["qty"]
                min_price = float('inf')
                best_store = None
                
                for store in optimal_route:
                    price = price_database[store].get(item_name.lower(), float('inf'))
                    if price < min_price:
                        min_price = price
                        best_store = store
                
                if best_store:
                    print(f"  - {quantity} × {item_name}: ${min_price:.2f} each at {best_store}")
    else:
        print("❌ Optimization could not find a suitable store or route that meets the time constraint.")
    print("====================================================")