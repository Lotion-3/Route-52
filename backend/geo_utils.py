
import requests
import time
import math
import os
from typing import Dict, List, Tuple, Union, Any, Optional
import config
from cache_manager import cache

import googlemaps
from shapely.geometry import shape, Point

from pydantic import BaseModel

# --- HELPER FUNCTION: Get the GeoJSON Bounding Box ---
def get_geojson_bounding_box(geometry: Dict) -> Tuple[float, float, float, float]:
    """Calculates the bounding box from Isochrone geometry."""
    if geometry['type'] != 'Polygon':
        return (0, 0, 0, 0)
    
    all_coords = [coord for ring in geometry['coordinates'] for coord in ring]
    lons = [c[0] for c in all_coords]
    lats = [c[1] for c in all_coords]
    
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    return (min_lat, min_lon, max_lat, max_lon)

# --- FUNCTION: Get Travel Isochrone ---
def get_travel_isochrone(start_location: Tuple[float, float], time_limit_seconds: int) -> Union[Dict, None]:
    """
    Calculates the maximum area reachable within the time_limit_seconds.
    Returns the GeoJSON geometry of the reachable area.
    """
    print(f"\nCalculating reachable area ({int(time_limit_seconds / 60)} minutes)...")
    
    # Isochrone requires [Lon, Lat] format
    lon, lat = start_location[1], start_location[0]
    
    headers = {
        'Accept': 'application/geo+json',
        'Authorization': f'Bearer {config.ORS_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Updated payload format - OpenRouteService v2 requires different structure
    payload = {
        "locations": [[lon, lat]],
        "range": [time_limit_seconds],
        "range_type": "time",
        "units": "m"  # meters (default) or "km"
    }
    
    cache_key = {"func": "get_travel_isochrone", "start": start_location, "limit": time_limit_seconds}
    cached_result = cache.get(cache_key, max_age_seconds=86400 * 7) # 1 week cache
    if cached_result:
        print("Using cached isochrone.")
        return cached_result

    try:
        response = requests.post(config.ORS_ISOCHRONE_URL, headers=headers, json=payload, timeout=15)
        
        if response.status_code != 200:
            print(f"Response Text: {response.text[:200]}")
        
        response.raise_for_status()
        data = response.json()
        
        isochrone_feature = data.get('features', [{}])[0]
        if isochrone_feature and isochrone_feature.get('geometry'):
            print("Success! Reachable area calculated.")
            geom = isochrone_feature.get('geometry')
            cache.set(cache_key, geom)
            return geom
        
        print("Error: Isochrone API returned no valid geometry.")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Isochrone data: {e}")
        return None

# --- FUNCTION: Find Eligible Stores (Google Places) ---
def find_eligible_stores_google(isochrone_geometry: Dict, center_point: Tuple[float, float]) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, str]]:
    """Find grocery stores within isochrone using Google Places API."""
    print(f"\nSearching for stores via Google Places...")
    
    cache_key = {"func": "find_eligible_stores_google", "center": center_point, "keywords": config.STORE_KEYWORDS}
    cached_result = cache.get(cache_key, max_age_seconds=86400 * 7) # 1 week cache
    if cached_result:
        print("Using cached store search results.")
        return cached_result[0], cached_result[1]

    gmaps = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)
    iso_polygon = shape(isochrone_geometry)
    
    stores = {}
    store_addresses = {}
    
    # We search using a large radius to cover the isochrone
    # Google Places Max Radius is 50000 meters
    radius = 50000  
    
    print(f"Searching for: {', '.join(config.STORE_KEYWORDS)}...")
    
    for keyword in config.STORE_KEYWORDS:
        try:
            results = gmaps.places_nearby(
                location=center_point,
                radius=radius,
                keyword=keyword
            )
            
            # Filter results by isochrone shape
            count_for_keyword = 0
            for place in results.get('results', []):
                lat = place['geometry']['location']['lat']
                lng = place['geometry']['location']['lng']
                point = Point(lng, lat)
                
                # Check if inside isochrone
                if iso_polygon.contains(point):
                    name = place['name']
                    
                    # --- FILTER: Exclude unwanted store sub-types ---
                    # Check 1: Exclude if name contains specific banned terms
                    if any(term in name.lower() for term in config.EXCLUDED_STORE_TERMS):
                        # print(f"Skipping {name} (Excluded term)")
                        continue

                    # Check 2: Must be a retail/grocery type — filters attorneys, doctors, clinics, etc.
                    place_types = place.get('types', [])
                    GROCERY_TYPES = {'grocery_or_supermarket', 'supermarket', 'store', 'department_store', 'shopping_mall', 'food'}
                    if not any(t in place_types for t in GROCERY_TYPES):
                        continue

                    if 'gas_station' in place_types or 'car_repair' in place_types:
                        if not any(t in place_types for t in ['supermarket', 'grocery_or_supermarket', 'department_store', 'shopping_mall']):
                            continue

                    # Ensure name uniqueness
                    original_name = name
                    count = 1
                    while name in stores:
                        name = f"{original_name} {count}"
                        count += 1
                        
                    stores[name] = (lat, lng)
                    store_addresses[name] = place.get('vicinity', 'Unknown Address')
                    count_for_keyword += 1
                    
            # print(f"  Found {count_for_keyword} {keyword}s in range.")
            
        except Exception as e:
            print(f"Error searching for {keyword}: {e}")

    print(f"Found {len(stores)} eligible store(s).")
    cache.set(cache_key, (stores, store_addresses))
    return stores, store_addresses

