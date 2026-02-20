
import googlemaps
import config
from shapely.geometry import shape, Point
import geo_utils
import os

def debug_trader_joes():
    print("DEBUG: searching for Trader Joe's...")
    
    # User's default location from main.py if not dynamic (using config default for test)
    user_loc = config.USER_START_LOCATION
    print(f"User Location: {user_loc}")
    
    gmaps = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)
    
    # 1. Check what Google Places returns directly
    print("\n1. Direct Google Places Search (Radius 50km)...")
    try:
        results = gmaps.places_nearby(
            location=user_loc,
            radius=50000,
            keyword="Trader Joe's"
        )
        places = results.get('results', [])
        print(f"Found {len(places)} results for 'Trader Joe's':")
        for p in places:
            print(f" - {p['name']} @ {p.get('vicinity')} (Lat: {p['geometry']['location']['lat']}, Lng: {p['geometry']['location']['lng']})")
    except Exception as e:
        print(f"Error in places search: {e}")

    # 2. Check Isochrone
    print("\n2. Checking Isochrone containment...")
    # Calculate isochrone for 45 mins (same as main.py logic: 3 hours total / 4 = 45 mins one way)
    one_way_secs = int(config.SHOPPING_TIME_HOURS * 3600 / 4)
    iso_geo = geo_utils.get_travel_isochrone(user_loc, one_way_secs)
    
    if iso_geo:
        iso_polygon = shape(iso_geo)
        print(f"Isochrone calculated. Valid: {iso_polygon.is_valid}")
        
        # Check if the found places are inside
        for p in places:
            lat = p['geometry']['location']['lat']
            lng = p['geometry']['location']['lng']
            point = Point(lng, lat)
            is_inside = iso_polygon.contains(point)
            print(f" - {p['name']} inside isochrone? {is_inside}")
    else:
        print("Failed to calculate isochrone.")

if __name__ == "__main__":
    debug_trader_joes()
