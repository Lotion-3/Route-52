import os
from typing import List, Dict, Tuple, Any
from google import genai
from google.genai import types
from pydantic import BaseModel

# --- GEMINI SCHEMA DEFINITIONS ---

class IngredientItem(BaseModel):
    item_name: str
    quantity: int  # Simplified count for shopping

class Meal(BaseModel):
    day: str
    meal_type: str  # e.g., "Breakfast", "Lunch", "Dinner"
    recipe_name: str
    calories: int
    ingredients: List[str]

class MealPlanResponse(BaseModel):
    meals: List[Meal]
    shopping_list: List[IngredientItem]

# --- MAIN MEAL PLAN FUNCTION ---

def create_weekly_meal_plan(
    days: int, 
    meals_per_day: int, 
    daily_calories: int,
    diet_restrictions: str = "",
    cuisines: str = "",
    experiment: bool = True,
    cook_time: str = "30-45 mins"
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Generates a meal plan using Google Gemini.
    Returns:
      1. meal_plan: List of dictionaries (compatible with main.py structure)
      2. ingredient_quantities: Dictionary {ingredient_name: quantity}
    """
    print("\n" + "-"*50)
    print("🤖 ASKING GEMINI FOR A CUSTOM MEAL PLAN...")
    print(f"   Target: {days} days, {meals_per_day} meals/day")
    print(f"   Calories: {daily_calories} kcal/day")
    if diet_restrictions: print(f"   Diet: {diet_restrictions}")
    if cuisines: print(f"   Cuisines: {cuisines}")
    print("-"*50)

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_V"))
    
    experiment_text = "Yes, please provide variety and new dishes." if experiment else "No, stick to classic/simple recipes."

    prompt = (
        f"Please create a {days} day meal plan with {meals_per_day} meals a day, "
        f"strictly targeting {daily_calories} calories per day (+/- 10%). "
        f"Dietary Restrictions: {diet_restrictions if diet_restrictions else 'None'}. "
        f"Cuisine Preferences: {cuisines if cuisines else 'No specific preference'}. "
        f"Willingness to Experiment: {experiment_text} "
        f"Preferred Cooking Time per Meal: {cook_time}. "
        f"Provide a structured list of meals and a consolidated list of grocery items needed. "
        f"All items must be purchasable in a single standard US grocery trip. "
        f"CRITICAL RULES FOR SHOPPING LIST:"
        f"1. DO NOT group items (e.g. 'nuts (almonds, walnuts)' is BANNED). Pick ONE specific item (e.g. 'almonds')."
        f"2. Use singular names (e.g. 'apple' not 'apples')."
        f"3. Do not include brand off-brand names."
        f"4. Use as common ingredients as possible."
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MealPlanResponse,
            )
        )
        
        if not response.parsed:
            print("❌ Gemini failed to generate a structured response.")
            return [], {}
            
        print("✅ Gemini successfully generated the plan!")
        
        # --- Convert Pydantic Models to Dicts for Compatibility ---
        
        # 1. Process Meal Plan
        meal_plan = []
        for meal in response.parsed.meals:
            meal_plan.append({
                'day': meal.day,
                'meal_type': meal.meal_type,
                'recipe': meal.recipe_name,
                'calories': meal.calories,
                'ingredients': meal.ingredients
            })
            
        # 2. Process Shopping List
        ingredient_quantities = {}
        for item in response.parsed.shopping_list:
            # Flatten "item_name" to lowercase for price matching logic
            name = item.item_name.strip().lower()
            qty = item.quantity
            
            if name in ingredient_quantities:
                ingredient_quantities[name] += qty
            else:
                ingredient_quantities[name] = qty
                
        # Basic Validation Stats
        total_cals = sum(m['calories'] for m in meal_plan)
        avg_cal = total_cals / days if days > 0 else 0
        
        print(f"\nPlan Summary:")
        print(f"   Total Meals: {len(meal_plan)}")
        print(f"   Avg Calories/Day: {avg_cal:.0f}")
        print(f"   Shopping Items: {len(ingredient_quantities)}")
        
        return meal_plan, ingredient_quantities

    except Exception as e:
        print(f"❌ Error communicating with Gemini: {e}")
        return [], {}

