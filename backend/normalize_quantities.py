"""
Assigns qty/unit to the bare ingredient names in recipes_tagged_staging.jsonl.

IMPORTANT: this is NOT extracted from the recipe. Food.com's `steps` text was
checked directly and essentially never states an ingredient amount (it's
almost entirely times/temps and vague dish-portioning language like "1/3 of
the mixture", not "2 cups flour") — so there is no free, reliable way to
recover the recipe author's real quantities. What this does instead is
assign a sensible, typical default per ingredient CATEGORY (keyword-matched),
e.g. "eggs" -> 2 whole, "flour" -> 1 cup, "chicken breast" -> 1 lb. Every
ingredient is marked qty_source="category_default" so nothing downstream
mistakes this for the recipe's actual amount.

Usage:
    python normalize_quantities.py [--limit N] [--in PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_IN_PATH = Path(__file__).parent / "recipes_tagged_staging.jsonl"
_OUT_PATH = Path(__file__).parent / "recipes_ready_to_merge.jsonl"

# Ordered most-specific-first: first matching category wins. (qty, unit)
# reflects a typical single-recipe-serving-batch amount, not a per-serving
# amount — same convention as the existing hand-written meals.json.
# Ordered most-specific-first, first match wins. Matching is WORD-BOUNDARY
# based (see _compile / default_for), NOT naive substring — this is what stops
# "lemon juice" matching "ice", "buttermilk" matching "butter", "bell pepper"
# matching the spice "pepper", and "pear"/"peach" matching "pea". Simple
# plurals are auto-handled ((?:s|es)?), so list singular forms; irregular
# plurals (leaf->leaves) are listed explicitly.
_CATEGORY_DEFAULTS: list[tuple[list[str], float, str]] = [
    # Eggs
    (["egg"], 2, "whole"),
    # Juices — citrus is a small flavoring amount; other juices a recipe liquid.
    # MUST precede oils/fruit so "lemon juice" doesn't hit "ice" or "lemon".
    (["lemon juice", "lime juice"], 2, "tbsp"),
    (["orange juice", "apple juice", "cranberry juice", "pineapple juice",
      "grape juice", "juice"], 0.5, "cup"),
    # Butter / oils (small measured amounts). "butter" no longer catches
    # "buttermilk" thanks to word boundaries.
    (["unsalted butter", "butter"], 2, "tbsp"),
    (["olive oil", "vegetable oil", "canola oil", "cooking oil", "sesame oil",
      "coconut oil", "grapeseed oil", "oil"], 2, "tbsp"),
    # Condiments / sauces (small amounts). "chili-garlic sauce" / "garlic sauce"
    # sit here so they don't fall to the garlic-cloves allium rule below.
    (["ketchup", "mustard", "mayonnaise", "mayo", "hot sauce", "soy sauce",
      "worcestershire", "vinegar", "hoisin", "bbq sauce", "barbecue sauce",
      "chili-garlic sauce", "garlic sauce", "pesto", "oyster sauce", "fish sauce",
      "teriyaki", "sriracha", "ranch dressing", "italian dressing", "steak sauce"], 1, "tbsp"),
    # Pepper — SPICE forms first (tsp), so they beat the vegetable-pepper rule.
    (["black pepper", "white pepper", "red pepper flake", "crushed red pepper",
      "cayenne", "ground pepper", "lemon pepper", "peppercorn"], 1, "tsp"),
    # Pepper — VEGETABLE forms (1 whole). Precede the general spice rule so bare
    # "pepper" there doesn't swallow "bell pepper".
    (["bell pepper", "red pepper", "green pepper", "sweet pepper", "yellow pepper",
      "orange pepper", "banana pepper", "jalapeno", "serrano", "poblano",
      "chili pepper", "chile pepper", "habanero"], 1, "whole"),
    # Spices, seasonings, extracts, leavening (very small amounts). "cream of
    # tartar" lives here (tsp) so it beats the dairy "cream" rule below, and the
    # "celery seed" / "granulated garlic" style forms so they beat the celery
    # vegetable / garlic allium rules below.
    (["salt", "pepper", "cumin", "paprika", "oregano", "basil", "thyme", "rosemary",
      "cinnamon", "nutmeg", "cayenne", "chili powder", "garlic powder", "onion powder",
      "baking soda", "baking powder", "vanilla", "seasoning", "spice", "ground clove",
      "allspice", "turmeric", "curry powder", "bay leaf", "bay leaves", "italian seasoning",
      "ginger", "coriander", "cardamom", "cocoa", "cream of tartar",
      "celery seed", "granulated garlic", "garlic granules", "onion flakes",
      "poppy seed", "fennel seed", "mustard seed", "caraway seed",
      "whole clove", "sage"], 1, "tsp"),
    # Fresh herbs
    (["parsley", "cilantro", "dill", "mint", "chives", "fresh herb"], 2, "tbsp"),
    # Alcohol / liqueurs used as flavoring (small amounts, not a beverage serving)
    (["wine", "vodka", "liqueur", "amaretto", "rum", "brandy", "sherry", "beer"], 2, "tbsp"),
    # Sweeteners
    (["agave", "maple syrup"], 2, "tbsp"),
    # Garlic / alliums (counted, not measured)
    (["garlic clove", "garlic"], 2, "cloves"),
    (["scallion", "green onion"], 2, "stalks"),
    # Flour / dry baking staples
    (["flour"], 1, "cup"),
    (["sugar", "honey", "molasses"], 0.5, "cup"),
    (["cocoa powder", "cornstarch", "breadcrumb", "panko"], 0.5, "cup"),
    (["chocolate chip", "chocolate"], 0.5, "cup"),
    (["raisin", "dried fruit", "dried cranberry", "date", "prune", "dried apricot"], 0.25, "cup"),
    (["yeast"], 1, "packet"),
    # Water / ice (recipe-as-written amount, genuinely variable — small nominal default)
    (["water", "ice"], 1, "cup"),
    (["cooking spray"], 1, "spray"),
    (["margarine", "shortening"], 2, "tbsp"),
    # Dairy — cream SPECIFICS first (cream cheese / sour cream get their own
    # amount) so they don't inherit the generic 1-cup pouring-cream default.
    (["cream cheese"], 0.5, "cup"),
    (["sour cream"], 0.5, "cup"),
    (["milk", "buttermilk", "cream", "heavy cream", "whipping cream",
      "half and half", "half-and-half", "condensed milk",
      "soymilk", "soy milk", "almond milk", "oat milk"], 1, "cup"),
    (["yogurt", "greek yogurt"], 0.5, "cup"),
    (["cheese"], 0.5, "cup"),  # shredded/grated convention; block/sliced cheese is close enough
    # Grains / starches (dry, uncooked)
    (["rice", "quinoa", "couscous", "oat", "oatmeal"], 1, "cup"),
    (["pasta", "noodle", "spaghetti", "macaroni", "penne", "linguine",
      "fettuccine", "lasagna", "rigatoni", "orzo", "ravioli"], 8, "oz"),
    # Buns/rolls counted; precede protein so "hamburger bun" isn't priced as meat.
    (["hamburger bun", "burger bun", "hot dog bun", "bun", "roll", "bagel",
      "english muffin", "pita"], 4, "each"),
    (["bread"], 2, "slices"),
    # Chips are a snack measured by volume — must precede the tortilla rule so
    # "tortilla chips" isn't counted as 4 whole tortillas.
    (["tortilla chip", "corn chip", "potato chip"], 2, "cups"),
    (["tortilla", "taco shell"], 4, "each"),
    # Bean sprouts are a fresh vegetable, not a canned bean — precede canned.
    (["bean sprout"], 1, "cup"),
    # Canned / jarred staples
    (["canned", "bean", "chickpea", "lentil"], 1, "can"),
    (["broth", "stock"], 2, "cups"),
    (["tomato paste"], 2, "tbsp"),
    (["tomato sauce", "salsa", "marinara"], 1, "cup"),
    # Boxed/packet mixes (precede protein/other rules so "pork gravy mix" isn't
    # priced as 1 lb of pork)
    (["gravy mix", "cake mix", "stuffing mix", "pancake mix", "muffin mix",
      "brownie mix", "seasoning mix", "pudding mix"], 1, "packet"),
    # Protein (raw weight convention). Broad on purpose — a missing protein
    # keyword silently sends a real meal's main component to the "1 unit"
    # fallback (found via validate_meals.py: tilapia/cod/scallops/roast cuts).
    (["chicken breast", "chicken thigh", "chicken", "turkey", "beef", "steak",
      "ground beef", "ground turkey", "ground pork", "ground chicken", "pork chop",
      "pork", "lamb", "veal", "venison", "duck",
      "roast", "brisket", "sirloin", "tenderloin", "chuck", "ribs", "rib eye",
      "ribeye", "meatball", "meatloaf",
      "fish fillet", "fish", "salmon", "tuna", "tilapia", "cod", "haddock",
      "halibut", "catfish", "trout", "snapper", "mahi", "flounder", "sole",
      "monkfish", "swordfish", "bass", "perch",
      "shrimp", "prawn", "scallop", "crab", "lobster", "clam", "mussel", "oyster",
      "calamari", "squid", "tofu", "tempeh", "seitan",
      "hamburger", "burger", "patty", "hot dog", "bratwurst"], 1, "lb"),
    (["bacon"], 4, "slices"),
    (["sausage"], 4, "links"),
    (["ham"], 1, "lb"),
    (["prosciutto", "deli meat", "deli ham"], 4, "slices"),
    # More condiments / small-amount jarred items
    (["fish sauce", "tabasco", "caper", "tahini", "nut butter", "horseradish"], 1, "tbsp"),
    # Nuts / seeds (small amounts)
    (["almond", "walnut", "pecan", "cashew", "peanut", "pistachio", "sesame seed",
      "sunflower seed", "chia seed", "pine nut", "nut"], 0.25, "cup"),
    (["coconut"], 0.25, "cup"),
    # Fresh chili/chile (bare) — after the spice rule so "chili powder" stays tsp.
    (["chili", "chile"], 1, "whole"),
    # More dry baking staples
    (["cornmeal"], 0.5, "cup"),
    (["applesauce"], 0.5, "cup"),
    # Fresh ginger (root form — one word, needs its own entry)
    (["gingerroot", "ginger root", "fresh ginger"], 1, "tbsp"),
    # Vegetables — counted produce (bell pepper handled above)
    (["shallot", "leek"], 1, "whole"),
    (["onion", "tomato", "potato", "carrot", "cucumber", "avocado",
      "zucchini", "eggplant", "squash", "beet", "radish", "turnip", "parsnip",
      "artichoke"], 1, "whole"),
    (["celery"], 2, "stalks"),
    (["spinach", "lettuce", "kale", "cabbage", "greens"], 2, "cups"),
    (["broccoli", "cauliflower", "asparagus", "green bean", "brussels sprout",
      "okra", "snap pea", "snow pea"], 2, "cups"),
    (["mushroom"], 1, "cup"),
    (["pumpkin", "sweet potato", "butternut"], 1, "cup"),
    (["corn", "pea", "olive"], 1, "cup"),
    # Beverages used as flavoring/small amounts
    (["coffee"], 1, "tbsp"),
    # Fruit — counted produce
    (["banana", "apple", "lemon", "lime", "orange", "pear", "peach", "pineapple", "mango"], 1, "whole"),
    (["strawberry", "blueberry", "raspberry", "blackberry", "cranberry",
      "berries", "berry", "grape"], 1, "cup"),
]

_FALLBACK = (1.0, "unit")

# Precompile one word-boundary regex per rule. We auto-handle plurals so the
# table can list singular forms: a trailing "(?:s|es)?" covers pea->peas /
# clove->cloves, and _variants() adds the -y -> -ies form (berry->berries).
# Word boundaries (\b) are the whole point: they stop the substring
# false-positives (ice/juice, butter/buttermilk, pea/pear).
def _variants(kw: str) -> set[str]:
    forms = {kw}
    if kw.endswith("y"):
        forms.add(kw[:-1] + "ies")
    return forms


_COMPILED: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"\b(?:" + "|".join(
        re.escape(v) for kw in kws for v in _variants(kw)
     ) + r")(?:s|es)?\b"),
     float(qty), unit)
    for kws, qty, unit in _CATEGORY_DEFAULTS
]


def default_for(name: str) -> tuple[float, str]:
    low = name.lower()
    for pattern, qty, unit in _COMPILED:
        if pattern.search(low):
            return qty, unit
    return _FALLBACK


def normalize_recipe(recipe: dict) -> dict:
    for ing in recipe.get("ingredients", []):
        qty, unit = default_for(ing["name"])
        ing["qty"] = qty
        ing["unit"] = unit
        ing["qty_source"] = "category_default"
    recipe["_needs_quantity_normalization"] = False
    recipe["_qty_note"] = "qty/unit are typical-amount ESTIMATES, not the recipe's real amounts (see normalize_quantities.py)"
    return recipe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--in", dest="in_path", type=Path, default=_IN_PATH)
    ap.add_argument("--out", type=Path, default=_OUT_PATH)
    args = ap.parse_args()

    written = 0
    unmatched_counter: dict[str, int] = {}
    with open(args.in_path, "r", encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            if args.limit and written >= args.limit:
                break
            recipe = json.loads(line)
            recipe = normalize_recipe(recipe)
            for ing in recipe["ingredients"]:
                if ing["qty_source"] == "category_default" and ing["unit"] == "unit":
                    unmatched_counter[ing["name"]] = unmatched_counter.get(ing["name"], 0) + 1
            fout.write(json.dumps(recipe, ensure_ascii=False) + "\n")
            written += 1
            if written % 20000 == 0:
                print(f"[normalize_quantities] {written} done...", flush=True)

    print(f"[normalize_quantities] Done. {written} recipes -> {args.out}", flush=True)
    top_unmatched = sorted(unmatched_counter.items(), key=lambda kv: -kv[1])[:20]
    print(f"[normalize_quantities] Top ingredients that hit the generic 1-unit fallback "
          f"(no category matched): {top_unmatched}", flush=True)


if __name__ == "__main__":
    main()
