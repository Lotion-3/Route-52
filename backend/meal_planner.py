"""
Meal-plan selection.

Design rule that drives most of this file: a constraint the user set is either
HONOURED or REPORTED — never silently dropped. The previous version did

    filtered = _filter_meals(all_meals, diet, allergies)
    if not filtered:
        filtered = _filter_meals(all_meals, diet, "") or all_meals

so an unsatisfiable combination fell all the way back to the unfiltered menu
with no signal to anyone. Because only 15 of the UI's 38 diet chips and 10 of
its 20 allergen chips exist as tags in the corpus, that path was the COMMON
case: selecting "Kosher" matched nothing, so the user was served pork.

Three mechanisms replace it:

  * ALIASES  — chips the corpus doesn't tag directly but which imply tags it
    does (Halal ⇒ No Pork, Kosher ⇒ No Pork + no Shellfish, Nut-Free ⇒ no Tree
    Nuts/Peanuts, ...). These are honoured properly rather than ignored.

  * INGREDIENT-LEVEL EXCLUSION — a keyword pass over ingredient names. This is
    what enforces the untagged allergens (Citrus, Coconut, Legumes, ...) and the
    user's free-form "avoid these ingredients" list, and it doubles as
    defence-in-depth behind the tag filters.

  * WARNINGS + a hard failure. Anything still unsupported is returned in
    `warnings` for the UI to show. If the hard constraints leave no meals at
    all, we raise NoSafeMealsError instead of quietly serving unsafe food.

Soft preferences (cuisine, calorie target, cook time, health conditions) rank
the pool rather than empty it, so they shape the plan without ever making it
unsatisfiable.
"""
from __future__ import annotations

import json
import os
import random
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

_MEALS_FILE = os.path.join(os.path.dirname(__file__), "meals.json")
_DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_TYPE_SEQUENCES = {
    1: ["Dinner"],
    2: ["Breakfast", "Dinner"],
    3: ["Breakfast", "Lunch", "Dinner"],
}

# Input bounds. Enforced here as well as in the API layer so the CLI and any
# direct caller get the same protection — meals_per_day=0 used to be a
# ZeroDivisionError and days_plan=365 a 2000-meal basket priced across 10 stores.
MAX_DAYS = int(os.environ.get("PLAN_MAX_DAYS", "30"))
MAX_MEALS_PER_DAY = int(os.environ.get("PLAN_MAX_MEALS_PER_DAY", "6"))
MAX_HOUSEHOLD = int(os.environ.get("PLAN_MAX_HOUSEHOLD", "12"))


class NoSafeMealsError(ValueError):
    """No meal satisfies the user's hard constraints (allergens / diet).

    A real, reportable state — the caller should surface it, never paper over it
    by relaxing the constraints.
    """


# ---------------------------------------------------------------------------
# Constraint vocabulary
# ---------------------------------------------------------------------------

# Diet chips the corpus tags directly.
_DIET_TAGS = {
    "Vegetarian", "Vegan", "Pescatarian", "Dairy-Free", "Egg-Free", "Gluten-Free",
    "Low-Carb", "Low-Fat", "Keto", "No Beef", "No Pork", "No Lamb", "No Poultry",
    "No Seafood", "No Red Meat",
}

# Diet chips with no tag of their own that nonetheless IMPLY constraints the
# corpus can enforce. Value: (dietary_tags to require, allergen_tags to exclude,
# ingredient keywords to exclude, caveat shown to the user or None).
_DIET_ALIASES: dict[str, tuple[set[str], set[str], set[str], Optional[str]]] = {
    "Hindu (No Beef)": ({"No Beef"}, set(), set(), None),
    "Halal": ({"No Pork"}, set(), {"bacon", "ham", "pancetta", "prosciutto", "chorizo",
                                   "wine", "beer", "rum", "vodka", "sherry", "mirin"},
              "Halal is enforced as no pork and no alcohol ingredients; "
              "meat is not certified zabiha."),
    "Kosher": ({"No Pork"}, {"Shellfish"}, {"bacon", "ham", "pancetta", "prosciutto"},
               "Kosher is enforced as no pork and no shellfish; "
               "meat/dairy separation and certification are not tracked."),
    "Nut-Free": (set(), {"Tree Nuts", "Peanuts"}, set(), None),
    "Soy-Free": (set(), {"Soy"}, {"soy sauce", "tofu", "tempeh", "edamame", "miso"}, None),
    "Sesame-Free": (set(), {"Sesame"}, {"sesame", "tahini"}, None),
    "No Red Meat": ({"No Beef", "No Lamb"}, set(), set(), None),
    "Mediterranean": (set(), set(), set(), None),      # handled as a health-tag preference
    "High-Protein": (set(), set(), set(), None),       # handled as a health-tag preference
    "Flexitarian": (set(), set(), set(),
                    "Flexitarian is treated as no restriction."),
}

