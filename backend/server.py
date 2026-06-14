import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware  # Added for CORS
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
import config
import meal_planner
import fridge_manager
import geo_utils
import data_manager
import optimizer
import kroger_async
from kroger_async import is_kroger_banner
import aldi_pricing
from aldi_pricing import is_aldi_store
import kingsoopers_pricing
from kingsoopers_pricing import is_king_soopers_store
import instacart_pricing
from instacart_pricing import get_instacart_slug, is_instacart_retailer
import walmart_pricing
from walmart_pricing import is_walmart_store
import trader_joes_pricing
from trader_joes_pricing import is_trader_joes_store
import flipp_coupons
from kroger_pricing import aggregate_ingredients
from geopy.geocoders import Nominatim

import logging
import traceback

# Setup logging
logging.basicConfig(filename='server_error.log', level=logging.ERROR)

SERVER_VERSION = "2.1.0-STRICT-BENCHMARK"
print(f"\n🚀 BASKET BUDDY SERVER STARTING - VERSION: {SERVER_VERSION}", flush=True)

app = FastAPI()
router = APIRouter(prefix="/api")

@app.middleware("http")
async def catch_exceptions_middleware(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        err_msg = f"Unhandled exception: {exc}\n{traceback.format_exc()}"
        print(f"🔥 CRITICAL ERROR:\n{err_msg}")
        logging.error(err_msg)
        return {"error": str(exc), "traceback": traceback.format_exc()}

# --- CORS CONFIGURATION START ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for local dev to prevent connectivity issues with physical devices
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CORS CONFIGURATION END ---

# Data Models
class UserPreferences(BaseModel):
    address: str
    shopping_time_hours: float = 3.0
    budget: float = 150.0
    calorie_target: int = 2000
    household_size: int = 1
    days_plan: int = 7
    meals_per_day: int = 3
    dietary_restrictions: Optional[str] = None
    health_issues: Optional[str] = None
    cuisines: Optional[str] = None
    experiment: bool = True
    cook_time: str = "30-45 minutes"
    fridge_image_path: Optional[str] = None 
    fridge_items: Optional[str] = None
    has_costco_card: bool = False
    dev_mode: int = 1

class PlanRequest(BaseModel):
    preferences: UserPreferences

@app.get("/")
def read_root():
    return {"message": "Route 52 Backend is running!"}

@router.get("/")
def read_root_api():
    return {"message": "Route 52 Backend is running!"}

@router.post("/generate_plan")
def generate_plan(request: PlanRequest):
    print(f"\n📥 RECEIVED PLAN REQUEST (Server v{SERVER_VERSION})", flush=True)
    prefs = request.preferences
    
    # 1. Geocode Address with Cache
    from cache_manager import cache
    cache_key = {"func": "geocode", "address": prefs.address}
    cached_loc = cache.get(cache_key)
    
    if cached_loc:
        print(f"Using cached location for: {prefs.address}")
        user_loc = (cached_loc['lat'], cached_loc['lon'])
    else:
        geolocator = Nominatim(user_agent="basket_buddy_backend")
        location = geolocator.geocode(prefs.address)
        
        if not location:
            raise HTTPException(status_code=400, detail="Address not found")
            
        user_loc = (location.latitude, location.longitude)
        cache.set(cache_key, {'lat': location.latitude, 'lon': location.longitude})
    
    # 2. Update Config
    # Each person needs calorie_target, so total is target * days * size
    config.TOTAL_WEEKLY_CALORIES = prefs.calorie_target * prefs.days_plan * prefs.household_size
    
    # 3. Handle Fridge Items
    fridge_items = prefs.fridge_items or ""
    if prefs.fridge_image_path and os.path.exists(prefs.fridge_image_path):
        vision_items = fridge_manager.analyze_fridge_image(prefs.fridge_image_path)
        if vision_items:
            fridge_items = f"{fridge_items}, {vision_items}"
    
    # 4. Generate Meal Plan
    # Pass household_size so AI knows to scale ingredients
    print(f"\n📦 FINAL FRIDGE LIST FOR MEAL PLANNER: {repr(fridge_items)}", flush=True)
    meal_plan, ingredient_data = meal_planner.create_weekly_meal_plan(
        prefs.days_plan, prefs.meals_per_day, prefs.calorie_target,
        prefs.dietary_restrictions, prefs.cuisines, fridge_items, prefs.experiment, prefs.cook_time,
        prefs.health_issues, prefs.budget, prefs.household_size
    )
    
    if not ingredient_data:
        raise HTTPException(status_code=500, detail="Failed to generate meal plan")

    # Aggregate ingredient totals across all meals using proper base-unit math
    # (handles mixed units for the same ingredient across different meals).
    # meal_plan quantities are already scaled by household_size, so pass 1 here.
    aggregated = aggregate_ingredients(meal_plan, household_size=1)

    to_buy_quantities = {}
    at_home_ingredients = []

    for name, data in aggregated.items():
        # ingredient_data keys are lowercased; match by normalizing
        ing_meta = ingredient_data.get(name.lower().strip(), {})
        if ing_meta.get("is_at_home"):
            at_home_ingredients.append({"name": name, "qty": data["qty"], "unit": data["unit"]})
        else:
            to_buy_quantities[name] = {"qty": data["qty"], "unit": data["unit"]}

    print("\n" + "-" * 40)
    print(f"📋 INGREDIENTS NEEDED (TO BUY) [{len(to_buy_quantities)} items]:")
    for item, data in to_buy_quantities.items():
        print(f"   • {item.title()} ({data.get('qty')} {data.get('unit')})")
    print(f"🏠 INGREDIENTS ALREADY AT HOME [{len(at_home_ingredients)} items]:")
    for item in at_home_ingredients:
        print(f"   • {item['name'].title()} ({item['qty']} {item['unit']})")
    print("-" * 40)

    # 5. Find Stores & Optimize
    # Normalize Shopping Time: if user entered > 10, they probably meant minutes
    sh_hours = prefs.shopping_time_hours
    if sh_hours > 12: # Likely minutes
        sh_hours = sh_hours / 60.0

    MAX_TIME_SECS = sh_hours * 3600
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(user_loc, ONE_WAY_TIME_SECONDS)
    
    if not isochrone_geometry:
        # Fallback: 15 km bounding box around user
        print("[Server] ORS isochrone failed — using 15 km bounding-box fallback.", flush=True)
        lat0, lon0 = user_loc
        D = 0.135  # ~15 km in degrees
        isochrone_geometry = {
            "type": "Polygon",
            "coordinates": [[
                [lon0 - D, lat0 - D],
                [lon0 + D, lat0 - D],
                [lon0 + D, lat0 + D],
                [lon0 - D, lat0 + D],
                [lon0 - D, lat0 - D],
            ]]
        }
    
    # --- STORE FILTERING ---
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, user_loc)
    print(f"DEBUG: Found {len(STORE_LOCATIONS)} raw stores: {list(STORE_LOCATIONS.keys())}")
    
    # Costco Membership Filter
    print(f"DEBUG: Costco Card Preference = {prefs.has_costco_card}")
    if not prefs.has_costco_card:
        print("🚫 Filtering out Costco stores...")
        filtered_locations = {}
        filtered_addresses = {}
        for k, v in STORE_LOCATIONS.items():
            k_lower = k.lower()
            if "costco" not in k_lower:
                filtered_locations[k] = v
                filtered_addresses[k] = STORE_ADDRESSES.get(k, "")
            else:
                print(f"   - Removed Costco store: {k}")
        STORE_LOCATIONS = filtered_locations
        STORE_ADDRESSES = filtered_addresses

    # Filter to unique chains closest to user
    STORE_LOCATIONS_RAW, STORE_ADDRESSES_RAW = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, user_loc)
    
    # Strip all keys to prevent mismatches between matrix, price db, and optimizer
    STORE_LOCATIONS = {k.strip(): v for k, v in STORE_LOCATIONS_RAW.items()}
    STORE_ADDRESSES = {k.strip(): v for k, v in STORE_ADDRESSES_RAW.items()}
    
    print(f"DEBUG: Stores after chain filtering & stripping: {list(STORE_LOCATIONS.keys())}")

    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = []
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - user_loc[0])**2 + (lon - user_loc[1])**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
        STORE_ADDRESSES = {name: STORE_ADDRESSES[name] for name in STORE_LOCATIONS}
    
    all_coords = [user_loc] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    
    # Step 7: Get prices
    # Start with synthetic prices for all stores as a baseline.
    # Real Kroger prices will override the Kroger store if one is nearby.
    price_database, removed_items, shopping_list = data_manager.generate_synthetic_market(
        to_buy_quantities, list(STORE_LOCATIONS.keys())
    )

    # Attempt real Kroger pricing for the nearest Kroger-family store.
    lat, lon = user_loc
    try:
        kroger_store_name, kroger_store_id, kroger_prices = asyncio.run(
            kroger_async.price_all_async(to_buy_quantities, lat, lon)
        )
    except Exception as e:
        print(f"[Kroger] Async pricing failed ({e}), using synthetic prices.")
        kroger_store_name, kroger_prices = None, {}

    # If Kroger API returned nothing, try King Soopers via Instacart (Colorado fallback).
    if not kroger_prices:
        ks_key = next((k for k in price_database if is_king_soopers_store(k)), None)
        if ks_key:
            print("[KS] Kroger API empty and King Soopers store in route — trying Instacart fallback.", flush=True)
            try:
                ks_store_name, ks_store_id, ks_prices = kingsoopers_pricing.price_all_ks(
                    to_buy_quantities, lat, lon
                )
                if ks_prices:
                    kroger_prices = ks_prices
                    kroger_store_name = ks_store_name
                    print(f"[KS] Instacart fallback priced {len(ks_prices)} ingredients.", flush=True)
            except Exception as e:
                print(f"[KS] Instacart fallback failed ({e}).", flush=True)

    if kroger_prices:
        # Find the matching Kroger-family store in the optimizer's store list.
        kroger_key = next(
            (k for k in price_database if is_kroger_banner(k)), None
        )
        if kroger_key:
            print(f"[Kroger] Applying real prices to store: '{kroger_key}'", flush=True)
            for ing_name, result in kroger_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                # Store as unit_price so optimizer's (unit_price × qty = total_cost) stays correct.
                price_database[kroger_key][ing_name.lower().strip()] = total_cost / qty
        else:
            print("[Kroger] Real prices fetched but no Kroger-family store in route — discarding.")

    # Attempt real ALDI pricing if an ALDI store is in the optimizer's store list.
    aldi_key = next((k for k in price_database if is_aldi_store(k)), None)
    if aldi_key:
        try:
            aldi_store_name, aldi_store_id, aldi_prices = aldi_pricing.price_all_aldi(
                to_buy_quantities, lat, lon
            )
        except Exception as e:
            print(f"[ALDI] Pricing failed ({e}), using synthetic prices.", flush=True)
            aldi_prices = {}

        if aldi_prices:
            print(f"[ALDI] Applying real prices to store: '{aldi_key}'", flush=True)
            for ing_name, result in aldi_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                price_database[aldi_key][ing_name.lower().strip()] = total_cost / qty
    else:
        print("[ALDI] No ALDI store in route — skipping real pricing.", flush=True)

    # Track which store keys already have real pricing so we don't double-price.
    _priced_keys: set[str] = set()
    if kroger_prices:
        kroger_key_tmp = next((k for k in price_database if is_kroger_banner(k)), None)
        if kroger_key_tmp:
            _priced_keys.add(kroger_key_tmp)
    if aldi_key:
        _priced_keys.add(aldi_key)

    # Price all remaining stores: Walmart, Trader Joe's, and any Instacart retailer.
    for store_key in list(price_database.keys()):
        if store_key in _priced_keys:
            continue
        if is_kroger_banner(store_key) or is_aldi_store(store_key):
            continue  # Handled above

        # --- Walmart (via Instacart; direct scrape is blocked by PerimeterX) ---
        if is_walmart_store(store_key):
            try:
                _, _, wm_prices = instacart_pricing.price_all_instacart(
                    to_buy_quantities, lat, lon, "walmart"
                )
                if wm_prices:
                    print(f"[IC:walmart] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in wm_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        price_database[store_key][ing_name.lower().strip()] = total_cost / qty
                    _priced_keys.add(store_key)
            except Exception as e:
                print(f"[Walmart] Pricing failed ({e}).", flush=True)
            continue

        # --- Trader Joe's ---
        if is_trader_joes_store(store_key):
            try:
                _, tj_prices = trader_joes_pricing.price_all_tj(to_buy_quantities)
                if tj_prices:
                    print(f"[TJ] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in tj_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        price_database[store_key][ing_name.lower().strip()] = total_cost / qty
                    _priced_keys.add(store_key)
            except Exception as e:
                print(f"[TJ] Pricing failed ({e}).", flush=True)
            continue

        # --- Generic Instacart retailer ---
        slug = get_instacart_slug(store_key)
        if slug:
            try:
                _, _, ic_prices = instacart_pricing.price_all_instacart(
                    to_buy_quantities, lat, lon, slug
                )
                if ic_prices:
                    print(f"[IC:{slug}] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in ic_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        price_database[store_key][ing_name.lower().strip()] = total_cost / qty
                    _priced_keys.add(store_key)
            except Exception as e:
                print(f"[IC:{slug}] Pricing failed ({e}).", flush=True)

    # Step 7b: Apply real Flipp deals (weekly flyers + digital coupons) to the
    # price database BEFORE optimization, so savings affect both the cheapest-
    # route comparison and the displayed prices.
    applied_deals: dict = {}
    try:
        postal = instacart_pricing._get_postal(lat, lon)
        if postal:
            flyers, coupons = flipp_coupons.fetch_deals(postal)
            if flyers or coupons:
                applied_deals = flipp_coupons.apply_deals(
                    price_database, to_buy_quantities, flyers, coupons
                )
                print(f"[Flipp] Applied {len(applied_deals)} real deals to the price database.", flush=True)
        else:
            print("[Flipp] No postal code for this location — skipping deals.", flush=True)
    except Exception as e:
        print(f"[Flipp] Deal application failed ({e}).", flush=True)

    config.MAX_TIME_SECONDS = MAX_TIME_SECS
    optimal_route, item_cost, total_time_seconds, item_assignments, cheapest_single_store_cost, cheapest_single_store_name = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    formatted_shopping_list = []
    if optimal_route:
        for store_raw in optimal_route:
            store = store_raw.strip()
            if store == "Start": continue # Skip the start location in the list
            items = item_assignments.get(store_raw, [])
            store_items = []
            for item_data in items:
                item_name = item_data["name"]
                item_qty = item_data["qty"]
                lookup_key = item_name.lower().strip()
                store_prices = price_database.get(store, {})
                unit_price = store_prices.get(lookup_key, 0.0)
                
                # Debug logging to catch mismatches
                if unit_price == 0.0:
                    available_keys = list(store_prices.keys())
                    print(f"❌ PRICE MISS: Store '{store}' | Key '{lookup_key}' not found.")
                    print(f"   Available keys in this store: {available_keys[:20]}")
                
                total_item_price = unit_price * item_qty
                item_entry = {"name": item_name, "qty": item_qty, "price": total_item_price}

                # Attach a real Flipp deal if one was applied to this line.
                deal = applied_deals.get((store, lookup_key))
                if deal:
                    orig_unit = deal["old_unit"]
                    item_entry["original_price"] = round(orig_unit * item_qty, 2)
                    item_entry["coupon"] = {
                        "type": deal["type"],
                        "label": deal["label"],
                        "savings": deal["savings"],
                        "image_url": deal.get("image_url", ""),
                        "valid_to": deal.get("valid_to", ""),
                    }
                store_items.append(item_entry)
            
            formatted_shopping_list.append({
                "store": store,
                "address": STORE_ADDRESSES.get(store, ""),
                "coordinates": {"lat": STORE_LOCATIONS[store][0], "lng": STORE_LOCATIONS[store][1]},
                "items": store_items
            })

    # Step 8: Calculate prices for meal ingredients
    # Create a lookup for unit prices based on optimal assignments
    item_unit_prices = {}
    for store_name, items in item_assignments.items():
        if store_name == "Start": continue
        store_prices = price_database.get(store_name, {})
        for itm in items:
            l_key = itm["name"].lower().strip()
            item_unit_prices[l_key] = store_prices.get(l_key, 0.0)

    # Attach prices to meal plan ingredients
    for meal in meal_plan:
        for ing in meal.get('ingredients', []):
            l_key = ing['name'].lower().strip()
            u_price = item_unit_prices.get(l_key, 0.0)
            ing['price'] = u_price * ing['qty']

    res = {
        "meal_plan": meal_plan,
        "shopping_list": formatted_shopping_list,
        "at_home_ingredients": at_home_ingredients,
        "total_cost": item_cost if item_cost != float('inf') else 0,
        "cheapest_single_store_cost": cheapest_single_store_cost if cheapest_single_store_cost != float('inf') else 0,
        "cheapest_single_store_name": cheapest_single_store_name,
        "total_time_minutes": total_time_seconds / 60 if total_time_seconds else 0,
        "route": optimal_route if optimal_route else [],
        "user_location": {"lat": user_loc[0], "lng": user_loc[1]},
        "total_savings": round(sum(d["savings"] for d in applied_deals.values()), 2),
    }
    print(f"DEBUG SERVER: Sending benchmark {cheapest_single_store_name} to frontend", flush=True)
    return res

@router.post("/optimize_shopping")
def optimize_shopping_route(data: Dict):
    return {"message": "Optimization endpoint not fully implemented yet"}

app.include_router(router)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)