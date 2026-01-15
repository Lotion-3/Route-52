import sys
import config
import data_loader
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
    # 3. Calorie Input
    try:
        dev_input = input("Fake data(1) or Real data(0)").strip()
        dev_mode = int(dev_input) if dev_input else 1
    except ValueError:
        print("Invalid format. Using 2000 kcal.")
        dev_mode = 1
        
    return user_loc, shop_hours, cal_target, dev_mode

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Get Dynamic Inputs from Address
    USER_LOC, SHOP_HOURS, CAL_TARGET, DEV_MODE = get_user_inputs()
    MAX_TIME_SECS = SHOP_HOURS * 3600

    print("\n" + "=" * 60)
    print("INITIALIZING PLANNER")
    print("=" * 60)
    print(f"Start Point: {USER_LOC}")
    print(f"Budgeted Time: {SHOP_HOURS} hours")
    print(f"Daily Calories: {CAL_TARGET}")
    print("=" * 60)
    
    # Step 1: Load available vegetables
    available_veggies = data_loader.load_available_vegetables()
    
    # Step 2: Load and filter recipes
    all_recipes = data_loader.load_recipes()
    filtered_recipes = meal_planner.filter_recipes_by_available_vegetables(all_recipes, available_veggies)
    
    # Step 3: Create weekly meal plan
    meal_plan, ingredient_quantities = meal_planner.create_weekly_meal_plan(filtered_recipes, available_veggies)
    
    # Step 4: Calculate reachable area
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(USER_LOC, ONE_WAY_TIME_SECONDS)
    bbox = geo_utils.get_geojson_bounding_box(isochrone_geometry)
    
    # Step 5: Find stores
    # bbox is no longer strictly needed for google places search, but we use the user location as center
    STORE_LOCATIONS = geo_utils.find_eligible_stores_google(isochrone_geometry, USER_LOC)
    
    # Filter to closest stores
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
    
    # Step 7: Get prices via Gemini Grounding
    if (DEV_MODE):
        price_path = price_managerOG
    else:
        price_path = price_manager
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
        print("❌ No route found. Try increasing shopping time or simplifying the list.")