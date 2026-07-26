"""
Mechanical tagging pass over backend/recipes_raw.jsonl, per the rules in
MEALS_TAGGING.md. Derives allergen_tags, dietary_tags, and the
NUTRITION-derivable health_tags for every recipe — KEYWORD/NUTRITION rules
only, no LLM calls, so this runs on all 83k+ rows in seconds for free.

Does NOT derive: ingredient qty/unit (recipes_raw.jsonl's ingredients are
bare names, no quantities — see import_kaggle_recipes.py), or any LLM-only
health_tags (High-Fiber, Heart-Healthy, Diabetes-Friendly, Mediterranean,
Anti-Inflammatory, Gut-Friendly, PCOS-Friendly, Weight-Loss). Output is a
staging file, NOT meals.json directly — meal_planner.py multiplies qty by
household_size, so a placeholder qty would silently corrupt pricing for any
meal pulled from here. Merge into meals.json only after quantities exist.

Usage:
    python tag_recipes.py [--limit N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_IN_PATH = Path(__file__).parent / "recipes_raw.jsonl"
_OUT_PATH = Path(__file__).parent / "recipes_tagged_staging.jsonl"

# ---------------------------------------------------------------------------
# Allergen keyword lists — see MEALS_TAGGING.md for the rationale (biased
# toward over-flagging: false positives are annoying, false negatives are
# harmful).
# ---------------------------------------------------------------------------
ALLERGEN_KEYWORDS: dict[str, list[str]] = {
    "Milk / Dairy": ["milk", "cream", "butter", "cheese", "yogurt", "yoghurt", "whey",
                     "casein", "ghee", "buttermilk", "custard", "half and half", "half-and-half"],
    "Eggs": ["egg", "mayonnaise", "mayo", "meringue", "albumin"],
    "Fish": ["fish", "anchov", "salmon", "tuna", "cod", "tilapia", "bass", "trout",
             "sardine", "fish sauce", "worcestershire"],
    "Shellfish": ["shrimp", "crab", "lobster", "prawn", "crawfish", "crayfish"],
    "Molluscs": ["clam", "mussel", "oyster", "scallop", "squid", "calamari", "octopus",
                 "snail", "escargot"],
    "Tree Nuts": ["almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut",
                  "macadamia", "brazil nut", "pine nut", "marzipan", "nutella", "praline"],
    "Peanuts": ["peanut", "groundnut"],
    "Wheat / Gluten": ["wheat", "flour", "bread", "pasta", "barley", "rye", "malt",
                       "semolina", "couscous", "panko", "breadcrumb", "noodle", "cracker",
                       "soy sauce", "tortilla"],
    "Soy": ["soy", "tofu", "edamame", "miso", "tempeh", "tamari", "soybean"],
    "Sesame": ["sesame", "tahini", "halva"],
    "Corn": ["corn", "cornstarch", "corn syrup", "cornmeal", "masa", "hominy"],
    "Mustard": ["mustard"],
    "Sulfites": ["wine", "dried apricot", "raisin", "molasses"],
    "Celery": ["celery", "celeriac"],
    "Coconut": ["coconut"],
    "Lupin": ["lupin", "lupini"],
}

# Protein-source keywords, used for the meat/poultry/fish exclusion dietary
# tags (Vegan/Vegetarian/Pescatarian/No X).
MEAT_KEYWORDS = ["beef", "steak", "ground beef", "brisket", "veal"]
PORK_KEYWORDS = ["pork", "bacon", "ham", "sausage", "prosciutto", "pancetta", "chorizo"]
LAMB_KEYWORDS = ["lamb", "mutton"]
POULTRY_KEYWORDS = ["chicken", "turkey", "duck", "hen"]
SEAFOOD_KEYWORDS = (ALLERGEN_KEYWORDS["Fish"] + ALLERGEN_KEYWORDS["Shellfish"]
                    + ALLERGEN_KEYWORDS["Molluscs"])
HONEY_KEYWORDS = ["honey"]
GELATIN_KEYWORDS = ["gelatin", "gelatine"]

PALEO_EXCLUDE = (ALLERGEN_KEYWORDS["Wheat / Gluten"] + ["rice", "oat", "quinoa", "barley",
                 "bean", "lentil", "chickpea", "peanut", "sugar", "corn syrup"]
                 + ALLERGEN_KEYWORDS["Milk / Dairy"])
FODMAP_EXCLUDE = ["garlic", "onion", "wheat", "bean", "lentil", "chickpea", "apple",
                  "pear", "watermelon", "cabbage", "cauliflower"]


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _ingredient_blob(recipe: dict) -> str:
    return " | ".join((recipe.get("ingredients") or [])).lower()


def tag_allergens(blob: str) -> list[str]:
    return sorted(tag for tag, kws in ALLERGEN_KEYWORDS.items() if _contains_any(blob, kws))


def tag_dietary(blob: str, allergens: set[str]) -> list[str]:
    tags = []
    has_meat = _contains_any(blob, MEAT_KEYWORDS)
    has_pork = _contains_any(blob, PORK_KEYWORDS)
    has_lamb = _contains_any(blob, LAMB_KEYWORDS)
    has_poultry = _contains_any(blob, POULTRY_KEYWORDS)
    has_seafood = _contains_any(blob, SEAFOOD_KEYWORDS)
    has_honey = _contains_any(blob, HONEY_KEYWORDS)
    any_meat_or_animal_protein = has_meat or has_pork or has_lamb or has_poultry or has_seafood

    if not any_meat_or_animal_protein:
        tags.append("Vegetarian")
        if "Milk / Dairy" not in allergens and "Eggs" not in allergens and not has_honey:
            tags.append("Vegan")
    elif not (has_meat or has_pork or has_lamb or has_poultry) and has_seafood:
        tags.append("Pescatarian")

    if not has_meat:
        tags.append("No Beef")
    if not has_pork:
        tags.append("No Pork")
    if not has_lamb:
        tags.append("No Lamb")
    if not has_poultry:
        tags.append("No Poultry")
    if not has_seafood:
        tags.append("No Seafood")
    if not (has_meat or has_lamb):
        tags.append("No Red Meat")

    if "Wheat / Gluten" not in allergens:
        tags.append("Gluten-Free")
    if "Milk / Dairy" not in allergens:
        tags.append("Dairy-Free")
    if "Eggs" not in allergens:
        tags.append("Egg-Free")

    if not _contains_any(blob, PALEO_EXCLUDE):
        tags.append("Paleo")
    if not _contains_any(blob, FODMAP_EXCLUDE):
        tags.append("Low-FODMAP")
    if not has_pork and not _contains_any(blob, ["alcohol", "wine", "beer", "rum", "liquor"]) \
            and not _contains_any(blob, GELATIN_KEYWORDS):
        tags.append("Halal")  # approximate — see MEALS_TAGGING.md caveat
    # Kosher also requires meat+dairy separation, which isn't verifiable from
    # a flat ingredient list (no dish-structure info) — skipped entirely
    # rather than producing a rule that's more likely wrong than right.

    return sorted(set(tags))


# High-carb/sugar staples that make a "low carb %DV" reading misleading —
# Food.com's %DV is against 300g of carbs, so plenty of genuinely carby
# dishes (small-portion desserts, legumes, starches) still read "low" by
# percentage alone. Validated against a 500-recipe sample: without this,
# brownies and taco shells were passing the Keto nutrition threshold.
# Extra high-carb/sugar staples not already covered by the Wheat/Gluten
# allergen keyword list (which already catches wheat/bulgur/crackers/etc.).
# Combined with that list below rather than duplicating it. Validated against
# a 500-recipe sample: without this, brownies, taco shells, pizza crust/dough
# snacks, and bulgur dishes were all passing the Keto nutrition threshold.
_HIGH_CARB_KEYWORDS = [
    "sugar", "syrup", "honey", "rice", "potato", "oat", "corn", "pea", "bean",
    "lentil", "chickpea", "cornstarch", "dough", "crust", "crescent", "granola",
    "quinoa",
]


def tag_health_nutrition(nutrition: dict, blob: str = "", allergens: set[str] | None = None) -> list[str]:
    """NUTRITION-threshold tags, cross-checked against ingredients for the
    carb-sensitive ones — the LLM-only tags are deliberately left out (see
    MEALS_TAGGING.md)."""
    if not nutrition:
        return []
    tags = []
    protein = nutrition.get("protein_pdv")
    carbs = nutrition.get("carbohydrates_pdv")
    fat = nutrition.get("total_fat_pdv")
    sodium = nutrition.get("sodium_pdv")
    sugar = nutrition.get("sugar_pdv")
    has_high_carb_ingredient = (_contains_any(blob, _HIGH_CARB_KEYWORDS)
                                 or "Wheat / Gluten" in (allergens or set()))

    if protein is not None and protein >= 40:
        tags.append("High-Protein")
    if carbs is not None and carbs <= 8 and sugar is not None and sugar <= 5 \
            and not has_high_carb_ingredient:
        tags.append("Low-Carb")
        if fat is not None and fat >= 15:
            tags.append("Keto")  # low-carb alone isn't keto — needs fat-dominance too
    if fat is not None and fat <= 10:
        tags.append("Low-Fat")
    if sodium is not None and sodium <= 10:
        tags.append("Low-Sodium")
    if sugar is not None and sugar <= 5:
        tags.append("Low-Sugar")
    return sorted(set(tags))


# ---------------------------------------------------------------------------
# meal_type / cuisine — not covered by MEALS_TAGGING.md (that doc is scoped
# to allergy/dietary/health), but required by the existing meals.json schema.
# ---------------------------------------------------------------------------
_MEAL_TYPE_TAGS = {
    "Breakfast": ["breakfast", "brunch"],
    "Lunch": ["lunch"],
    "Snack": ["snacks", "appetizers", "desserts", "cookies-and-brownies", "candy"],
}
_CUISINE_TAGS = {
    "Italian": ["italian"],
    "Mexican": ["mexican", "tex-mex"],
    "Asian": ["asian", "chinese", "japanese", "thai", "vietnamese", "korean"],
    "Indian": ["indian"],
    "French": ["french"],
    "Mediterranean": ["mediterranean", "greek"],
    "American": ["american", "north-american"],
}


def guess_meal_type(tags: list[str]) -> str:
    tagset = set(tags)
    for mtype, kws in _MEAL_TYPE_TAGS.items():
        if tagset & set(kws):
            return mtype
    return "Dinner"


def guess_cuisine(tags: list[str]) -> str:
    tagset = set(tags)
    for cuisine, kws in _CUISINE_TAGS.items():
        if tagset & set(kws):
            return cuisine
    return "American"


def tag_recipe(recipe: dict) -> dict:
    blob = _ingredient_blob(recipe)
    allergens = tag_allergens(blob)
    dietary = tag_dietary(blob, set(allergens))
    health = tag_health_nutrition(recipe.get("nutrition") or {}, blob, set(allergens))
    ftags = recipe.get("tags") or []

    return {
        "id": f"kaggle-{recipe.get('id')}",
        "name": (recipe.get("name") or "").strip().title(),
        "meal_type": guess_meal_type(ftags),
        "cuisine": guess_cuisine(ftags),
        "calories": round((recipe.get("nutrition") or {}).get("calories") or 0),
        "cook_time_minutes": recipe.get("minutes"),
        "dietary_tags": dietary,
        "allergen_tags": allergens,
        "health_tags": health,
        "ingredients": [{"name": n, "qty": None, "unit": None} for n in (recipe.get("ingredients") or [])],
        "instructions": recipe.get("steps") or [],
        "_source": "kaggle_foodcom",
        "_needs_quantity_normalization": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=_OUT_PATH)
    args = ap.parse_args()

    written = 0
    with open(_IN_PATH, "r", encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            if args.limit and written >= args.limit:
                break
            recipe = json.loads(line)
            tagged = tag_recipe(recipe)
            fout.write(json.dumps(tagged, ensure_ascii=False) + "\n")
            written += 1
            if written % 20000 == 0:
                print(f"[tag_recipes] {written} tagged...", flush=True)

    print(f"[tag_recipes] Done. {written} recipes tagged -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
