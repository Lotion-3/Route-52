
import requests
import time
from typing import Dict, List, Tuple, Union, Any, Optional
import config

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
    
    try:
        response = requests.post(config.ORS_ISOCHRONE_URL, headers=headers, json=payload, timeout=15)
        
        # Debug: Print response details
        print(f"Request URL: {config.ORS_ISOCHRONE_URL}")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Response Text: {response.text[:200]}")
        
        response.raise_for_status()
        data = response.json()
        
        isochrone_feature = data.get('features', [{}])[0]
        if isochrone_feature and isochrone_feature.get('geometry'):
            print("Success! Reachable area calculated.")
            return isochrone_feature.get('geometry')
        
        print("Error: Isochrone API returned no valid geometry.")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Isochrone data: {e}")
        return None

# --- FUNCTION: Find Eligible Stores ---
def find_eligible_stores_overpass(bbox: Tuple[float, float, float, float]) -> Dict[str, Tuple[float, float]]:
    """Find grocery stores within bounding box using Overpass API."""
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

def get_distance_matrix(locations: List[Tuple[float, float]]) -> Union[Dict[str, Any], None]:
    ors_locations = convert_locations_to_ors_format(locations)
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
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.exceptions.RequestException:
            return None
    
    return None

def process_matrix_result(matrix_response: Dict) -> List[List[float]]:
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
