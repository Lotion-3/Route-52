
import random
from typing import List, Dict, Tuple, Any
import config

# --- FUNCTION: Filter Recipes by Available Vegetables ---
def filter_recipes_by_available_vegetables(recipes: List[Dict[str, Any]], available_veggies: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """
    Filter recipes to only include those that use available vegetables
    """
    print("Filtering recipes by available vegetables...")
    
    filtered_recipes = []
    
    for recipe in recipes:
        recipe_ingredients = recipe['ingredients']
        all_ingredients_available = True
        
        # Check each ingredient in the recipe
        for ingredient in recipe_ingredients:
            ingredient_lower = ingredient.lower()
            
            # Check if this ingredient (or a similar one) is in our available veggies
            ingredient_found = False
            
            # Direct match
            if ingredient_lower in available_veggies:
                ingredient_found = True
            else:
                # Check for partial matches (e.g., "chopped tomatoes" contains "tomatoes")
                for veggie in available_veggies.keys():
                    if veggie in ingredient_lower or ingredient_lower in veggie:
                        ingredient_found = True
                        break
            
            if not ingredient_found:
                all_ingredients_available = False
                break
        
        if all_ingredients_available:
            filtered_recipes.append(recipe)
    
    print(f"Found {len(filtered_recipes)} recipes using only available vegetables.")
    return filtered_recipes

# --- FUNCTION: Create Weekly Meal Plan ---
def create_weekly_meal_plan(filtered_recipes: List[Dict[str, Any]], available_veggies: Dict[str, List[str]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Create a week's worth of meals (21 meals) that meet nutritional targets
    Returns: (meal_plan, ingredient_quantities)
    """
    print("\n--- CREATING WEEKLY MEAL PLAN ---")
    print(f"Target: {config.TOTAL_MEALS} meals ({config.DAYS_PER_WEEK} days × {config.MEALS_PER_DAY} meals/day)")
    print(f"Total calories per week: {config.TOTAL_WEEKLY_CALORIES:,}")
    
    if not filtered_recipes:
        print("No recipes available for meal planning!")
        return [], {}
    
    # Calculate per-meal calorie target
    calories_per_meal = config.TOTAL_WEEKLY_CALORIES / config.TOTAL_MEALS
    print(f"Target calories per meal: {calories_per_meal:.0f}")
    
    # Group recipes by calorie ranges
    low_cal_recipes = []    # < 300 calories
    med_cal_recipes = []    # 300-600 calories
    high_cal_recipes = []   # > 600 calories
    
    for recipe in filtered_recipes:
        calories = recipe['nutrition']['calories']
        if calories < 300:
            low_cal_recipes.append(recipe)
        elif calories <= 600:
            med_cal_recipes.append(recipe)
        else:
            high_cal_recipes.append(recipe)
    
    print(f"Available recipes by calorie range:")
    print(f"  Low calorie (<300): {len(low_cal_recipes)} recipes")
    print(f"  Medium calorie (300-600): {len(med_cal_recipes)} recipes")
    print(f"  High calorie (>600): {len(high_cal_recipes)} recipes")
    
    # Create meal plan
    meal_plan = []
    ingredient_quantities: Dict[str, int] = {}
    
    # For variety, we'll aim for:
    # - 7 high-calorie meals (dinners)
    # - 7 medium-calorie meals (lunches)
    # - 7 low-calorie meals (breakfasts)
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    for day in days:
        # Breakfast (low calorie)
        if low_cal_recipes:
            breakfast = random.choice(low_cal_recipes)
            meal_plan.append({
                'day': day,
                'meal_type': 'Breakfast',
                'recipe': breakfast['name'],
                'recipe_id': breakfast['id'],
                'calories': breakfast['nutrition']['calories'],
                'protein': breakfast['nutrition']['protein'],
                'ingredients': breakfast['ingredients']
            })
            # Track ingredients
            for ingredient in breakfast['ingredients']:
                ingredient_lower = ingredient.lower()
                # Find matching vegetable
                for veggie in available_veggies.keys():
                    if veggie in ingredient_lower or ingredient_lower in veggie:
                        ingredient_quantities[veggie] = ingredient_quantities.get(veggie, 0) + 1
                        break
        
        # Lunch (medium calorie)
        if med_cal_recipes:
            lunch = random.choice(med_cal_recipes)
            meal_plan.append({
                'day': day,
                'meal_type': 'Lunch',
                'recipe': lunch['name'],
                'recipe_id': lunch['id'],
                'calories': lunch['nutrition']['calories'],
                'protein': lunch['nutrition']['protein'],
                'ingredients': lunch['ingredients']
            })
            # Track ingredients
            for ingredient in lunch['ingredients']:
                ingredient_lower = ingredient.lower()
                for veggie in available_veggies.keys():
                    if veggie in ingredient_lower or ingredient_lower in veggie:
                        ingredient_quantities[veggie] = ingredient_quantities.get(veggie, 0) + 1
                        break
        
        # Dinner (high calorie)
        if high_cal_recipes:
            dinner = random.choice(high_cal_recipes)
            meal_plan.append({
                'day': day,
                'meal_type': 'Dinner',
                'recipe': dinner['name'],
                'recipe_id': dinner['id'],
                'calories': dinner['nutrition']['calories'],
                'protein': dinner['nutrition']['protein'],
                'ingredients': dinner['ingredients']
            })
            # Track ingredients
            for ingredient in dinner['ingredients']:
                ingredient_lower = ingredient.lower()
                for veggie in available_veggies.keys():
                    if veggie in ingredient_lower or ingredient_lower in veggie:
                        ingredient_quantities[veggie] = ingredient_quantities.get(veggie, 0) + 1
                        break
    
    # Calculate total nutrition
    total_calories = sum(meal['calories'] for meal in meal_plan)
    total_protein = sum(meal['protein'] for meal in meal_plan)
    
    print(f"\nMeal Plan Created:")
    print(f"  Total meals: {len(meal_plan)}")
    print(f"  Total calories: {total_calories:.0f} ({total_calories/config.TOTAL_WEEKLY_CALORIES*100:.1f}% of target)")
    print(f"  Total protein: {total_protein:.1f}g")
    print(f"  Unique ingredients needed: {len(ingredient_quantities)}")
    
    return meal_plan, ingredient_quantities
