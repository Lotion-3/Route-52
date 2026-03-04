import os
import logging
import traceback
from typing import List, Dict, Tuple, Any
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# --- UPDATED SCHEMAS ---

# --- SCHEMAS FOR 3-PROMPT DESIGN ---

# Step 1: IngredientPool (Sourcing)
class IngredientInfo(BaseModel):
    name: str = Field(description="Exact name of the ingredient")
    qty: float = Field(description="Total quantity needed across ALL meals")
    unit: str = Field(description="Measurement unit (e.g., 'lbs', 'cups', 'units')")
    search_query: str = Field(description="A retail search string (only for items to buy)")
    purchase_strategy: str = Field(description="'weighted' or 'unit'")

class InitialIngredientStrategy(BaseModel):
    buy_list: List[IngredientInfo] = Field(description="List of ingredients the user needs to PURCHASE")
    home_list: List[IngredientInfo] = Field(description="List of ingredients the user ALREADY HAS. MUST use exact names from User Fridge.")

# Step 2: MealPlanStructure (Scheduling)
class MealIngredientMapping(BaseModel):
    name: str = Field(description="Exact name of the ingredient from the Step 1 Pool")
    qty: float = Field(description="Quantity used in this specific meal")
    unit: str = Field(description="Unit used in this specific meal")

class MealBrief(BaseModel):
    day: str
    meal_type: str = Field(description="Type of meal (e.g., Breakfast, Lunch, Dinner, Snack, Pre-workout, etc.)")
    name: str = Field(description="Full name of the recipe")
    ingredients: List[MealIngredientMapping] = Field(description="Ingredients mapped from the pool for this meal")

class MealPlanStructure(BaseModel):
    meals: List[MealBrief]

# Step 3: RecipeDetails (Instruction Generation)
class RecipeExecution(BaseModel):
    name: str = Field(description="Name of the recipe")
    calories: int
    cook_time: str = Field(description="e.g., '25 mins'")
    instructions: List[str]

class BatchRecipeExecution(BaseModel):
    recipes: List[RecipeExecution]