# Diet chips scored as a health-tag PREFERENCE rather than a hard filter.
_DIET_AS_HEALTH_TAG = {"Mediterranean": "Mediterranean", "High-Protein": "High-Protein"}

# Allergen chips the corpus tags directly.
_ALLERGEN_TAGS = {
    "Eggs", "Milk / Dairy", "Wheat / Gluten", "Corn", "Fish", "Shellfish",
    "Soy", "Sesame", "Tree Nuts", "Peanuts",
}

# Allergen chips with no tag — enforced by matching ingredient names instead.
# Silently ignoring these was the most dangerous behaviour in the old code.
_ALLERGEN_INGREDIENT_KEYWORDS: dict[str, set[str]] = {
    "Mustard": {"mustard"},
    "Celery": {"celery", "celeriac"},
    "Lupin": {"lupin"},
    "Molluscs": {"clam", "mussel", "oyster", "scallop", "squid", "calamari",
                 "octopus", "snail", "escargot"},
    "Sulfites": {"wine", "vinegar", "dried apricot", "molasses"},
    "Nightshades": {"tomato", "potato", "bell pepper", "chili", "chilli", "jalapeno",
                    "jalapeño", "eggplant", "aubergine", "paprika", "cayenne",
                    "serrano", "habanero", "poblano", "salsa"},
    "Citrus": {"lemon", "lime", "orange", "grapefruit", "citrus", "tangerine",
               "clementine", "pomelo"},
    "Stone Fruits": {"peach", "plum", "nectarine", "apricot", "cherry", "mango"},
    "Coconut": {"coconut"},
    "Legumes": {"bean", "lentil", "chickpea", "pea", "peanut", "soy", "tofu",
                "tempeh", "edamame", "hummus"},
    # Belt-and-braces for the TAGGED allergens too — a mis-tagged meal should
    # still be caught by its ingredient list.
    "Peanuts": {"peanut"},
    # (continued below)
    "Tree Nuts": {"almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut",
                  "macadamia", "brazil nut", "pine nut"},
    "Sesame": {"sesame", "tahini"},
    "Shellfish": {"shrimp", "prawn", "crab", "lobster", "crayfish"},
    "Fish": {"salmon", "tuna", "tilapia", "cod", "halibut", "anchovy", "sardine",
             "trout", "mackerel", "haddock", "fish sauce"},
    "Milk / Dairy": {"milk", "cheese", "butter", "cream", "yogurt", "yoghurt",
                     "ghee", "paneer", "mozzarella", "cheddar", "parmesan", "ricotta"},
    "Eggs": {"egg"},
    "Wheat / Gluten": {"wheat", "bread", "pasta", "flour", "tortilla", "breadcrumb",
                       "couscous", "barley", "cracker", "bun", "noodle"},
    "Soy": {"soy", "tofu", "tempeh", "edamame", "miso"},
    "Corn": {"corn", "cornmeal", "polenta", "tortilla chip", "masa"},
}

# Allergens whose keyword match is genuinely unreliable, because they are
# additives rather than named ingredients — sulfites hide in dried fruit, wine
# and countless processed items; lupin flour is common in gluten-free baking and
# almost never appears as "lupin" in a recipe. We still apply the keywords, but
# these must NOT be presented as enforced.
_LOW_CONFIDENCE_ALLERGENS = {"Sulfites", "Lupin"}

