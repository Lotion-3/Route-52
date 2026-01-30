
import os
import googlemaps
from dotenv import load_dotenv

# Load env in case it's needed for keys
load_dotenv('config.env')

def simple_debug():
    print("Staritng debug...")
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        # Fallback if env var not loaded correctly
        key = 'AIzaSyAO91icuarLlR50fpKZ7ILBP_n8TfkRdak' 
    
    gmaps = googlemaps.Client(key=key)
    
    # Use Indianapolis center if user loc is hard to determine
    loc = (39.7684, -86.1581) 
    print(f"Searching near {loc}...")
    
    try:
        # Try both variations
        for kw in ["Trader Joe's", "Trader Joes"]:
            print(f"\nSearching for '{kw}':")
            results = gmaps.places_nearby(location=loc, radius=50000, keyword=kw)
            places = results.get('results', [])
            print(f"Found {len(places)} locations.")
            for p in places[:5]:
                print(f" - {p['name']} ({p.get('vicinity')})")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    simple_debug()
