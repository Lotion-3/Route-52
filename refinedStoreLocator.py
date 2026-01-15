import openrouteservice
from googlemaps import Client as GoogleMapsClient
from shapely.geometry import shape, Point

# --- CONFIGURATION ---
ORS_KEY = 'eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjcxNjJmZGM4Yzg2YzQwMTM4MDU4YmExZGQ5ODdlOTdjIiwiaCI6Im11cm11cjY0In0='
GOOGLE_KEY = 'AIzaSyAO91icuarLlR50fpKZ7ILBP_n8TfkRdak'
START_COORDS = [-86.1151735, 39.9651798]  # [Longitude, Latitude]
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
gmaps = GoogleMapsClient(key=GOOGLE_KEY)
# We search using the center and a radius that covers the bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lng = (bounds[0] + bounds[2]) / 2
radius = 1500  # Adjust based on your isochrone size

# Define types for grocery and retail
# Google uses specific types: https://developers.google.com/maps/documentation/places/web-service/supported_types
place_types = ['grocery_or_supermarket', 'department_store']
found_stores = []

for p_type in place_types:
    results = gmaps.places_nearby(
        location=(center_lat, center_lng),
        radius=radius,
        type=p_type
    )
    
    # --- 3. FILTER RESULTS BY ISOCHRONE SHAPE ---
    for place in results.get('results', []):
        lat = place['geometry']['location']['lat']
        lng = place['geometry']['location']['lng']
        point = Point(lng, lat)
        
        # Only keep the store if it is TRULY inside the isochrone
        if iso_polygon.contains(point):
            found_stores.append({
                'name': place['name'],
                'address': place.get('vicinity'),
                'type': p_type
            })

# --- OUTPUT ---
print(f"Found {len(found_stores)} stores within the {TRAVEL_TIME_SEC//60} min {TRAVEL_MODE} isochrone:")
for store in found_stores:
    print(f"- {store['name']} ({store['type']}) at {store['address']}")