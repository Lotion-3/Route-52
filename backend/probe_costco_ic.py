"""
Test Instacart Costco coverage and pricing across 12 US cities.
Shows which cities have Costco on Instacart, what gets priced, and prices.
"""
import sys
sys.path.insert(0, ".")
import instacart_pricing

BASKET = {
    "milk":           {"qty": 1,  "unit": "gallon"},
    "eggs":           {"qty": 12, "unit": "count"},
    "bananas":        {"qty": 3,  "unit": "pound"},
    "chicken breast": {"qty": 3,  "unit": "pound"},
    "white rice":     {"qty": 5,  "unit": "pound"},
    "olive oil":      {"qty": 1,  "unit": "count"},
    "bread":          {"qty": 1,  "unit": "loaf"},
}

CITIES = [
    ("New York, NY",       40.7128,  -74.0060),
    ("Los Angeles, CA",    34.0522, -118.2437),
    ("Chicago, IL",        41.8781,  -87.6298),
    ("Houston, TX",        29.7604,  -95.3698),
    ("Phoenix, AZ",        33.4484, -112.0740),
    ("Philadelphia, PA",   39.9526,  -75.1652),
    ("Seattle, WA",        47.6062, -122.3321),
    ("Denver, CO",         39.7392, -104.9903),
    ("Atlanta, GA",        33.7490,  -84.3880),
    ("Dallas, TX",         32.7767,  -96.7970),
    ("Miami, FL",          25.7617,  -80.1918),
    ("Boston, MA",         42.3601,  -71.0589),
]

print(f"{'City':<22} {'Store':<30} {'Priced':>7} {'Total $':>9}  Prices")
print("-" * 100)

for city, lat, lon in CITIES:
    try:
        name, sid, prices = instacart_pricing.price_all_instacart(BASKET, lat, lon, "costco")
        if prices:
            total = sum(v.get("total_cost", 0) for v in prices.values() if v)
            detail = "  ".join(f"{k}=${v.get('total_cost',0):.2f}" for k, v in sorted(prices.items()) if v)
            print(f"  {city:<20} {str(name)[:28]:<30} {len(prices):>2}/{len(BASKET):<4} ${total:>7.2f}  {detail[:55]}")
        else:
            print(f"  {city:<20} {'NO STORE FOUND':<30} {'0':>2}/{len(BASKET):<4}  (Costco not on Instacart here)")
    except Exception as e:
        print(f"  {city:<20} ERROR: {str(e)[:50]}")
