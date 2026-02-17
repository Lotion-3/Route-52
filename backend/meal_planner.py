import os
import logging
import traceback
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
    is_at_home: bool = Field(description="True if this item is already in the user's fridge/home")

class MealIngredient(BaseModel):
    name: str = Field(description="Core name of the ingredient (e.g., 'chicken breast')")
    qty: float
    unit: str
    is_at_home: bool = Field(description="Set to true if this ingredient matches something in the User's fridge list")
    search_query: str = Field(description="A retail search string for this ingredient (e.g., 'fresh boneless chicken breast')")
    purchase_strategy: str = Field(description="'weighted' or 'unit' based on how it's typically sold")

class Meal(BaseModel):
    day: str
    meal_type: str = Field(description="Breakfast, Lunch, or Dinner")
    name: str
    calories: int
    cook_time: str = Field(description="Estimated time to cook, e.g., '25 mins'")
    ingredients: List[MealIngredient]
    instructions: List[str]

class MealPlanResponse(BaseModel):
    meals: List[Meal]
    shopping_list: List[ShoppingItem]

# --- STEP 1 SCHEMAS ---

class MealBrief(BaseModel):
    day: str
    meal_type: str
    name: str

class MealBriefList(BaseModel):
    meals: List[MealBrief]

# --- REIMPLEMENTED FUNCTION ---

# --- DAY-BY-DAY SCHEMAS ---

class DailyMealPlan(BaseModel):
    meals: List[Meal]

def create_weekly_meal_plan(
    days: int, 
    meals_per_day: int, 
    daily_calories: int,
    diet_restrictions: str = "",
    cuisines: str = "",
    fridge_contents: str = "",
    experiment: bool = True,
    cook_time: str = "30-45 mins"
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Generates a meal plan using Google Gemini.
    Returns:
      1. meal_plan: List of dictionaries (compatible with main.py structure)
      2. ingredient_data: Dictionary {ingredient_name: details}
    """
    print("\n" + "-"*50)
    print("🤖 ASKING GEMINI FOR A CUSTOM MEAL PLAN...")
    print(f"   Target: {days} days, {meals_per_day} meals/day")
    print(f"   Calories: {daily_calories} kcal/day")
    if diet_restrictions: print(f"   Diet: {diet_restrictions}")
    if cuisines: print(f"   Cuisines: {cuisines}")
    if fridge_contents: print(f"   Fridge Contents: {fridge_contents}")
    print("-"*50)

    api_key = os.environ.get("GEMINI_API_KEY_V")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY_V not found in environment.")
        return [], {}

    client = genai.Client(api_key=api_key)
    
    # --- STEP 1: GENERATE MEAL NAMES ---
    prompt_step1 = (
        f"Generate a {days}-day meal plan ({meals_per_day} meals/day) at {daily_calories} total kcal/day. "
        f"Dietary Restrictions: {diet_restrictions}. Cuisines: {cuisines}. "
        f"The user has: {fridge_contents}. Use these if possible.\n"
        "Just provide the meal names for each day and type."
    )

    try:
        response1 = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_step1,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MealBriefList,
            )
        )
        brief_plan = response1.parsed
        if not brief_plan or not brief_plan.meals:
            print("❌ STEP 1 FAILED: No meal briefs generated.")
            return [], {}
        
        # Group meals by day to process day-by-day
        meals_by_day = {}
        for m in brief_plan.meals:
            if m.day not in meals_by_day:
                meals_by_day[m.day] = []
            meals_by_day[m.day].append(m)

        final_meals = []
        aggregated_ingredients = {} # name -> {qty, unit, is_at_home}

        # --- STEP 2: GENERATE DETAILS DAY-BY-DAY ---
        for day, meals in meals_by_day.items():
            print(f"📅 Expanding recipes for {day}...")
            meal_list_str = "\n".join([f"- {m.meal_type}: {m.name}" for m in meals])
            
            prompt_day = (
                f"Detailed recipe expansion for {day}:\n{meal_list_str}\n\n"
                f"For EACH meal listed, provide:\n"
                f"1. 'day' (use '{day}') and 'meal_type' (exactly as listed above)\n"
                f"2. 'name' (exactly as provided above)\n"
                f"3. 'calories' (integer)\n"
                f"4. 'cook_time' (string, e.g. '20 mins')\n"
                f"5. 'ingredients' (list of objects with 'name', 'qty', 'unit', 'is_at_home', 'search_query', 'purchase_strategy')\n"
                f"6. 'instructions' (list of strings)\n\n"
                f"Rules for ingredients (CRITICAL):\n"
                f"- 'is_at_home': Check if an ingredient is EXPLICITLY in this fridge list: {fridge_contents}. Set to true if found.\n"
                f"- 'search_query': Provide a retail search string (e.g., 'organic baby spinach').\n"
                f"- 'purchase_strategy': 'weighted' for things like produce/meat by lb, 'unit' for discrete items like cans/cartons.\n"
            )

            try:
                response_day = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt_day,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DailyMealPlan,
                        max_output_tokens=4096,
                    )
                )
                
                day_plan = response_day.parsed
                if not day_plan:
                    print(f"⚠️ Warning: Failed to expand recipes for {day}. Skipping.")
                    continue

                for m in day_plan.meals:
                    meal_dict = {
                        'day': m.day,
                        'meal_type': m.meal_type,
                        'name': m.name,
                        'calories': m.calories,
                        'cook_time': m.cook_time,
                        'ingredients': [
                            {
                                'name': ing.name, 
                                'qty': ing.qty, 
                                'unit': ing.unit,
                                'is_at_home': ing.is_at_home,
                                'search_query': ing.search_query,
                                'purchase_strategy': ing.purchase_strategy
                            } 
                            for ing in m.ingredients
                        ],
                        'instructions': m.instructions
                    }
                    final_meals.append(meal_dict)
                    
                    # Track ingredients for aggregation (Manual Code-side sum)
                    for ing in m.ingredients:
                        name_lower = ing.name.lower().strip()
                        if name_lower not in aggregated_ingredients:
                            aggregated_ingredients[name_lower] = {
                                "qty": 0.0,
                                "unit": ing.unit,
                                "is_at_home": ing.is_at_home,
                                "query": ing.search_query,
                                "strategy": ing.purchase_strategy
                            }
                        
                        # Add quantity. Note: In a production app, we'd handle unit conversions here (e.g. g to oz).
                        # For now, we assume Gemini is consistent per-session or we use the first unit found.
                        aggregated_ingredients[name_lower]["qty"] += ing.qty
            
            except Exception as day_err:
                print(f"❌ Error expanding {day}: {day_err}")
                continue

        if not final_meals:
            print("❌ FAILED: No detailed recipes were generated.")
            return [], {}

        # --- STEP 3: CLEANUP & RETURN ---
        # No more AI call here. ingredient_data is built from recipes.
        print(f"🛒 Aggregated {len(aggregated_ingredients)} unique ingredients from recipes.")
        
        print("✅ Meal plan implementation complete.")
        return final_meals, aggregated_ingredients

    except Exception as e:
        err = f"❌ Error in create_weekly_meal_plan: {e}\n{traceback.format_exc()}"
        print(err)
        logging.error(err)
        return [], {}