# --- FUNCTION: Find Eligible Stores (Legacy Overpass) ---
def find_eligible_stores_overpass(bbox: Tuple[float, float, float, float]) -> Dict[str, Tuple[float, float]]:
    """Find grocery stores within bounding box using Overpass API."""
    # ... (Kept for reference or fallback if needed)
    print(f"\nSearching for stores within area...")
    
    min_lat, min_lon, max_lat, max_lon = bbox
    overpass_query = f"""
        [out:json][timeout:25];
        node["shop"~"supermarket|convenience|grocer|grocery"]({min_lat},{min_lon},{max_lat},{max_lon});
        out center;
    """
    
    for attempt in range(3):
        try:
            response = requests.post(config.OVERPASS_URL, data={"data": overpass_query}, timeout=30)
            response.raise_for_status()
            data = response.json()
            stores = {}
            
            for element in data.get('elements', []):
                if element['type'] == 'node':
                    lat = element.get('lat')
                    lon = element.get('lon')
                    name = element.get('tags', {}).get('name')
                    
                    if not name:
                        shop_type = element.get('tags', {}).get('shop', 'Store')
                        name = f"{shop_type.capitalize()} ({int(lat * 1000)})"
                    
                    if lat and lon:
                        # Ensure unique names
                        original_name = name
                        count = 1
                        while name in stores:
                            name = f"{original_name} {count}"
                            count += 1
                        
                        stores[name] = (lat, lon)
            
            print(f"Found {len(stores)} eligible store(s).")
            return stores
            
        except requests.exceptions.RequestException:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return {}
    
    return {}

# --- TRAVEL TIME MATRIX FUNCTIONS ---
def convert_locations_to_ors_format(locations: List[Tuple[float, float]]) -> List[List[float]]:
    return [[loc[1], loc[0]] for loc in locations]

def _haversine_km(loc1: Tuple[float, float], loc2: Tuple[float, float]) -> float:
    lat1, lon1 = loc1
    lat2, lon2 = loc2
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))

def build_fallback_duration_matrix(locations: List[Tuple[float, float]]) -> List[List[float]]:
    """Estimate driving durations (seconds) from straight-line distances.

    Straight-line km × 1.3 road-winding factor at a 40 km/h average city
    driving speed — rough, but enough for the optimizer to rank routes.
    """
    ROAD_FACTOR = 1.3
    AVG_SPEED_KMH = 40.0
    n = len(locations)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            secs = _haversine_km(locations[i], locations[j]) * ROAD_FACTOR / AVG_SPEED_KMH * 3600.0
            matrix[i][j] = matrix[j][i] = secs
    return matrix

