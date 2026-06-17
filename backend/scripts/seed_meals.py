"""
Seed meals from meals.json and extract ingredients into Supabase.

Usage:
    python -m backend.scripts.seed_meals
"""
import json
import os
import sys
from collections import Counter
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config.env"))

from db import db
from kroger_pricing import (
    _DRY_OZ_PER_CUP,
    STANDARD_CAN_OZ,
    _COUNT_TO_OZ,
    MASS_TO_OZ,
    VOL_TO_FLOZ,
    COUNT_UNIT_STRINGS,
)


MEALS_FILE = os.path.join(os.path.dirname(__file__), "..", "meals.json")


# ── Ingredient metadata helpers ────────────────────────────────────────────

def _unit_family(unit: str) -> str:
    u = unit.lower().strip()
    if u in MASS_TO_OZ:
        return "oz"
    if u in VOL_TO_FLOZ:
        return "fl_oz"
    if u in COUNT_UNIT_STRINGS:
        return "ct"
    return "ct"


def _get_density(name: str) -> Optional[float]:
    lower = name.lower()
    for keyword, oz_per_cup in _DRY_OZ_PER_CUP.items():
        if keyword in lower:
            return round(oz_per_cup / 8.0, 6)
    return None


def _get_can_size(name: str) -> Optional[float]:
    lower = name.lower()
    for keyword, oz in STANDARD_CAN_OZ.items():
        if keyword in lower:
            return oz
    return None


def _get_count_to_oz(name: str) -> Optional[float]:
    lower = name.lower()
    for keyword, oz in _COUNT_TO_OZ.items():
        if keyword in lower:
            return oz
    return None


def _determine_canonical_unit(ingredient_name: str, units_seen: list[str]) -> str:
    """Pick the most appropriate base unit for an ingredient based on how
    it's used across meals and the known density/can-size tables."""
    lower = ingredient_name.lower()

    if _get_can_size(lower):
        return "oz"
    if _get_density(lower):
        return "fl_oz"
    if _get_count_to_oz(lower):
        return "ct"

    families = [_unit_family(u) for u in units_seen]
    most_common = Counter(families).most_common(1)
    return most_common[0][0] if most_common else "ct"


# ── Main ──────────────────────────────────────────────────────────────────

def seed():
    with open(MEALS_FILE, "r", encoding="utf-8") as f:
        meals_data = json.load(f)

    print(f"Loaded {len(meals_data)} meals from meals.json")

    # ── Extract unique ingredients ───────────────────────────────────────
    ingredient_usage: dict[str, Counter] = {}  # name -> Counter of units
    for meal in meals_data:
        for ing in meal.get("ingredients", []):
            name = ing["name"]
            unit = ing["unit"]
            if name not in ingredient_usage:
                ingredient_usage[name] = Counter()
            ingredient_usage[name][unit] += 1

    # Build ingredient rows
    ingredient_rows = []
    for name, unit_counts in sorted(ingredient_usage.items()):
        units_seen = list(unit_counts.elements())
        canonical = _determine_canonical_unit(name, units_seen)
        row = {
            "name": name,
            "canonical_unit": canonical,
            "density": _get_density(name) if canonical == "fl_oz" else None,
            "can_size_oz": _get_can_size(name),
            "count_to_oz": _get_count_to_oz(name),
        }
        ingredient_rows.append(row)

    # Insert ingredients
    inserted = db.bulk_create_ingredients(ingredient_rows)
    print(f"Inserted {inserted} new ingredient(s) (total: {len(db.get_ingredients())})")
    if inserted > 0:
        print(f"  First few: {', '.join(r['name'] for r in ingredient_rows[:5])}")

    # ── Seed meals table ─────────────────────────────────────────────────
    existing_ids = {m["id"] for m in db.client.table("meals").select("id").execute().data}
    new_meals = [m for m in meals_data if m["id"] not in existing_ids]

    if not new_meals:
        print("Meals already seeded — nothing to do.")
        return

    # Convert to the column names expected by the meals table
    meal_rows = []
    for m in new_meals:
        meal_rows.append({
            "id": m["id"],
            "name": m["name"],
            "meal_type": m.get("meal_type", "Dinner"),
            "cuisine": m.get("cuisine", ""),
            "calories": m.get("calories", 0),
            "cook_time_minutes": m.get("cook_time_minutes", 0),
            "dietary_tags": m.get("dietary_tags", []),
            "allergen_tags": m.get("allergen_tags", []),
            "health_tags": m.get("health_tags", []),
            "ingredients": m.get("ingredients", []),
            "instructions": m.get("instructions", []),
        })

    resp = db.client.table("meals").insert(meal_rows).execute()
    inserted_count = len(resp.data)
    print(f"Inserted {inserted_count} meal(s) into Supabase")
    print(f"  Meal types: {set(m['meal_type'] for m in new_meals)}")


if __name__ == "__main__":
    seed()