def create_weekly_meal_plan(
    days: int, 
    meals_per_day: int, 
    daily_calories: int,
    diet_restrictions: str = "",
    cuisines: str = "",
    fridge_contents: str = "",
    experiment: bool = True,
    cook_time: str = "30-45 mins",
    health_issues: str = "",
    budget: float = 150.0,
    household_size: int = 1
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    logging.basicConfig(filename='meal_planner_debug.log', level=logging.INFO, 
                        format='%(asctime)s - %(message)s', force=True)
    
    def log_step(msg):
        print(msg)
        logging.info(msg)

    log_step("\n" + "-"*50)
    log_step("🤖 3-PROMPT MEAL PLAN GENERATION STARTING...")
    log_step(f"   Budget: ${budget} | Health: {health_issues} | People: {household_size}")
    log_step(f"   Fridge: {fridge_contents if fridge_contents else 'Empty'}")
    log_step("-"*50)

    api_key = os.environ.get("GEMINI_API_KEY_V")
    if not api_key:
        log_step("❌ ERROR: GEMINI_API_KEY_V not found in environment.")
        return [], {}

    client = genai.Client(api_key=api_key)

    # --- PROMPT 1: INGREDIENT SOURCING STRATEGY ---
    prompt_step1 = (
        f"Step 1: Create a universal ingredient list for a {days}-day plan ({meals_per_day} meals/day) "
        f"for a household of {household_size} people.\n"
        f"TOTAL BUDGET: ${budget} for the 'buy_list'.\n"
        f"USER FRIDGE: {fridge_contents}.\n"
        f"HEALTH/DIET: {health_issues}, {diet_restrictions}.\n\n"
        "Requirements:\n"
        "1. List every unique ingredient needed for the week. SCALE QUANTITIES for {household_size} people.\n"
        "   - CLEAN NAMES: The 'name' field must ONLY contain the name of the food (e.g., 'bananas', 'milk').\n"
        "   - Do NOT include quantities, units, or '(x...)' in the name string itself.\n"
        "2. YIELD AWARENESS: Calculate quantities based on RETAIL UNITS (e.g., '1 bunch of bananas', '1 bag of spinach', '1 carton of milk').\n"
        "   - Do NOT suggest one unit per meal if one unit serves many (e.g., 1 bunch of bananas should last for multiple recipes).\n"
        "   - Calculate the total aggregate amount needed for the ENTIRE week first (multiplied by household size), then convert to retail units.\n"
        "3. FOR EACH ITEM, provide a realistic retail unit (e.g., 'bunch', 'bottle', 'lb', 'dozen', 'bag') and the minimum quantity of THAT unit required to cover the whole week.\n"
        "4. FOR FRIDGE ITEMS, USE THE EXACT LABELS PROVIDED BY THE USER.\n"
        "5. STAPLE SANITY CHECK: For pantry items (oil, spices, flour), do NOT suggest more than 1 unit (e.g., 1 bottle) unless the plan requires bulk amounts.\n"
        "6. Ensure the 'buy_list' cost is within budget."
    )

    print(f"DEBUG: Explicit fridge list being sent to API: {repr(fridge_contents)}", flush=True)
    try:
        response1 = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_step1,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=InitialIngredientStrategy,
            )
        )
        strategy = response1.parsed
        if not strategy:
            log_step("❌ STEP 1 FAILED.")
            return [], {}

        log_step(f"✅ Sourcing Complete: {len(strategy.buy_list)} to buy, {len(strategy.home_list)} from home.")

        # --- PROMPT 2: MEAL SCHEDULING & MAPPING ---
        buy_pool = [f"{ing.name} ({ing.qty} {ing.unit})" for ing in strategy.buy_list]
        home_pool = [f"{ing.name} ({ing.qty} {ing.unit})" for ing in strategy.home_list]
        
        prompt_step2 = (
            f"Step 2: Create a {days}-day meal plan schedule for {household_size} people using ONLY these ingredients.\n"
            f"REQUIRED: Generate EXACTLY {meals_per_day} meals per day (Total {days * meals_per_day} meals).\n"
            f"BUY LIST: {', '.join(buy_pool)}\n"
            f"HOME LIST: {', '.join(home_pool)}\n\n"
            "Constraints:\n"
            "1. Assign specific ingredients and amounts to each meal. Each meal should serve {household_size} people.\n"
            "2. FRACTIONAL USE: Since Step 1 defined large retail units (e.g., '1 bunch of bananas'), use fractions of those units for individual meals (e.g., '0.2 bunch' or '1 unit') to ensure the total used matches the pool.\n"
            "3. Ensure the meal plan respects dietary goals: {diet_restrictions}, {cuisines}.\n"
            "4. NO NEW INGREDIENTS. Assume ONLY water."
        )

        response2 = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_step2,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MealPlanStructure,
            )
        )
        plan_structure = response2.parsed
        if not plan_structure:
            log_step("❌ STEP 2 FAILED.")
            return [], {}

        log_step(f"✅ Scheduling Complete: {len(plan_structure.meals)} meals planned.")

        # Build master lookup for ingredient metadata
        master_lookup = {}
        for ing in strategy.buy_list:
            master_lookup[ing.name.lower()] = {"is_at_home": False, "query": ing.search_query, "strategy": ing.purchase_strategy}
        for ing in strategy.home_list:
            master_lookup[ing.name.lower()] = {"is_at_home": True, "query": "", "strategy": ing.purchase_strategy}

        # --- PROMPT 3: BATCH RECIPE EXECUTION (BATCHED BY 6) ---
        final_meal_plan = []
        
        # Split meals into batches of 6
        meal_batches = [plan_structure.meals[i:i + 6] for i in range(0, len(plan_structure.meals), 6)]
        
        log_step(f"🍳 Generating instructions for {len(plan_structure.meals)} meals in {len(meal_batches)} batches...")
        
        import time 

        for batch_idx, batch in enumerate(meal_batches):
            log_step(f"   - Processing Batch {batch_idx + 1}/{len(meal_batches)} ({len(batch)} meals)...")
            
            batch_prompts = []
            for meal_brief in batch:
                ing_strings = [f"{i.name} ({i.qty} {i.unit})" for i in meal_brief.ingredients]
                batch_prompts.append(f"- Recipe: {meal_brief.name}. Ingredients: {', '.join(ing_strings)}")

            prompt_step3 = (
                "Generate detailed recipe instructions for each of the following meals.\n"
                "MEALS TO GENERATE:\n" + "\n".join(batch_prompts) + "\n\n"
                "Constraints:\n"
                "1. Provide realistic calories and cook time for EACH.\n"
                "2. Instructions must be clear and use the exact ingredient names provided.\n"
                "3. Return a list of recipes matching the input list."
            )

            try:
                response3 = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt_step3,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchRecipeExecution,
                    )
                )
                batch_result = response3.parsed
                if batch_result and batch_result.recipes:
                    # Create a lookup for recipe results in this batch
                    recipe_lookup = {r.name.lower(): r for r in batch_result.recipes}
                    
                    for meal_brief in batch:
                        recipe = recipe_lookup.get(meal_brief.name.lower())
                        if not recipe:
                            # Fallback search if name slightly changed
                            for name, res in recipe_lookup.items():
                                if meal_brief.name.lower() in name or name in meal_brief.name.lower():
                                    recipe = res
                                    break
                        
                        if recipe:
                            # Enrich ingredients with metadata for the UI
                            enriched_ings = []
                            for i in meal_brief.ingredients:
                                meta = master_lookup.get(i.name.lower(), {"is_at_home": False, "query": "", "strategy": "unit"})
                                enriched_ings.append({
                                    "name": i.name, "qty": i.qty, "unit": i.unit,
                                    "is_at_home": meta["is_at_home"],
                                    "search_query": meta["query"],
                                    "purchase_strategy": meta["strategy"]
                                })

                            final_meal_plan.append({
                                "day": meal_brief.day,
                                "meal_type": meal_brief.meal_type,
                                "name": meal_brief.name,
                                "calories": recipe.calories,
                                "cook_time": recipe.cook_time,
                                "ingredients": enriched_ings,
                                "instructions": recipe.instructions
                            })
                else:
                    log_step(f"⚠️ Batch {batch_idx + 1} returned no recipes.")
                
                # Small pause to avoid hitting Rpm limits on free tier
                if batch_idx < len(meal_batches) - 1:
                    time.sleep(2)

            except Exception as e:
                log_step(f"⚠️ Failed to generate batch {batch_idx + 1}: {e}")
                if "429" in str(e):
                    log_step("   - Rate limit hit, sleeping for 10s before next batch...")
                    time.sleep(10)

        # Build aggregated ingredient data for mapping in main.py
        aggregated_ingredient_data = {}
        for ing in strategy.buy_list:
            aggregated_ingredient_data[ing.name.lower().strip()] = {
                "qty": ing.qty, "unit": ing.unit, "is_at_home": False,
                "query": ing.search_query, "strategy": ing.purchase_strategy
            }
        for ing in strategy.home_list:
            aggregated_ingredient_data[ing.name.lower().strip()] = {
                "qty": ing.qty, "unit": ing.unit, "is_at_home": True,
                "query": "", "strategy": ing.purchase_strategy
            }

        log_step("✅ 3-Prompt plan complete.")
        return final_meal_plan, aggregated_ingredient_data

    except Exception as e:
        err = f"❌ Error in 3-Prompt planner: {e}\n{traceback.format_exc()}"
        log_step(err)
        return [], {}
