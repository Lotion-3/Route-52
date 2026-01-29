import sys
import config
import meal_planner
import fridge_manager
import geo_utils
import price_manager
import price_managerOG
import optimizer
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

def calculate_calories():
    print("\n" + "-" * 40)
    print("CALORIE CALCULATOR")
    print("-" * 40)
    try:
        weight_input = input("Current Weight (lbs): ").strip()
        if not weight_input: return 2000
        weight_lbs = float(weight_input)
        
        print("Height:")
        ft_input = input("  Feet: ").strip()
        in_input = input("  Inches: ").strip()
        height_ft = int(ft_input) if ft_input else 5
        height_in = int(in_input) if in_input else 9
        
        age_input = input("Age: ").strip()
        age = int(age_input) if age_input else 30
        
        gender = input("Gender (M/F): ").strip().upper()
        
        print("\nActivity Level:")
        print("1. Sedentary (little to no exercise)")
        print("2. Lightly Active (1-3 days/week)")
        print("3. Moderately Active (3-5 days/week)")
        print("4. Very Active (6-7 days/week)")
        act_input = input("Select (1-4) [default 2]: ").strip()
        tdee_multipliers = {'1': 1.2, '2': 1.375, '3': 1.55, '4': 1.725}
        multiplier = tdee_multipliers.get(act_input, 1.375)
        
        # Mifflin-St Jeor Equation
        weight_kg = weight_lbs * 0.453592
        height_cm = ((height_ft * 12) + height_in) * 2.54
        
        if gender == 'M':
            bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
        else:
            bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
            
        tdee = bmr * multiplier
        
        print(f"\nEstimated Maintenance Calories (TDEE): {int(tdee)}")
        print("Goal:")
        print("1. Lose Weight (-500 kcal)")
        print("2. Maintain")
        print("3. Gain Weight (+500 kcal)")
        goal_input = input("Select (1-3) [default 2]: ").strip()
        
        if goal_input == '1':
            target = tdee - 500
        elif goal_input == '3':
            target = tdee + 500
        else:
            target = tdee
            
        final_target = int(target)
        # Safety bounds
        if final_target < 1200: 
            print("⚠️  Calculated target is very low. Setting to minimum 1200.")
            final_target = 1200
            
        print(f"✅ Setting Daily Target to: {final_target} kcal")
        return final_target
        
    except ValueError:
        print("⚠️  Invalid input detected. Defaulting to 2000 kcal.")
        return 2000

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

    # 3. Calorie Input Strategy
    cal_target = 2000
    try:
        print("\n--- Calorie Goals ---")
        use_calc = input("Are you working toward a certain weight? (y/n): ").strip().lower()
        if use_calc == 'y' or use_calc == 'yes':
            cal_target = calculate_calories()
        else:
            cal_input = input("Daily calorie target (default 2000): ").strip()
            cal_target = int(cal_input) if cal_input else 2000
    except ValueError:
        print("Invalid format. Using 2000 kcal.")
        cal_target = 2000
        
    # --- Fridge Scan (New) ---
    print("\n--- Fridge Scanner ---")
    fridge_items = ""
    scan_input = input("Do you want to scan a picture of your fridge? (y/n): ").strip().lower()
    if scan_input in ['y', 'yes']:
        image_path = "fridge.jpeg"
        if image_path:
            fridge_items = fridge_manager.analyze_fridge_image(image_path)
            
    # --- New Questions for Meal Plan Context ---
    print("\n--- Meal Preferences ---")
    
    # dietary restrictions
    dietary_restrictions = input("Dietary restrictions (e.g., 'vegan, gluten-free, no peanuts' or Enter for None): ").strip()
    
    # preferred cuisines
    cuisines = input("Preferred cuisines (e.g., 'Italian, Mexican' or Enter for Any): ").strip()
    
    # willing to experiment
    exp_input = input("Are you willing to experiment with new recipes? (y/n) [default y]: ").strip().lower()
    experiment = False if exp_input in ['n', 'no'] else True
    
    # cooking time
    cook_time = input("How much time do you want to spend cooking per meal? (e.g. '30 mins', '1 hour'): ").strip()
    if not cook_time: cook_time = "30-45 minutes"
    
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
        
    return user_loc, shop_hours, cal_target, dev_mode, days_plan, meals_per_day, dietary_restrictions, cuisines, experiment, cook_time, fridge_items


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Get Dynamic Inputs
    USER_LOC, SHOP_HOURS, CAL_TARGET, DEV_MODE, DAYS_PLAN, MEALS_PER_DAY, DIET_RESTRICTIONS, CUISINES, EXPERIMENT, COOK_TIME, FRIDGE_ITEMS = get_user_inputs()
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
        DAYS_PLAN, MEALS_PER_DAY, CAL_TARGET,
        DIET_RESTRICTIONS, CUISINES, FRIDGE_ITEMS, EXPERIMENT, COOK_TIME
    )
    
    # Step 2: Skip filtering (Done by Gemini)
    
    # Step 3: Skip manual meal creation (Done by Gemini)
    
    # Step 3: Print the meal plan
    print("\n" + "=" * 60)
    print("GENERATED WEEKLY MEAL PLAN")
    print("=" * 60)
    
    current_day = ""
    for meal in meal_plan:
        if meal['day'] != current_day:
            current_day = meal['day']
            print(f"\n📅 {current_day.upper()}")
            print("-" * 30)
        
        print(f"   • {meal['meal_type']}: {meal['recipe']} ({meal['calories']} kcal)")
    
    print("=" * 60)
    
    # Step 4: Calculate reachable area
    if not ingredient_quantities:
        print("❌ Meal plan generation failed or returned no ingredients. Exiting.")
        sys.exit(0)
        
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(USER_LOC, ONE_WAY_TIME_SECONDS)
    
    # Step 5: Find stores
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, USER_LOC)
    
    # Deduplicate to unique chains
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, USER_LOC)
    
    # Filter to closest stores if too many found
    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = []
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - USER_LOC[0])**2 + (lon - USER_LOC[1])**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
        STORE_ADDRESSES = {name: STORE_ADDRESSES[name] for name in STORE_LOCATIONS}
    
    # Step 6: Get travel times
    all_coords = [USER_LOC] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    
    # Step 7: Get prices
    price_path = price_managerOG if DEV_MODE else price_manager
        
    print("\n🔍 Searching for prices for all recipe ingredients...")
    price_database, removed_items, shopping_list = price_path.fetch_grocery_prices(
        ingredient_quantities, list(STORE_LOCATIONS.keys()), STORE_ADDRESSES
    )
    
    # Step 8: Optimize shopping
    config.MAX_TIME_SECONDS = MAX_TIME_SECS 
    
    optimal_route, item_cost, total_time_seconds, item_assignments = optimizer.find_optimal_store(
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
        
        print("\n🛒 SHOPPING LIST BREAKDOWN:")
        for store in optimal_route:
            items = item_assignments.get(store, [])
            print(f"\n📍 {store} ({len(items)} items):")
            for item in items:
                print(f"   - {item}")
    else:
        print("❌ No route found within the time limit.")