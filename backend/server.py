import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware  # Added for CORS
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
import config
import meal_planner
import fridge_manager
import geo_utils
import price_manager
import price_managerOG
import data_manager
import optimizer
from geopy.geocoders import Nominatim

import logging
import traceback

# Setup logging
logging.basicConfig(filename='server_error.log', level=logging.ERROR)

app = FastAPI()

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
    days_plan: int = 7
    meals_per_day: int = 3
    dietary_restrictions: Optional[str] = None
    health_issues: Optional[str] = None
    cuisines: Optional[str] = None
    experiment: bool = True
    cook_time: str = "30-45 minutes"
    fridge_image_path: Optional[str] = None 
    fridge_items: Optional[str] = None
    dev_mode: int = 1

class PlanRequest(BaseModel):
    preferences: UserPreferences

@app.get("/")
def read_root():
    return {"message": "BasketBuddy Backend is running!"}

@app.post("/generate_plan")
def generate_plan(request: PlanRequest):
    prefs = request.preferences
    
    # 1. Geocode Address
    geolocator = Nominatim(user_agent="basket_buddy_backend")
    location = geolocator.geocode(prefs.address)
    
    if not location:
        raise HTTPException(status_code=400, detail="Address not found")
        
    user_loc = (location.latitude, location.longitude)
    
    # 2. Update Config
    config.TOTAL_WEEKLY_CALORIES = prefs.calorie_target * prefs.days_plan
    
    # 3. Handle Fridge Items
    fridge_items = prefs.fridge_items or ""
    if prefs.fridge_image_path and os.path.exists(prefs.fridge_image_path):
        vision_items = fridge_manager.analyze_fridge_image(prefs.fridge_image_path)
        if vision_items:
            fridge_items = f"{fridge_items}, {vision_items}"
    
    # 4. Generate Meal Plan
    print(f"\n📦 FINAL FRIDGE LIST FOR MEAL PLANNER: {repr(fridge_items)}", flush=True)
    meal_plan, ingredient_data = meal_planner.create_weekly_meal_plan(
        prefs.days_plan, prefs.meals_per_day, prefs.calorie_target,
        prefs.dietary_restrictions, prefs.cuisines, fridge_items, prefs.experiment, prefs.cook_time,
        prefs.health_issues, prefs.budget
    )
    
    if not ingredient_data:
        raise HTTPException(status_code=500, detail="Failed to generate meal plan")

    # Separate items to buy from items at home
    to_buy_quantities = {}
    at_home_ingredients = []
    
    for name, data in ingredient_data.items():
        if data.get("is_at_home"):
            at_home_ingredients.append({
                "name": name,
                "qty": data.get("qty"),
                "unit": data.get("unit")
            })
        else:
            to_buy_quantities[name] = data

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
        # Fallback: create a small circle or handle error
        raise HTTPException(status_code=500, detail="Could not calculate reachable area. Check API keys.")
    
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, user_loc)
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, user_loc)
    
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
    # The user requested dev_mode to always be 1
    prefs.dev_mode = 1 
    
    price_database, removed_items, shopping_list = data_manager.generate_synthetic_market(
        to_buy_quantities, list(STORE_LOCATIONS.keys())
    )
    
    config.MAX_TIME_SECONDS = MAX_TIME_SECS 
    optimal_route, item_cost, total_time_seconds, item_assignments = optimizer.find_optimal_store(
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
                store_items.append({"name": item_name, "qty": item_qty, "price": total_item_price})
            
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

    return {
        "meal_plan": meal_plan,
        "shopping_list": formatted_shopping_list,
        "at_home_ingredients": at_home_ingredients,
        "total_cost": item_cost if item_cost != float('inf') else 0,
        "total_time_minutes": total_time_seconds / 60 if total_time_seconds else 0,
        "route": optimal_route if optimal_route else [],
        "user_location": {"lat": user_loc[0], "lng": user_loc[1]}
    }

@app.post("/optimize_shopping")
def optimize_shopping_route(data: Dict):
    return {"message": "Optimization endpoint not fully implemented yet"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)