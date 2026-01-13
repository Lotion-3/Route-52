
import sys
import config
import data_loader
import meal_planner
import geo_utils
import price_manager
import optimizer

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("=" * 60)
    print("MEAL PLANNER & GROCERY OPTIMIZER")
    print("=" * 60)
    print(f"Location: {config.USER_START_LOCATION}")
    print(f"Shopping time available: {config.SHOPPING_TIME_HOURS} hours")
    print(f"Nutrition target: {config.DAILY_CALORIE_TARGET:,} calories/day")
    print("=" * 60)
    
    # Step 1: Load available vegetables
    available_veggies = data_loader.load_available_vegetables()
    if not available_veggies:
        print("FATAL: No vegetables available for meal planning.")
        sys.exit(1)
    
    # Step 2: Load and filter recipes
    all_recipes = data_loader.load_recipes()
    filtered_recipes = meal_planner.filter_recipes_by_available_vegetables(all_recipes, available_veggies)
    
    if not filtered_recipes:
        print("FATAL: No recipes available with the current vegetables.")
        sys.exit(1)
    
    # Step 3: Create weekly meal plan
    meal_plan, ingredient_quantities = meal_planner.create_weekly_meal_plan(filtered_recipes, available_veggies)
    
    if not meal_plan:
        print("FATAL: Could not create meal plan.")
        sys.exit(1)
    
    # Display meal plan
    print("\n" + "=" * 60)
    print("WEEKLY MEAL PLAN")
    print("=" * 60)
    for meal in meal_plan:
        print(f"{meal['day']} - {meal['meal_type']}:")
        print(f"  Recipe: {meal['recipe']}")
        print(f"  Calories: {meal['calories']:.0f}, Protein: {meal['protein']:.1f}g")
        print(f"  Ingredients: {', '.join(meal['ingredients'][:3])}...")
        print()
    
    print("\n" + "=" * 60)
    print("INGREDIENTS NEEDED")
    print("=" * 60)
    for veggie, quantity in ingredient_quantities.items():
        print(f"  {veggie.title()}: {quantity} units")
    
    # Step 4: Calculate reachable area
    ONE_WAY_TIME_SECONDS = int(config.MAX_TIME_SECONDS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(config.USER_START_LOCATION, ONE_WAY_TIME_SECONDS)
    
    if not isochrone_geometry:
        print("FATAL: Could not calculate reachable area.")
        sys.exit(1)
    
    bbox = geo_utils.get_geojson_bounding_box(isochrone_geometry)
    
    # Step 5: Find stores
    STORE_LOCATIONS = geo_utils.find_eligible_stores_overpass(bbox)
    
    if not STORE_LOCATIONS:
        print("FATAL: No stores found in reachable area.")
        sys.exit(1)
    
    # Filter stores if needed
    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        print(f"Filtering stores to {config.MAX_STORES_TO_USE} closest...")
        distances = []
        start_lat, start_lon = config.USER_START_LOCATION
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - start_lat)**2 + (lon - start_lon)**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
    
    print(f"\nStores for optimization: {len(STORE_LOCATIONS)}")
    
    # Step 6: Get travel times
    all_coords = [config.USER_START_LOCATION] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    
    print("\nGetting travel times...")
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    
    if not matrix_response:
        print("FATAL: Could not get travel times.")
        sys.exit(1)
    
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    if not durations_matrix:
        print("FATAL: No travel time data.")
        sys.exit(1)
    
    # Step 7: Get prices
    price_database, removed_items, shopping_list = price_manager.fetch_grocery_prices(
        ingredient_quantities, list(STORE_LOCATIONS.keys())
    )
    
    if not price_database or not shopping_list:
        print("FATAL: Could not generate prices.")
        sys.exit(1)
    
    # Step 8: Optimize shopping
    print("\n" + "=" * 60)
    print("OPTIMIZING GROCERY SHOPPING")
    print("=" * 60)
    
    optimal_route, item_cost, total_time_seconds = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list
    )
    
    # Display results
    print("\n" + "=" * 60)
    print("OPTIMAL SHOPPING PLAN")
    print("=" * 60)
    
    if optimal_route:
        print(f"✅ Recommended Route: Start → {' → '.join(optimal_route)} → Home")
        print(f"💰 Estimated Cost: ${item_cost:.2f}")
        print(f"⏱️  Total Time: {int(total_time_seconds/60)}m {int(total_time_seconds%60)}s")
        
        # Show what to buy where
        print(f"\n📋 Shopping List Breakdown:")
        for item_data in shopping_list:
            item_name = item_data["name"]
            quantity = item_data["qty"]
            best_price = float('inf')
            best_store = None
            
            for store in optimal_route:
                price = price_database[store].get(item_name, float('inf'))
                if price < best_price:
                    best_price = price
                    best_store = store
            
            if best_store:
                print(f"  {quantity} × {item_name.title()}: ${best_price:.2f} each at {best_store}")
    else:
        print("❌ No feasible shopping route found within time constraint.")
        print("Try increasing your shopping time or reducing the number of ingredients.")
    
    print("=" * 60)
