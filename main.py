import sys
import config

import meal_planner
import geo_utils
import price_manager
import price_managerOG
import optimizer
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

def get_user_inputs():
    print("=" * 60)
    print("USER PREFERENCES SETUP")
    print("=" * 60)
    
    # 1. Address to Coordinate Conversion
    geolocator = Nominatim(user_agent="basket_buddy_planner")
    user_loc = None
    
    while user_loc is None:
        address = input("Enter your Address (e.g., 100 Monument Circle, Indianapolis, IN): ").strip()
        if not address:
            print("Using default coordinates (Indianapolis).")
            user_loc = (40.0033, -86.1366)
            break
            
        try:
            print(f"🌍 Locating '{address}'...")
            location = geolocator.geocode(address)
            if location:
                user_loc = (location.latitude, location.longitude)
                print(f"✅ Found: {location.address}")
                print(f"📍 Coordinates: {user_loc}")
            else:
                print("❌ Address not found. Please try being more specific (include City/State).")
        except GeocoderTimedOut:
            print("⏳ Service timed out. Please try again.")

    # 2. Shopping Time Input
    try:
        time_input = input("\nShopping time available in hours (default 3): ").strip()
        shop_hours = float(time_input) if time_input else 3.0
    except ValueError:
        print("Invalid format. Using 3.0 hours.")
        shop_hours = 3.0

    # 3. Calorie Input
    try:
        cal_input = input("Daily calorie target (default 2000): ").strip()
        cal_target = int(cal_input) if cal_input else 2000
    except ValueError:
        print("Invalid format. Using 2000 kcal.")
        cal_target = 2000
    
    # 4. Developer mode or gemini
    try:
        dev_input = input("Fake data(1) or Real data(0): ").strip()
        dev_mode = int(dev_input) if dev_input else 1
    except ValueError:
        print("Invalid format. Using fake data mode.")
        dev_mode = 1
    
    # 5. Meal Plan Duration
    try:
        days_input = input("Number of days for meal plan (default 7): ").strip()
        days_plan = int(days_input) if days_input else 7
    except ValueError:
        print("Invalid format. Using 7 days.")
        days_plan = 7

    # 6. Meals Per Day
    try:
        meals_input = input("Meals per day (default 3): ").strip()
        meals_per_day = int(meals_input) if meals_input else 3
    except ValueError:
        print("Invalid format. Using 3 meals.")
        meals_per_day = 3
        
    return user_loc, shop_hours, cal_target, dev_mode, days_plan, meals_per_day


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Get Dynamic Inputs
    USER_LOC, SHOP_HOURS, CAL_TARGET, DEV_MODE, DAYS_PLAN, MEALS_PER_DAY = get_user_inputs()
    MAX_TIME_SECS = SHOP_HOURS * 3600

    # Update config values dynamically based on user input
    config.TOTAL_WEEKLY_CALORIES = CAL_TARGET * DAYS_PLAN # Total for the plan duration

    print("\n" + "=" * 60)
    print("INITIALIZING CALORIE-FOCUSED PLANNER")
    print("=" * 60)
    print(f"Start Point: {USER_LOC}")
    print(f"Budgeted Time: {SHOP_HOURS} hours")
    print(f"Daily Calories: {CAL_TARGET}")
    print(f"Plan Duration: {DAYS_PLAN} days ({MEALS_PER_DAY} meals/day)")
    print("=" * 60)
    
    # Step 1: Create meal plan using Gemini (No longer loading CSVs)
    meal_plan, ingredient_quantities = meal_planner.create_weekly_meal_plan(
        DAYS_PLAN, MEALS_PER_DAY, CAL_TARGET
    )
    
    # Step 2: Skip filtering (Done by Gemini)
    
    # Step 3: Skip manual meal creation (Done by Gemini)
    
    # Step 4: Calculate reachable area
    if not ingredient_quantities:
        print("❌ Meal plan generation failed or returned no ingredients. Exiting.")
        sys.exit(0)
        
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(USER_LOC, ONE_WAY_TIME_SECONDS)
    
    # Step 5: Find stores
    STORE_LOCATIONS = geo_utils.find_eligible_stores_google(isochrone_geometry, USER_LOC)
    
    # Filter to closest stores if too many found
    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = []
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - USER_LOC[0])**2 + (lon - USER_LOC[1])**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
    
    # Step 6: Get travel times
    all_coords = [USER_LOC] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    
    # Step 7: Get prices
    price_path = price_managerOG if DEV_MODE else price_manager
        
    print("\n🔍 Searching for prices for all recipe ingredients...")
    price_database, removed_items, shopping_list = price_path.fetch_grocery_prices(
        ingredient_quantities, list(STORE_LOCATIONS.keys())
    )
    
    # Step 8: Optimize shopping
    config.MAX_TIME_SECONDS = MAX_TIME_SECS 
    
    optimal_route, item_cost, total_time_seconds = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    # Display results
    print("\n" + "=" * 60)
    print("OPTIMAL SHOPPING PLAN")
    print("=" * 60)
    
    if optimal_route:
        print(f"✅ Route: Start → {' → '.join(optimal_route)} → Home")
        print(f"💰 Cost: ${item_cost:.2f}")
        print(f"⏱️  Time: {int(total_time_seconds/60)}m {int(total_time_seconds%60)}s")
    else:
        print("❌ No route found within the time limit.")