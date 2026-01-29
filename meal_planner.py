import os
from typing import List, Dict, Tuple, Any
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# --- UPDATED SCHEMAS ---

class ShoppingItem(BaseModel):
    item_name: str = Field(description="Core name (e.g., 'banana')")
    search_query: str = Field(description="Retail search string (e.g., 'fresh bananas')")
    recipe_quantity: float
    recipe_unit: str
    purchase_strategy: str = Field(description="'weighted' or 'unit'")

class Meal(BaseModel):
    day: str
    meal_type: str 
    recipe_name: str
    calories: int
    cook_time: str = Field(description="Estimated time to cook, e.g., '25 mins'") # Added this back
    ingredients: List[str]

class MealPlanResponse(BaseModel):
    meals: List[Meal]
    shopping_list: List[ShoppingItem]

# --- REIMPLEMENTED FUNCTION ---

def create_weekly_meal_plan(
    days: int, 
    meals_per_day: int, 
    daily_calories: int,
    diet_restrictions: str = "",
    cuisines: str = "",
    experiment: bool = True,
    cook_time_pref: str = "30-45 mins" # User preference argument
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_V"))
    
    # Updated prompt to explicitly mention cook_time for each meal
    prompt = (
        f"Create a {days}-day meal plan ({meals_per_day} meals/day) at {daily_calories} kcal/day. "
        f"Restrictions: {diet_restrictions}. Cuisines: {cuisines}. "
        f"Target cook time per meal: {cook_time_pref}. "
        "For each meal, you MUST provide an estimated 'cook_time' string."
        "\nSHOPPING LIST RULES:"
        "\n1. For produce/meat, use 'weighted' strategy and 'lb' or 'each' units."
        "\n2. For pantry items, use 'unit' strategy and provide a retail search_query."
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
        
        parsed = response.parsed
        
        # Format Meal Plan with cook_time included
        meal_plan = []
        for m in parsed.meals:
            meal_plan.append({
                'day': m.day,
                'meal_type': m.meal_type,
                'recipe': m.recipe_name,
                'calories': m.calories,
                'cook_time': m.cook_time, # Now flows to your main app
                'ingredients': m.ingredients
            })
            
        ingredient_data = {}
        for item in parsed.shopping_list:
            name = item.item_name.lower().strip()
            ingredient_data[name] = {
                "qty": item.recipe_quantity,
                "unit": item.recipe_unit,
                "query": item.search_query,
                "strategy": item.purchase_strategy
            }
                
        return meal_plan, ingredient_data

    except Exception as e:
        print(f"❌ Error: {e}")
        return [], {}