def get_distance_matrix(locations: List[Tuple[float, float]]) -> Dict[str, Any]:
    ors_locations = convert_locations_to_ors_format(locations)

    cache_key = {"func": "get_distance_matrix", "locations": ors_locations}
    cached_result = cache.get(cache_key, max_age_seconds=86400 * 7) # 1 week cache
    if cached_result:
        print("Using cached distance matrix.")
        return cached_result

    headers = {
        'Accept': 'application/json',
        'Authorization': config.ORS_API_KEY,
        'Content-Type': 'application/json'
    }
    payload = {"locations": ors_locations}

    for attempt in range(3):
        try:
            response = requests.post(config.ORS_MATRIX_URL, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('durations'):
                cache.set(cache_key, data)
            return data
        except requests.exceptions.HTTPError as e:
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
        except requests.exceptions.RequestException as e:
            print(f"Error fetching ORS matrix: {e}")
            break

    # Fallback: estimate durations from straight-line distances (not cached —
    # a later request should retry ORS for real road times).
    print("[Server] ORS matrix failed — using haversine duration estimates.", flush=True)
    return {"durations": build_fallback_duration_matrix(locations), "fallback": True}

def process_matrix_result(matrix_response: Optional[Dict]) -> List[List[float]]:
    if not matrix_response:
        return []
    durations_matrix = matrix_response.get('durations')
    return durations_matrix if durations_matrix else []

# --- CITY-TO-STATE MAPPING ---
def get_city_for_store(store_name: str) -> str:
    store_lower = store_name.lower()
    common_cities = ["indianapolis", "chicago", "new york", "los angeles", "houston"]
    
    for city in common_cities:
        if city in store_lower:
            return city.title()
    
    for store_pattern, city in config.STORE_CITY_MAPPING.items():
        if store_pattern.lower() in store_lower:
            return city
    
    return "Indianapolis"

# --- FUNCTION: Filter to Unique Chains ---
def filter_unique_closest_chains(
    stores: Dict[str, Tuple[float, float]], 
    addresses: Dict[str, str], 
    user_loc: Tuple[float, float]
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, str]]:
    """
    Filters the list of stores to keep only the closest single location for each chain.
    """
    print(f"\nFiltering for unique closest chains...")
    
    unique_stores = {}
    unique_addresses = {}
    
    # Pre-calculate distances for all stores
    store_distances = []
    for name, loc in stores.items():
        dist_sq = (loc[0] - user_loc[0])**2 + (loc[1] - user_loc[1])**2
        store_distances.append({
            "name": name,
            "loc": loc,
            "address": addresses.get(name, "Unknown"),
            "dist": dist_sq
        })
    
    # Sort ALL stores by distance first
    store_distances.sort(key=lambda x: x["dist"])
    
    # Track which chains we have already found a "winner" for
    found_chains = set()
    
    for entry in store_distances:
        # Check which chain this store belongs to
        original_name = entry["name"]
        
        # We need to match against the base Keywords (e.g. "Walmart" matches "Walmart Supercenter 1")
        matched_result = None
        for keyword in config.STORE_KEYWORDS:
            if keyword.lower() in original_name.lower():
                matched_result = keyword
                break
        
        if matched_result:
            # It belongs to a known chain
            if matched_result not in found_chains:
                # This is the closest one for this chain!
                unique_stores[original_name] = entry["loc"]
                unique_addresses[original_name] = entry["address"]
                found_chains.add(matched_result)
                print(f"  ✅ Keeping closest {matched_result}: {original_name} ({int(entry['dist'])}m²)")
            else:
                print(f"  ❌ Skipping duplicate {matched_result}: {original_name} (Further away)")
            
    print(f"Filtered {len(stores)} locations -> {len(unique_stores)} unique chains.")
    return unique_stores, unique_addresses

# --- FUNCTION: Filter Stores via Gemini ---
def filter_stores_with_gemini(
    store_locations: Dict[str, Tuple[float, float]], 
    shopping_list_keys: List[str], 
    max_stores: int = 10,
    user_loc: Tuple[float, float] = None
) -> Dict[str, Tuple[float, float]]:
    """
    Uses Gemini to intelligently filter stores based on relevance to the shopping list.
    Falls back to distance-based filtering if Gemini fails.
    """
    print(f"\n--- AI Store Filtering (Gemini) ---")
    print(f"Raw store count: {len(store_locations)}")
    
    if not store_locations:
        return {}
        
    try:
        class StoreSelectionResponse(BaseModel):
            selected_stores: List[str]
            reasoning: str

        gemini_api_key = os.environ.get("GEMINI_API_KEY_V")
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY_V not found in environment variables.")

        client = genai.Client(api_key=gemini_api_key)
        
        store_names = list(store_locations.keys())
        store_list_str = ", ".join(store_names)
        
        prompt = (
            f"I have a list of places found on a map: {store_list_str}. "
            f"I need to buy vegetables: {', '.join(shopping_list_keys)}. "
            "Identify the actual grocery stores, supermarkets, and places suitable for buying fresh produce. "
            "Exclude gas stations, dollar stores (unless they sell produce), pharmacies, and extensive duplicates of the same chain if they are redundant (keep 2-3 closest if unsure, or all if distinct). "
            f"Select up to {max_stores} best options. "
            "Return the exact names from the list that should be kept."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StoreSelectionResponse,
            )
        )
        
        selection = response.parsed
        print(f"Gemini Reasoning: {selection.reasoning}")
        
        # Filter the main dictionary
        gemini_selected_stores = {}
        for name in selection.selected_stores:
            # Try exact match first
            if name in store_locations:
                gemini_selected_stores[name] = store_locations[name]
            else:
                # Content matching for minor hallucinations/formatting diffs
                for original_name in store_locations:
                    if name.lower() in original_name.lower():
                        gemini_selected_stores[original_name] = store_locations[original_name]
                        break
        
        if gemini_selected_stores:
            print(f"Gemini selected {len(gemini_selected_stores)} stores.")
            return gemini_selected_stores
        else:
            print("Gemini returned no stores. Falling back to simple distance filtering.")
            
    except Exception as e:
        print(f"Gemini Filtering Failed: {e}")
        print("Falling back to distance filtering.")

    # Fallback: Distance-based filtering
    if user_loc:
        distances = []
        start_lat, start_lon = user_loc
        for name, (lat, lon) in store_locations.items():
            dist_sq = (lat - start_lat)**2 + (lon - start_lon)**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        return {name: loc for _, name, loc in distances[:max_stores]}
    else:
        # If no user_loc provided, just return the first N stores
        return {k: store_locations[k] for k in list(store_locations.keys())[:max_stores]}
