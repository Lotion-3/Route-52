import openrouteservice
from googlemaps import Client as GoogleMapsClient
from shapely.geometry import shape, Point
import config

# --- CONFIGURATION ---
ORS_KEY = config.ORS_API_KEY
GOOGLE_KEY = config.GOOGLE_MAPS_API_KEY

# --- INPUT & GEOCODING ---
gmaps = GoogleMapsClient(key=GOOGLE_KEY)

address = input("Enter the starting address: ")
geocode_result = gmaps.geocode(address)

if not geocode_result:
    print("Error: Could not geocode address.")
    exit()

loc = geocode_result[0]['geometry']['location']
START_COORDS = [loc['lng'], loc['lat']] # [Longitude, Latitude]
print(f"Coordinates found: {START_COORDS}")

TRAVEL_TIME_SEC = 3600                
TRAVEL_MODE = 'driving-car'         # options: 'driving-car', 'cycling-regular', etc.

# --- 1. GENERATE ISOCHRONE ---
ors_client = openrouteservice.Client(key=ORS_KEY)
iso_geojson = ors_client.isochrones(
    locations=[START_COORDS],
    profile=TRAVEL_MODE,
    range=[TRAVEL_TIME_SEC],
    attributes=['total_pop']
)

# Convert to a Shapely polygon for spatial filtering
iso_polygon = shape(iso_geojson['features'][0]['geometry'])
bounds = iso_polygon.bounds  # (minx, miny, maxx, maxy)

# --- 2. QUERY GOOGLE PLACES ---
# We search using the center and a radius that covers the bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lng = (bounds[0] + bounds[2]) / 2
radius = 50000  # Max radius is 50000 meters

# Define the list of stores you want to search for
STORE_KEYWORDS = ['Walmart', 'Aldi', 'Kroger', 'Target', 'Meijer', 'Whole Foods', 'Trader Joe', 'Costco', 'Jewel Osco']
found_stores = []

print(f"Searching for: {', '.join(STORE_KEYWORDS)}...")

for keyword in STORE_KEYWORDS:
    # Search specifically for the current keyword
    results = gmaps.places_nearby(
        location=(center_lat, center_lng),
        radius=radius,
        keyword=keyword
    )
    
    # --- 3. FILTER RESULTS BY ISOCHRONE SHAPE ---
    count_for_keyword = 0
    for place in results.get('results', []):
        lat = place['geometry']['location']['lat']
        lng = place['geometry']['location']['lng']
        point = Point(lng, lat)
        
        # Only keep the store if it is TRULY inside the isochrone
        if iso_polygon.contains(point):
            found_stores.append({
                'name': place['name'],
                'address': place.get('vicinity'),
                'type': keyword
            })
            count_for_keyword += 1
            
    # Optional: Feedback per keyword
    # print(f"  Found {count_for_keyword} {keyword}s in range.")

# --- OUTPUT ---
print(f"\nFound {len(found_stores)} total stores within the {TRAVEL_TIME_SEC//60} min {TRAVEL_MODE} isochrone:")
for store in found_stores:
    print(f"- {store['name']} ({store['type']}) at {store['address']}")