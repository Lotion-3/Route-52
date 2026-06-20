import asyncio
import json
import math
import uvicorn
from fastapi import FastAPI, HTTPException, APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
import config
import meal_planner
import fridge_manager
import geo_utils
import optimizer
import kroger_async
from kroger_async import is_kroger_banner
from aldi.aldi_pricing import price_all_aldi, is_aldi_store
import kingsoopers_pricing
from kingsoopers_pricing import is_king_soopers_store
import instacart_pricing
from instacart_pricing import get_instacart_slug
import walmart_pricing
from walmart_pricing import is_walmart_store
import trader_joes_pricing
from trader_joes_pricing import is_trader_joes_store
import meijer_pricing
from meijer_pricing import is_meijer_store
import target_pricing
from target_pricing import is_target_store
import matcher
import coupon_scraper
from kroger_pricing import aggregate_ingredients
from geopy.geocoders import Nominatim

import logging
import traceback

# Setup logging
logging.basicConfig(filename='server_error.log', level=logging.ERROR)

SERVER_VERSION = "3.0.0-SUPABASE"
print(f"\nBASKET BUDDY SERVER STARTING - VERSION: {SERVER_VERSION}", flush=True)

app = FastAPI()
router = APIRouter(prefix="/api")


# ── Supabase Auth Dependency ───────────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Extract the Supabase user_id from the JWT in the Authorization header.
    Returns None for anonymous requests (no token provided).
    """
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    try:
        from db import db
        user = db.client.auth.get_user(token)
        return user.user.id if user and user.user else None
    except Exception as e:
        print(f"[Auth] JWT verification failed: {e}", flush=True)
        return None


# ── Helper: save results to Supabase ──────────────────────────────────────
def _save_results(user_id: str | None, prefs: "UserPreferences", meal_plan: list,
                  shopping_list: list, route: list, total_cost: float,
                  cheapest_store_name: str, cheapest_store_cost: float,
                  total_time_minutes: float) -> None:
    """Persist the generated plan and route to Supabase when a user is authenticated."""
    if not user_id:
        return
    try:
        from db import db
        plan = db.save_meal_plan(
            user_id=user_id,
            preferences={
                "address": prefs.address,
                "budget": prefs.budget,
                "calorie_target": prefs.calorie_target,
                "household_size": prefs.household_size,
                "days_plan": prefs.days_plan,
                "meals_per_day": prefs.meals_per_day,
                "dietary_restrictions": prefs.dietary_restrictions,
                "health_issues": prefs.health_issues,
                "cuisines": prefs.cuisines,
            },
            meals=meal_plan,
        )
        db.save_shopping_route(plan["id"], {
            "total_cost": total_cost,
            "total_time_minutes": total_time_minutes,
            "route": route,
            "cheapest_single_store_name": cheapest_store_name,
            "cheapest_single_store_cost": cheapest_store_cost,
        })
        print(f"[Supabase] Saved plan {plan['id']} for user {user_id}", flush=True)
    except Exception as e:
        print(f"[Supabase] Failed to save results: {e}", flush=True)


# ── Coupon-first pricing helpers ──────────────────────────────────────────
STORE_MERCHANT_MAP = {
    "kroger": "kroger", "king soopers": "kroger", "aldi": "aldi",
    "walmart": "walmart", "target": "target", "trader joe": "trader joe",
    "meijer": "meijer", "costco": "costco",
}

def _resolve_merchant(store_key: str) -> str:
    lower = store_key.lower()
    for keyword, merchant in STORE_MERCHANT_MAP.items():
        if keyword in lower:
            return merchant
    return lower

def _overlay_coupon_prices(store_key: str, price_db: dict[str, dict],
                           postal: str, to_buy: dict[str, dict]) -> dict[str, str]:
    """Check coupons for this store and overlay coupon prices on price_db.
    Returns a dict {item_key: source} for items that had coupon matches.
    """
    from db import db
    merchant = _resolve_merchant(store_key)
    coupons = db.get_coupons_by_postal(postal, merchant=merchant)
    if not coupons:
        return {}

    sources = {}
    for ing_name, data in to_buy.items():
        key = ing_name.lower().strip()
        match = matcher.match_item_to_coupon(ing_name, coupons)
        if match and match.get("price", 0) > 0:
            unit_price = match["price"]
            qty = float(data.get("qty", 1) or 1)
            price_db[key] = (unit_price / qty) if qty else unit_price
            sources[key] = "coupon"
            print(f"  [Coupon] {ing_name}: ${unit_price:.2f} at {store_key}", flush=True)
    return sources


@app.on_event("shutdown")
def _close_target_browser():
    # Free the persistent CloakBrowser (~250MB) used for direct Target pricing.
    try:
        target_pricing.shutdown()
    except Exception:
        pass
    try:
        walmart_pricing.shutdown()
    except Exception:
        pass

@app.middleware("http")
async def catch_exceptions_middleware(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        err_msg = f"Unhandled exception: {exc}\n{traceback.format_exc()}"
        print(f"CRITICAL ERROR:\n{err_msg}")
        logging.error(err_msg)
        return JSONResponse(status_code=500, content={"error": str(exc), "traceback": traceback.format_exc()})

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

class PriceListItem(BaseModel):
    name: str
    qty: float = 1.0
    unit: str = "ct"

class PriceListRequest(BaseModel):
    address: str
    shopping_time_hours: float = 3.0
    items: List[PriceListItem]
    has_costco_card: bool = False

@app.get("/")
def read_root():
    return {"message": "Route 52 Backend is running!"}

@router.get("/")
def read_root_api():
    return {"message": "Route 52 Backend is running!"}

@router.post("/generate_plan")
def generate_plan(request: PlanRequest, user_id: Optional[str] = Depends(get_current_user)):
    print(f"\nRECEIVED PLAN REQUEST (Server v{SERVER_VERSION})", flush=True)
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
    # Fetch meals from Supabase (fall back to meals.json if DB unavailable)
    print(f"\nFINAL FRIDGE LIST FOR MEAL PLANNER: {repr(fridge_items)}", flush=True)
    try:
        from db import db
        raw_meals = db.get_meals()
        db_meals = []
        for m in raw_meals:
            if isinstance(m.get("ingredients"), str):
                m["ingredients"] = json.loads(m["ingredients"])
            if isinstance(m.get("instructions"), str):
                m["instructions"] = json.loads(m["instructions"])
            db_meals.append(m)
    except Exception as e:
        print(f"[Supabase] Could not fetch meals from DB ({e}), falling back to meals.json", flush=True)
        db_meals = None
    meal_plan, ingredient_data = meal_planner.create_weekly_meal_plan(
        prefs.days_plan, prefs.meals_per_day, prefs.calorie_target,
        prefs.dietary_restrictions, prefs.cuisines, fridge_items, prefs.experiment, prefs.cook_time,
        prefs.health_issues, prefs.budget, prefs.household_size, meals=db_meals
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
    
    # Step 7: Get real prices for each store; exclude any store where pricing fails.
    lat, lon = user_loc
    price_database: dict = {k.strip(): {} for k in STORE_LOCATIONS.keys()}
    real_priced_keys: set = set()
    product_details: dict = {}  # (store_key, ing_key) → {product_name, size_str}
    costco_estimates: dict = {}  # store_key → {"distance_km": float, "store": str} when proxied

    # shopping_list is needed by the optimizer regardless of pricing source.
    shopping_list = [
        {"name": name, "qty": float(data.get("qty", 1) or 1)}
        for name, data in to_buy_quantities.items()
    ]

    # --- Kroger / King Soopers ---
    try:
        kroger_store_name, kroger_store_id, kroger_prices = asyncio.run(
            kroger_async.price_all_async(to_buy_quantities, lat, lon)
        )
    except Exception as e:
        print(f"[Kroger] Async pricing failed ({e}), store will be excluded.", flush=True)
        kroger_store_name, kroger_prices = None, {}

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
        kroger_key = next((k for k in price_database if is_kroger_banner(k)), None)
        if kroger_key:
            print(f"[Kroger] Applying real prices to store: '{kroger_key}'", flush=True)
            for ing_name, result in kroger_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                key = ing_name.lower().strip()
                price_database[kroger_key][key] = total_cost / qty
                if result.get("description"):
                    brand = result.get("brand", "")
                    product_details[(kroger_key, key)] = {
                        "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                        "size_str": result.get("size_str", ""),
                        "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                    }
            real_priced_keys.add(kroger_key)
        else:
            print("[Kroger] Real prices fetched but no Kroger-family store in route — discarding.", flush=True)

    # --- ALDI ---
    aldi_key = next((k for k in price_database if is_aldi_store(k)), None)
    if aldi_key:
        try:
            aldi_lat, aldi_lon = STORE_LOCATIONS.get(aldi_key, (lat, lon))
            aldi_store_name, aldi_store_id, aldi_prices = price_all_aldi(
                to_buy_quantities, aldi_lat, aldi_lon
            )
        except Exception as e:
            print(f"[ALDI] Pricing failed ({e}), store will be excluded.", flush=True)
            aldi_prices = {}

        if aldi_prices:
            print(f"[ALDI] Applying real prices to store: '{aldi_key}'", flush=True)
            for ing_name, result in aldi_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                unit_price = total_cost / qty if qty else total_cost
                key = ing_name.lower().strip()
                price_database[aldi_key][key] = unit_price
                print(f"  [ALDI price] {ing_name!r}: total=${total_cost:.2f} qty={qty} unit=${unit_price:.3f} | {result.get('description','')}", flush=True)
                if result.get("description"):
                    brand = result.get("brand", "")
                    product_details[(aldi_key, key)] = {
                        "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                        "size_str": result.get("size_str", ""),
                        "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                    }
            real_priced_keys.add(aldi_key)
        else:
            print("[ALDI] Real pricing returned nothing, store will be excluded.", flush=True)
    else:
        print("[ALDI] No ALDI store in route — skipping real pricing.", flush=True)

    # --- Meijer ---
    meijer_key = next((k for k in price_database if is_meijer_store(k)), None)
    if meijer_key:
        try:
            meijer_store_name, meijer_store_id, meijer_prices = meijer_pricing.price_all_meijer(
                to_buy_quantities, lat, lon
            )
        except Exception as e:
            print(f"[Meijer] Pricing failed ({e}), store will be excluded.", flush=True)
            meijer_prices = {}

        if meijer_prices:
            print(f"[Meijer] Applying real prices to store: '{meijer_key}'", flush=True)
            for ing_name, result in meijer_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                key = ing_name.lower().strip()
                price_database[meijer_key][key] = total_cost / qty
                if result.get("description"):
                    brand = result.get("brand", "")
                    product_details[(meijer_key, key)] = {
                        "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                        "size_str": result.get("size_str", ""),
                        "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                    }
            real_priced_keys.add(meijer_key)
        else:
            print("[Meijer] Real pricing returned nothing, store will be excluded.", flush=True)
    else:
        print("[Meijer] No Meijer store in route — skipping direct pricing.", flush=True)

    # --- Walmart, Trader Joe's, and generic Instacart retailers ---
    for store_key in list(price_database.keys()):
        if store_key in real_priced_keys:
            continue
        if is_kroger_banner(store_key) or is_aldi_store(store_key) or is_meijer_store(store_key):
            continue

        if is_trader_joes_store(store_key):
            try:
                _, tj_prices = trader_joes_pricing.price_all_tj(to_buy_quantities)
                if tj_prices:
                    print(f"[TJ] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in tj_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            brand = result.get("brand", "")
                            product_details[(store_key, key)] = {
                                "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
            except Exception as e:
                print(f"[TJ] Pricing failed ({e}), store will be excluded.", flush=True)
            continue

        # Target: try direct RedSky pricing first; on failure fall through to
        # the generic Instacart "target" slug below (zero-regression fallback).
        if is_target_store(store_key):
            try:
                _, _, tg_prices = target_pricing.price_all_target(
                    to_buy_quantities, lat, lon
                )
                if tg_prices:
                    print(f"[Target] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in tg_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            brand = result.get("brand", "")
                            product_details[(store_key, key)] = {
                                "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
                print(f"[Target] Direct pricing empty for '{store_key}' — falling back to Instacart.", flush=True)
            except Exception as e:
                print(f"[Target] Direct pricing failed ({e}) — falling back to Instacart.", flush=True)

        # Walmart: try direct CloakBrowser pricing first; on failure fall through
        # to the generic Instacart "walmart" slug below (zero-regression fallback).
        if is_walmart_store(store_key):
            try:
                _, _, wm_prices = walmart_pricing.price_all_walmart(
                    to_buy_quantities, lat, lon
                )
                if wm_prices:
                    print(f"[Walmart] Applying real prices to '{store_key}'", flush=True)
                    for ing_name, result in wm_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            brand = result.get("brand", "")
                            product_details[(store_key, key)] = {
                                "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
                print(f"[Walmart] Direct pricing empty for '{store_key}' — falling back to Instacart.", flush=True)
            except Exception as e:
                print(f"[Walmart] Direct pricing failed ({e}) — falling back to Instacart.", flush=True)

        # Costco: prices are near-uniform nationally, so when the local warehouse
        # isn't on Instacart Same-Day we price at the nearest covered Costco and
        # flag the line as an estimate (instead of dropping Costco entirely).
        if "costco" in store_key.lower():
            try:
                _, _, cc_prices, cc_meta = instacart_pricing.price_all_costco(
                    to_buy_quantities, lat, lon
                )
                if cc_prices:
                    tag = " (estimate)" if cc_meta.get("is_estimate") else ""
                    print(f"[IC:costco] Applying real prices to '{store_key}'{tag}", flush=True)
                    for ing_name, result in cc_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            brand = result.get("brand", "")
                            product_details[(store_key, key)] = {
                                "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    if cc_meta.get("is_estimate"):
                        costco_estimates[store_key] = {
                            "distance_km": cc_meta.get("distance_km"),
                            "store": cc_meta.get("store", ""),
                        }
            except Exception as e:
                print(f"[IC:costco] Pricing failed ({e}), store will be excluded.", flush=True)
            continue

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
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            brand = result.get("brand", "")
                            product_details[(store_key, key)] = {
                                "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
            except Exception as e:
                print(f"[IC:{slug}] Pricing failed ({e}), store will be excluded.", flush=True)

    # Drop any store that real pricing couldn't cover — no synthetic fallback.
    unpriced = [k for k in list(price_database.keys()) if k not in real_priced_keys]
    for k in unpriced:
        print(f"[Pricing] No real prices for '{k}' — excluding from optimization.", flush=True)
        del price_database[k]

    if not price_database:
        raise HTTPException(status_code=503, detail="No stores with real pricing found in your area.")

    # Filter location_names and durations_matrix to only the priced stores.
    priced_set = set(price_database.keys())
    keep_indices = [i for i, name in enumerate(location_names) if name == "Start" or name in priced_set]
    location_names = [location_names[i] for i in keep_indices]
    durations_matrix = [[durations_matrix[r][c] for c in keep_indices] for r in keep_indices]

    # Step 7b: Overlay coupon prices on top of scraped prices.
    # Coupon prices replace scraped prices when matched.
    postal = instacart_pricing._get_postal(lat, lon)
    coupon_sources: dict[str, dict[str, str]] = {}
    if postal:
        try:
            from coupon_scraper import fetch_and_store
            fetch_and_store(postal)
        except Exception as e:
            print(f"[Coupon] Fetch/store failed ({e}), using existing data.", flush=True)
        for sk in list(price_database.keys()):
            sources = _overlay_coupon_prices(sk, price_database, postal, to_buy_quantities)
            if sources:
                coupon_sources[sk] = sources

    config.MAX_TIME_SECONDS = MAX_TIME_SECS
    optimal_route, item_cost, total_time_seconds, item_assignments, cheapest_single_store_cost, cheapest_single_store_name = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    # Debug: print full item assignments so we can spot duplicates across stores
    print("[Optimizer] Item assignments per store:", flush=True)
    for s_key, s_items in item_assignments.items():
        print(f"  {s_key}: {[i['name'] for i in s_items]}", flush=True)

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
                detail = product_details.get((store, lookup_key))
                if detail:
                    item_entry["product_name"] = detail["product_name"]
                    item_entry["size_str"] = detail["size_str"]
                    item_entry["units_to_buy"] = detail["units_to_buy"]

                store_items.append(item_entry)
            
            store_entry = {
                "store": store,
                "address": STORE_ADDRESSES.get(store, ""),
                "coordinates": {"lat": STORE_LOCATIONS[store][0], "lng": STORE_LOCATIONS[store][1]},
                "items": store_items
            }
            # Costco priced via the nearest-covered-warehouse proxy: flag as an
            # estimate so the UI can label it (Costco pricing is ~national).
            est = costco_estimates.get(store)
            if est:
                km = est.get("distance_km")
                store_entry["estimated"] = True
                store_entry["pricing_note"] = (
                    "Estimated — local Costco isn't on Instacart, so prices are from the "
                    f"nearest covered Costco (~{int(km)} km away). Costco prices are ~national."
                    if km else "Estimated from the nearest covered Costco."
                )
            formatted_shopping_list.append(store_entry)

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
    }

    # Persist to Supabase if user is authenticated
    _save_results(
        user_id=user_id, prefs=prefs, meal_plan=meal_plan,
        shopping_list=formatted_shopping_list, route=optimal_route or [],
        total_cost=res["total_cost"],
        cheapest_store_name=cheapest_single_store_name or "",
        cheapest_store_cost=cheapest_single_store_cost or 0,
        total_time_minutes=res["total_time_minutes"],
    )

    print(f"DEBUG SERVER: Sending benchmark {cheapest_single_store_name} to frontend", flush=True)
    return res

@router.post("/price_list")
def price_list(request: PriceListRequest, user_id: Optional[str] = Depends(get_current_user)):
    print(f"\nRECEIVED PRICE LIST REQUEST (Server v{SERVER_VERSION})", flush=True)
    prefs = request

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

    # 2. Build to_buy_quantities from the items list
    to_buy_quantities = {}
    for item in prefs.items:
        to_buy_quantities[item.name] = {"qty": item.qty, "unit": item.unit}

    # 3. Find Stores & Optimize (same logic as generate_plan)
    sh_hours = prefs.shopping_time_hours
    if sh_hours > 12:
        sh_hours = sh_hours / 60.0
    MAX_TIME_SECS = sh_hours * 3600
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(user_loc, ONE_WAY_TIME_SECONDS)
    if not isochrone_geometry:
        print("[Server] ORS isochrone failed — using 15 km bounding-box fallback.", flush=True)
        lat0, lon0 = user_loc
        D = 0.135
        isochrone_geometry = {
            "type": "Polygon",
            "coordinates": [[
                [lon0 - D, lat0 - D], [lon0 + D, lat0 - D],
                [lon0 + D, lat0 + D], [lon0 - D, lat0 + D],
                [lon0 - D, lat0 - D],
            ]]
        }

    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, user_loc)
    if not prefs.has_costco_card:
        STORE_LOCATIONS = {k: v for k, v in STORE_LOCATIONS.items() if "costco" not in k.lower()}
        STORE_ADDRESSES = {k: STORE_ADDRESSES[k] for k in STORE_LOCATIONS if k in STORE_ADDRESSES}

    STORE_LOCATIONS_RAW, STORE_ADDRESSES_RAW = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, user_loc)
    STORE_LOCATIONS = {k.strip(): v for k, v in STORE_LOCATIONS_RAW.items()}
    STORE_ADDRESSES = {k.strip(): v for k, v in STORE_ADDRESSES_RAW.items()}

    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = [( (lat - user_loc[0])**2 + (lon - user_loc[1])**2, name, (lat, lon) ) for name, (lat, lon) in STORE_LOCATIONS.items()]
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
        STORE_ADDRESSES = {name: STORE_ADDRESSES[name] for name in STORE_LOCATIONS}

    all_coords = [user_loc] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)

    # 4. Price each store (same coupon-first pipeline)
    lat, lon = user_loc
    price_database: dict = {k.strip(): {} for k in STORE_LOCATIONS.keys()}
    real_priced_keys: set = set()
    product_details: dict = {}
    costco_estimates: dict = {}

    shopping_list = [
        {"name": name, "qty": float(data.get("qty", 1) or 1)}
        for name, data in to_buy_quantities.items()
    ]

    # --- Kroger ---
    kroger_key = next((k for k in price_database if is_kroger_banner(k)), None)
    if kroger_key:
        try:
            _, _, kroger_prices = asyncio.run(kroger_async.price_all_async(to_buy_quantities, lat, lon))
        except Exception as e:
            kroger_prices = {}
        if kroger_prices:
            for ing_name, result in kroger_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                key = ing_name.lower().strip()
                price_database[kroger_key][key] = total_cost / qty
                if result.get("description"):
                    product_details[(kroger_key, key)] = {
                        "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                        "size_str": result.get("size_str", ""),
                        "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                    }
            real_priced_keys.add(kroger_key)

    # --- ALDI, Meijer, Walmart, Target, Trader Joe's, Costco, Instacart fallback ---
    # (same blocks as generate_plan but without the King Soopers King Soopers fallback)
    for store_key in list(price_database.keys()):
        if store_key in real_priced_keys:
            continue
        if is_kroger_banner(store_key):
            continue
        if is_aldi_store(store_key):
            try:
                _, _, aldi_prices = price_all_aldi(to_buy_quantities, lat, lon)
            except Exception:
                aldi_prices = {}
            if aldi_prices:
                for ing_name, result in aldi_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty if qty else total_cost
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_meijer_store(store_key):
            try:
                _, _, meijer_prices = meijer_pricing.price_all_meijer(to_buy_quantities, lat, lon)
            except Exception:
                meijer_prices = {}
            if meijer_prices:
                for ing_name, result in meijer_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_trader_joes_store(store_key):
            try:
                _, tj_prices = trader_joes_pricing.price_all_tj(to_buy_quantities)
            except Exception:
                tj_prices = {}
            if tj_prices:
                for ing_name, result in tj_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_target_store(store_key):
            try:
                _, _, tg_prices = target_pricing.price_all_target(to_buy_quantities, lat, lon)
                if tg_prices:
                    for ing_name, result in tg_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
            except Exception:
                pass
        if is_walmart_store(store_key):
            try:
                _, _, wm_prices = walmart_pricing.price_all_walmart(to_buy_quantities, lat, lon)
                if wm_prices:
                    for ing_name, result in wm_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
            except Exception:
                pass
        if "costco" in store_key.lower():
            try:
                _, _, cc_prices, cc_meta = instacart_pricing.price_all_costco(to_buy_quantities, lat, lon)
                if cc_prices:
                    for ing_name, result in cc_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    if cc_meta.get("is_estimate"):
                        costco_estimates[store_key] = {
                            "distance_km": cc_meta.get("distance_km"),
                            "store": cc_meta.get("store", ""),
                        }
            except Exception:
                pass
            continue
        slug = get_instacart_slug(store_key)
        if slug:
            try:
                _, _, ic_prices = instacart_pricing.price_all_instacart(to_buy_quantities, lat, lon, slug)
                if ic_prices:
                    for ing_name, result in ic_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
            except Exception:
                pass

    unpriced = [k for k in list(price_database.keys()) if k not in real_priced_keys]
    for k in unpriced:
        del price_database[k]
    if not price_database:
        raise HTTPException(status_code=503, detail="No stores with real pricing found in your area.")

    priced_set = set(price_database.keys())
    keep_indices = [i for i, n in enumerate(location_names) if n == "Start" or n in priced_set]
    location_names = [location_names[i] for i in keep_indices]
    durations_matrix = [[durations_matrix[r][c] for c in keep_indices] for r in keep_indices]

    # Coupon overlay
    postal = instacart_pricing._get_postal(lat, lon)
    if postal:
        try:
            from coupon_scraper import fetch_and_store
            fetch_and_store(postal)
        except Exception:
            pass
        for sk in list(price_database.keys()):
            _overlay_coupon_prices(sk, price_database, postal, to_buy_quantities)

    config.MAX_TIME_SECONDS = MAX_TIME_SECS
    optimal_route, item_cost, total_time_seconds, item_assignments, cheapest_single_store_cost, cheapest_single_store_name = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )

    formatted_shopping_list = []
    if optimal_route:
        for store_raw in optimal_route:
            store = store_raw.strip()
            if store == "Start":
                continue
            items = item_assignments.get(store_raw, [])
            store_items = []
            for item_data in items:
                item_name = item_data["name"]
                item_qty = item_data["qty"]
                lookup_key = item_name.lower().strip()
                store_prices = price_database.get(store, {})
                unit_price = store_prices.get(lookup_key, 0.0)
                total_item_price = unit_price * item_qty
                item_entry = {"name": item_name, "qty": item_qty, "price": total_item_price}
                detail = product_details.get((store, lookup_key))
                if detail:
                    item_entry["product_name"] = detail["product_name"]
                    item_entry["size_str"] = detail["size_str"]
                    item_entry["units_to_buy"] = detail["units_to_buy"]
                store_items.append(item_entry)
            store_entry = {
                "store": store,
                "address": STORE_ADDRESSES.get(store, ""),
                "coordinates": {"lat": STORE_LOCATIONS[store][0], "lng": STORE_LOCATIONS[store][1]},
                "items": store_items,
            }
            est = costco_estimates.get(store)
            if est:
                km = est.get("distance_km")
                store_entry["estimated"] = True
                store_entry["pricing_note"] = (
                    f"Estimated — local Costco isn't on Instacart, so prices are from the "
                    f"nearest covered Costco (~{int(km)} km away). Costco prices are ~national."
                    if km else "Estimated from the nearest covered Costco."
                )
            formatted_shopping_list.append(store_entry)

    res = {
        "shopping_list": formatted_shopping_list,
        "total_cost": item_cost if item_cost != float('inf') else 0,
        "cheapest_single_store_cost": cheapest_single_store_cost if cheapest_single_store_cost != float('inf') else 0,
        "cheapest_single_store_name": cheapest_single_store_name,
        "total_time_minutes": total_time_seconds / 60 if total_time_seconds else 0,
        "route": optimal_route if optimal_route else [],
        "user_location": {"lat": user_loc[0], "lng": user_loc[1]},
    }
    return res


@router.post("/optimize_shopping")
def optimize_shopping_route(data: Dict):
    return {"message": "Optimization endpoint not fully implemented yet"}

app.include_router(router)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)