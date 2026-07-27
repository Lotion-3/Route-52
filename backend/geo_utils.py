
import requests
import time
import math
import os
from typing import Dict, List, Tuple, Union, Any, Optional
import config
from cache_manager import cache

import googlemaps
from shapely.geometry import shape, Point


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

    stores: Dict[str, Tuple[float, float]] = {}
    store_addresses: Dict[str, str] = {}

    GROCERY_TYPES = {'grocery_or_supermarket', 'supermarket', 'store',
                     'department_store', 'shopping_mall', 'food'}
    _SUPERMARKET_TYPES = {'supermarket', 'grocery_or_supermarket',
                          'department_store', 'shopping_mall'}

    def _is_valid_grocery(place: dict) -> bool:
        name = place.get('name', '')
        if any(term in name.lower() for term in config.EXCLUDED_STORE_TERMS):
            return False
        types = place.get('types', [])
        if not any(t in types for t in GROCERY_TYPES):
            return False
        if ('gas_station' in types or 'car_repair' in types) and not any(t in types for t in _SUPERMARKET_TYPES):
            return False
        return True

    def _near_existing(lat: float, lng: float) -> bool:
        # Skip a result physically the same as one we already kept (~120m) —
        # e.g. "Trader Joe's" and "Trader Joes" resolving to one store.
        for (elat, elng) in stores.values():
            if _haversine_km((lat, lng), (elat, elng)) < 0.12:
                return True
        return False

    print(f"Searching nearest-first for {len(config.STORE_KEYWORDS)} chains...")

    # rank_by='distance' returns results NEAREST-FIRST, so we take the single
    # closest in-range valid store per chain and stop — instead of pulling ~20
    # results per keyword and collecting every store only to filter later. Cuts
    # the results processed per call from ~20 to ~1 and yields exactly one store
    # per chain (making the downstream unique-chain filter a no-op).
    for keyword in config.STORE_KEYWORDS:
        try:
            results = gmaps.places_nearby(
                location=center_point, keyword=keyword, rank_by='distance',
            )
            for place in results.get('results', []):
                loc = place['geometry']['location']
                lat, lng = loc['lat'], loc['lng']
                if not iso_polygon.contains(Point(lng, lat)):
                    continue                # out of reachable range
                if not _is_valid_grocery(place):
                    continue                # wrong type / excluded
                if _near_existing(lat, lng):
                    # Same physical store another keyword already captured. Keep
                    # scanning this keyword's results — `break` here abandoned the
                    # whole chain, so a distinct store sharing a strip mall with an
                    # already-found one was dropped entirely.
                    continue
                name = place['name']
                original, n = name, 1
                while name in stores:
                    name = f"{original} {n}"; n += 1
                stores[name] = (lat, lng)
                store_addresses[name] = place.get('vicinity', 'Unknown Address')
                break                       # nearest valid store for this chain — done
        except Exception as e:
            print(f"Error searching for {keyword}: {e}")

    print(f"Found {len(stores)} eligible store(s) (nearest per chain).")
    cache.set(cache_key, (stores, store_addresses))
    return stores, store_addresses

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
                print(f"  ✅ Keeping closest {matched_result}: {original_name} "
                      f"({_haversine_km(user_loc, entry['loc']):.1f} km)")
            else:
                print(f"  ❌ Skipping duplicate {matched_result}: {original_name} (Further away)")
            
    print(f"Filtered {len(stores)} locations -> {len(unique_stores)} unique chains.")
    return unique_stores, unique_addresses
