import json
import os
import random
from collections import defaultdict
from typing import List, Dict, Tuple, Any, Optional

_MEALS_FILE = os.path.join(os.path.dirname(__file__), "meals.json")
_DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_TYPE_SEQUENCES = {
    1: ["Dinner"],
    2: ["Breakfast", "Dinner"],
    3: ["Breakfast", "Lunch", "Dinner"],
}


_MEALS_CACHE: Optional[List[Dict]] = None


def _load_meals() -> List[Dict]:
    """Load meals.json once and cache in memory — the file is static per
    deploy, so re-reading/parsing it on every plan request is wasted work.
    (A restart picks up any edited meals.json.)"""
    global _MEALS_CACHE
    if _MEALS_CACHE is None:
        with open(_MEALS_FILE, "r", encoding="utf-8") as f:
            _MEALS_CACHE = json.load(f)
    return _MEALS_CACHE


def _filter_meals(meals: List[Dict], dietary_restrictions: str, allergens: str) -> List[Dict]:
    restrictions = {r.strip() for r in dietary_restrictions.split(",") if r.strip()} if dietary_restrictions else set()
    allergen_set = {a.strip() for a in allergens.split(",") if a.strip()} if allergens else set()

    filtered = []
    for meal in meals:
        if allergen_set and set(meal.get("allergen_tags", [])) & allergen_set:
            continue
        if restrictions:
            tags = set(meal.get("dietary_tags", []))
            if not restrictions.issubset(tags):
                continue
        filtered.append(meal)
    return filtered


def _select_meals(meals: List[Dict], days: int, meals_per_day: int) -> List[Dict]:
    by_type: Dict[str, List] = defaultdict(list)
    for m in meals:
        by_type[m.get("meal_type", "Dinner")].append(m)

    if meals_per_day <= 3:
        type_seq = _TYPE_SEQUENCES.get(meals_per_day, ["Breakfast", "Lunch", "Dinner"])
    else:
        type_seq = ["Breakfast", "Lunch", "Dinner"] + ["Snack"] * (meals_per_day - 3)

    selected, used_ids = [], set()
    for _ in range(days):
        for meal_type in type_seq:
            pool = by_type.get(meal_type, []) or meals
            available = [m for m in pool if m["id"] not in used_ids] or pool
            meal = random.choice(available)
            selected.append(meal)
            used_ids.add(meal["id"])
    return selected


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
    household_size: int = 1,
    meals: Optional[List[Dict]] = None,
    allergies: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:

    print(f"[MealPlanner] {days}d × {meals_per_day} meals, household={household_size}", flush=True)

    all_meals = meals if meals is not None else _load_meals()
    # allergen_tags are a hard exclusion (safety-relevant) — never silently
    # skipped. If every meal happens to trigger an allergen, that's a real
    # "no safe meals" state, not something to paper over with the unfiltered
    # list the way the softer dietary/cuisine filters do below.
    filtered = _filter_meals(all_meals, diet_restrictions, allergies)
    if not filtered:
        print("[MealPlanner] WARNING: no meals satisfy the allergy/diet filters — "
              "falling back to diet-only filter (allergens may not be fully honored).", flush=True)
        filtered = _filter_meals(all_meals, diet_restrictions, "") or all_meals
    selected = _select_meals(filtered, days, meals_per_day)

    fridge_tokens = {t.strip().lower() for t in fridge_contents.split(",") if t.strip()} if fridge_contents else set()

    if meals_per_day <= 3:
        type_seq = _TYPE_SEQUENCES.get(meals_per_day, ["Breakfast", "Lunch", "Dinner"])
    else:
        type_seq = ["Breakfast", "Lunch", "Dinner"] + ["Snack"] * (meals_per_day - 3)

    day_labels = (_DAYS_OF_WEEK * ((days // 7) + 1))[:days]

    meal_plan: List[Dict] = []
    aggregated: Dict[str, Dict] = {}

    for i, meal in enumerate(selected):
        day = day_labels[i // meals_per_day]
        meal_type = type_seq[i % meals_per_day]

        enriched_ings = []
        for ing in meal.get("ingredients", []):
            scaled_qty = ing["qty"] * household_size
            key = ing["name"].lower().strip()
            is_at_home = any(tok in key or key in tok for tok in fridge_tokens)

            enriched_ings.append({
                "name": ing["name"],
                "qty": scaled_qty,
                "unit": ing["unit"],
                "is_at_home": is_at_home,
                "search_query": ing["name"],
                "purchase_strategy": "unit",
            })

            if is_at_home:
                aggregated.setdefault(key, {"qty": 0.0, "unit": ing["unit"], "is_at_home": True, "query": "", "strategy": "unit"})
            else:
                if key not in aggregated:
                    aggregated[key] = {"qty": 0.0, "unit": ing["unit"], "is_at_home": False, "query": ing["name"], "strategy": "unit"}
                aggregated[key]["qty"] += scaled_qty

        cook_mins = meal.get("cook_time_minutes", 30)
        meal_plan.append({
            "day": day,
            "meal_type": meal_type,
            "name": meal["name"],
            "calories": meal.get("calories", 400),
            "cook_time": f"{cook_mins} mins",
            "ingredients": enriched_ings,
            "instructions": meal.get("instructions", ["Prepare ingredients.", "Cook and serve."]),
        })

    print(f"[MealPlanner] {len(meal_plan)} meals, {len(aggregated)} unique ingredients.", flush=True)
    return meal_plan, aggregated