# Health conditions → how we act on them.
#   "hard_diet"   : dietary tags that must be present (medical necessity)
#   "prefer"      : health tags we rank toward (a preference, not a filter)
_HEALTH_RULES: dict[str, dict[str, set[str]]] = {
    "Celiac Disease":        {"hard_diet": {"Gluten-Free"}},
    "Lactose Intolerance":   {"hard_diet": {"Dairy-Free"}},
    "Diabetes":              {"prefer": {"Diabetes-Friendly", "Low-Carb"}},
    "Pre-Diabetes":          {"prefer": {"Diabetes-Friendly", "Low-Carb"}},
    "Hypertension":          {"prefer": {"Heart-Healthy"}},
    "Heart Disease":         {"prefer": {"Heart-Healthy"}},
    "High Cholesterol":      {"prefer": {"Heart-Healthy", "High-Fiber"}},
    "Metabolic Syndrome":    {"prefer": {"Weight-Loss", "Heart-Healthy"}},
    "Fatty Liver Disease":   {"prefer": {"Weight-Loss", "Heart-Healthy"}},
    "PCOS":                  {"prefer": {"PCOS-Friendly", "Low-Carb"}},
    "IBS":                   {"prefer": {"Gut-Friendly"}},
    "Diverticulitis":        {"prefer": {"Gut-Friendly", "High-Fiber"}},
    "Arthritis":             {"prefer": {"Anti-Inflammatory"}},
    "Autoimmune Disease":    {"prefer": {"Anti-Inflammatory"}},
    "Eczema / Psoriasis":    {"prefer": {"Anti-Inflammatory"}},
    "Migraines":             {"prefer": {"Anti-Inflammatory"}},
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


def _split(csv: str) -> list[str]:
    return [p.strip() for p in (csv or "").split(",") if p.strip()]


def _ingredient_blob(meal: Dict) -> str:
    """Lowercased ingredient names for one meal, as a single searchable string."""
    return " | ".join((i.get("name") or "").lower() for i in meal.get("ingredients", []))


def _matches_keyword(blob: str, keyword: str) -> bool:
    """Whole-word-ish containment, so 'pea' doesn't match 'peanut butter' via a
    bare substring and 'egg' doesn't match 'eggplant'."""
    return re.search(rf"(?<![a-z]){re.escape(keyword)}(?:e?s)?(?![a-z])", blob) is not None


# ---------------------------------------------------------------------------
# Constraint resolution
# ---------------------------------------------------------------------------

class _Constraints:
    """Hard constraints + soft preferences, resolved from the raw user input."""

    def __init__(self):
        self.require_diet_tags: set[str] = set()
        self.exclude_allergen_tags: set[str] = set()
        self.exclude_keywords: set[str] = set()
        self.prefer_health_tags: set[str] = set()
        self.prefer_cuisines: set[str] = set()
        self.max_cook_minutes: Optional[int] = None
        self.warnings: list[str] = []


def _resolve_constraints(
    diet_restrictions: str,
    allergies: str,
    avoid_ingredients: str,
    health_issues: str,
    cuisines: str,
    cook_time: str,
    known_cuisines: set[str],
) -> _Constraints:
    c = _Constraints()
    unsupported_diet: list[str] = []
    unsupported_allergens: list[str] = []

    # --- Diet ---------------------------------------------------------------
    for chip in _split(diet_restrictions):
        if chip in _DIET_TAGS:
            c.require_diet_tags.add(chip)
        if chip in _DIET_AS_HEALTH_TAG:
            c.prefer_health_tags.add(_DIET_AS_HEALTH_TAG[chip])
        if chip in _DIET_ALIASES:
            tags, allergens, keywords, caveat = _DIET_ALIASES[chip]
            c.require_diet_tags |= tags
            c.exclude_allergen_tags |= allergens
            c.exclude_keywords |= keywords
            if caveat:
                c.warnings.append(caveat)
        elif chip not in _DIET_TAGS:
            unsupported_diet.append(chip)

    # --- Allergens (hard; tag filter AND ingredient filter) -----------------
    any_allergen = False
    low_confidence: list[str] = []
    for chip in _split(allergies):
        any_allergen = True
        handled = False
        if chip in _ALLERGEN_TAGS:
            c.exclude_allergen_tags.add(chip)
            handled = True
        if chip in _ALLERGEN_INGREDIENT_KEYWORDS:
            c.exclude_keywords |= _ALLERGEN_INGREDIENT_KEYWORDS[chip]
            handled = True
            if chip in _LOW_CONFIDENCE_ALLERGENS:
                low_confidence.append(chip)
        if not handled:
            unsupported_allergens.append(chip)

    # --- Explicit "avoid these ingredients" list ----------------------------
    for chip in _split(avoid_ingredients):
        token = chip.lower().strip()
        # Strip parenthetical hints, e.g. "Squid / Calamari", "Drumstick (Moringa)".
        token = re.sub(r"\(.*?\)", "", token).strip()
        for part in re.split(r"\s*/\s*", token):
            part = part.strip()
            if len(part) >= 3:
                c.exclude_keywords.add(part)

    # --- Health conditions --------------------------------------------------
    unsupported_health: list[str] = []
    for chip in _split(health_issues):
        rule = _HEALTH_RULES.get(chip)
        if not rule:
            unsupported_health.append(chip)
            continue
        c.require_diet_tags |= rule.get("hard_diet", set())
        c.prefer_health_tags |= rule.get("prefer", set())

    # --- Cuisine (soft) -----------------------------------------------------
    for chip in _split(cuisines):
        if chip in known_cuisines:
            c.prefer_cuisines.add(chip)
        else:
            c.warnings.append(f"No {chip} recipes in the catalogue yet — "
                              f"cuisine preference ignored for {chip}.")

    # --- Cook time (soft ceiling) ------------------------------------------
    c.max_cook_minutes = _parse_cook_minutes(cook_time)

    if unsupported_diet:
        c.warnings.append(
            "Not enforced (no recipes are tagged for these yet): "
            + ", ".join(sorted(unsupported_diet))
            + ". Your plan may include meals that don't meet them."
        )
    if unsupported_allergens:
        c.warnings.append(
            "ALLERGEN NOT ENFORCED — we can't detect "
            + ", ".join(sorted(unsupported_allergens))
            + " in these recipes. Check every ingredient list yourself."
        )
    if low_confidence:
        c.warnings.append(
            "ALLERGEN ONLY PARTLY ENFORCED — "
            + ", ".join(sorted(low_confidence))
            + " are additives that often aren't named in a recipe. "
            "Recipes naming them were removed, but others may still contain them."
        )
    if any_allergen:
        c.warnings.append(
            "Allergen filtering works on RECIPE ingredients, not product labels. "
            "Always check the packaging of what you actually buy."
        )
    if unsupported_health:
        c.warnings.append(
            "No specific recipe guidance for: " + ", ".join(sorted(unsupported_health)) + "."
        )
    return c


def _parse_cook_minutes(cook_time: str) -> Optional[int]:
    """Pull an upper bound in minutes out of the free-text cook-time field
    ('30-45 minutes' → 45, 'under 20 min' → 20, '1 hour' → 60)."""
    if not cook_time:
        return None
    s = cook_time.lower()
    hours = re.findall(r"(\d+(?:\.\d+)?)\s*(?:hour|hr)", s)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if hours:
        return int(max(float(h) * 60 for h in hours))
    if not nums:
        return None
    return int(max(nums))


# ---------------------------------------------------------------------------
# Filtering + ranking
# ---------------------------------------------------------------------------

def _passes_hard_constraints(meal: Dict, c: _Constraints) -> bool:
    if c.require_diet_tags and not c.require_diet_tags.issubset(set(meal.get("dietary_tags") or [])):
        return False
    if c.exclude_allergen_tags & set(meal.get("allergen_tags") or []):
        return False
    if c.exclude_keywords:
        blob = _ingredient_blob(meal)
        if any(_matches_keyword(blob, kw) for kw in c.exclude_keywords):
            return False
    return True


def _soft_score(meal: Dict, c: _Constraints, target_calories: Optional[float]) -> float:
    """Higher is better. Purely a ranking signal — never excludes a meal."""
    score = 0.0
    if c.prefer_cuisines:
        score += 3.0 if meal.get("cuisine") in c.prefer_cuisines else 0.0
    if c.prefer_health_tags:
        overlap = len(c.prefer_health_tags & set(meal.get("health_tags") or []))
        score += 2.0 * overlap
    if c.max_cook_minutes is not None:
        mins = meal.get("cook_time_minutes", 30)
        score += 1.5 if mins <= c.max_cook_minutes else -1.5
    if target_calories:
        # Reward proximity to the per-meal calorie target; ±40% is roughly neutral.
        cal = meal.get("calories") or 0
        if cal > 0:
            rel = abs(cal - target_calories) / target_calories
            score += max(-2.0, 2.0 * (1.0 - rel / 0.4))
    return score


def _filter_meals(meals: List[Dict], c: _Constraints) -> List[Dict]:
    return [m for m in meals if _passes_hard_constraints(m, c)]


def _select_meals(
    meals: List[Dict],
    days: int,
    meals_per_day: int,
    type_seq: List[str],
    c: _Constraints,
    per_meal_calories: Optional[float],
    experiment: bool,
    warnings: list[str],
) -> List[Dict]:
    """Pick days×meals_per_day meals, honouring meal_type and soft preferences."""
    by_type: Dict[str, List] = defaultdict(list)
    for m in meals:
        by_type[m.get("meal_type", "Dinner")].append(m)

    # Rank each bucket once by soft score; ties broken randomly so repeat plans
    # for the same inputs still vary.
    scored: Dict[str, List[Dict]] = {}
    for mtype, pool in by_type.items():
        ranked = sorted(
            pool,
            key=lambda m: (-_soft_score(m, c, per_meal_calories), random.random()),
        )
        scored[mtype] = ranked

    substituted: set[str] = set()
    selected: List[Dict] = []
    used_ids: set = set()

    for _ in range(days):
        for meal_type in type_seq:
            pool = scored.get(meal_type) or []
            if not pool:
                # No meal of this type survived the hard filters. Substitute from
                # the whole safe set rather than silently serving a Dinner as a
                # Breakfast with no explanation.
                pool = sorted(meals, key=lambda m: (-_soft_score(m, c, per_meal_calories),
                                                    random.random()))
                if pool:
                    substituted.add(meal_type)
            if not pool:
                continue
            available = [m for m in pool if m["id"] not in used_ids] or pool
            if experiment:
                # Explore: sample from the top slice rather than always taking
                # the single best-scoring meal, so plans stay varied.
                window = available[:max(3, len(available) // 3)]
                meal = random.choice(window)
            else:
                meal = available[0]
            selected.append(meal)
            used_ids.add(meal["id"])

    for mtype in sorted(substituted):
        warnings.append(
            f"No {mtype.lower()} recipes matched your restrictions — "
            f"other meals were used for those slots."
        )
    return selected


# ---------------------------------------------------------------------------
# Day labelling
# ---------------------------------------------------------------------------

def _day_labels(days: int) -> List[str]:
    """Unique label per day.

    Plans longer than a week used to reuse Monday..Sunday verbatim, and the UI
    groups meals by that string — so a 14-day plan collapsed into 7 cards with
    both weeks' meals piled together and no way to tell them apart.
    """
    if days <= 7:
        return _DAYS_OF_WEEK[:days]
    return [f"{_DAYS_OF_WEEK[i % 7]} (Week {i // 7 + 1})" for i in range(days)]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

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
    avoid_ingredients: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """Build a meal plan.

    Returns (meal_plan, aggregated_ingredients, warnings). `warnings` lists every
    constraint we could not fully enforce — the caller MUST surface these; they
    are the difference between "your Kosher plan" and "a plan with pork in it".

    Raises NoSafeMealsError when the hard constraints (allergens, diet) exclude
    every meal.
    """
    # --- Clamp inputs -------------------------------------------------------
    warnings: list[str] = []
    days = _clamp(days, 1, MAX_DAYS, "days", warnings)
    meals_per_day = _clamp(meals_per_day, 1, MAX_MEALS_PER_DAY, "meals per day", warnings)
    household_size = _clamp(household_size, 1, MAX_HOUSEHOLD, "household size", warnings)

    print(f"[MealPlanner] {days}d × {meals_per_day} meals, household={household_size}", flush=True)

    all_meals = meals if meals is not None else _load_meals()
    if not all_meals:
        raise NoSafeMealsError("No recipes are available.")

    known_cuisines = {m.get("cuisine") for m in all_meals if m.get("cuisine")}
    c = _resolve_constraints(
        diet_restrictions, allergies, avoid_ingredients,
        health_issues, cuisines, cook_time, known_cuisines,
    )
    warnings.extend(c.warnings)

    # --- Hard filter: NO silent fallback ------------------------------------
    safe = _filter_meals(all_meals, c)
    if not safe:
        raise NoSafeMealsError(
            "No recipes match your restrictions. Try removing a dietary "
            "restriction or an avoided ingredient — we won't substitute meals "
            "that break them."
        )
    if len(safe) < 5:
        warnings.append(
            f"Only {len(safe)} recipe(s) match your restrictions, so meals will repeat."
        )

    # Cook time is labelled "Max Cook Time" in the UI, so treat it as a real
    # ceiling rather than a ranking nudge — a soft preference happily returned
    # 35-minute recipes to someone who asked for 15. Relaxed (with a warning)
    # only if the ceiling would leave nothing to choose from.
    if c.max_cook_minutes is not None:
        within = [m for m in safe if (m.get("cook_time_minutes") or 0) <= c.max_cook_minutes]
        if within:
            safe = within
        else:
            fastest = min((m.get("cook_time_minutes") or 0) for m in safe)
            warnings.append(
                f"No recipes matching your restrictions cook in under "
                f"{c.max_cook_minutes} minutes — the quickest is {fastest} minutes, "
                f"so the cook-time limit was relaxed."
            )

    if meals_per_day <= 3:
        type_seq = _TYPE_SEQUENCES.get(meals_per_day, ["Breakfast", "Lunch", "Dinner"])
    else:
        type_seq = ["Breakfast", "Lunch", "Dinner"] + ["Snack"] * (meals_per_day - 3)

    per_meal_calories = (daily_calories / meals_per_day) if daily_calories and meals_per_day else None
    selected = _select_meals(safe, days, meals_per_day, type_seq, c,
                             per_meal_calories, experiment, warnings)

    # --- Fridge contents ----------------------------------------------------
    # Tokens must be >= 3 chars and match on a word boundary. The old check was
    # `tok in key or key in tok`, so "egg" marked eggplant as already-at-home and
    # a single-letter entry marked the entire basket at home.
    fridge_tokens = {t.strip().lower() for t in _split(fridge_contents)}
    short = {t for t in fridge_tokens if len(t) < 3}
    fridge_tokens -= short
    if short:
        warnings.append(
            "Ignored too-short at-home item(s): " + ", ".join(sorted(short))
            + " (3+ characters needed to match reliably)."
        )

    day_labels = _day_labels(days)

    meal_plan: List[Dict] = []
    aggregated: Dict[str, Dict] = {}

    for i, meal in enumerate(selected):
        day_idx = i // meals_per_day
        day = day_labels[day_idx]
        meal_type = type_seq[i % meals_per_day]

        enriched_ings = []
        for ing in meal.get("ingredients", []):
            scaled_qty = ing["qty"] * household_size
            key = ing["name"].lower().strip()
            is_at_home = any(_matches_keyword(key, tok) for tok in fridge_tokens)

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
            "day_index": day_idx,       # stable sort key; `day` is a display label
            "meal_type": meal_type,
            "name": meal["name"],
            "calories": meal.get("calories", 400),
            "cook_time": f"{cook_mins} mins",
            "cook_time_minutes": cook_mins,
            "cuisine": meal.get("cuisine", ""),
            "ingredients": enriched_ings,
            "instructions": meal.get("instructions", ["Prepare ingredients.", "Cook and serve."]),
        })

    # Report calorie drift so the target isn't silently decorative.
    if daily_calories and meal_plan:
        actual = sum(m["calories"] for m in meal_plan) / days
        if abs(actual - daily_calories) / daily_calories > 0.25:
            warnings.append(
                f"Closest match averages ~{int(actual)} kcal/day against your "
                f"{int(daily_calories)} target — the catalogue doesn't have enough "
                f"recipes to hit it exactly."
            )

    print(f"[MealPlanner] {len(meal_plan)} meals, {len(aggregated)} unique ingredients, "
          f"{len(safe)}/{len(all_meals)} recipes passed hard filters.", flush=True)
    return meal_plan, aggregated, warnings


def _clamp(value: Any, lo: int, hi: int, label: str, warnings: list[str]) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = lo
    if v < lo or v > hi:
        clamped = max(lo, min(hi, v))
        warnings.append(f"{label.capitalize()} adjusted from {value} to {clamped} "
                        f"(allowed range {lo}–{hi}).")
        return clamped
    return v
