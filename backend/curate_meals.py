"""
Curates a quality-filtered subset from recipes_ready_to_merge.jsonl for
actual meals.json merging. Does NOT touch or delete the source file — this
only reads it and writes a new, smaller file. The full 83k+ tagged/quantified
set stays intact as the source of record.

Filtering, not deletion of source data:
  - Drops recipes with <3 ingredients (761/83781 — almost always a
    condiment/sauce base, not a standalone meal) from the CURATED set only.
  - Drops recipes tagged purely as beverages/cocktails (not meals).
  - Cleans formatting noise (collapses the double/triple-space artifacts
    Food.com's scrape left where punctuation was stripped from titles,
    e.g. "1 Brownies In The World    Best Ever").
  - De-duplicates near-identical resubmissions: groups by
    (meal_type, first 3 sorted ingredient keywords) and keeps only the
    best-formed few per group, rather than every "chocolate chip cookies"
    variant a different submitter uploaded — this is the "use the messy
    ones as inspiration to keep one correct one" step: within each group,
    the best-scored (cleanest name, reasonable cook time, reasonable
    ingredient count) representative survives, the rest are excluded from
    the curated set but remain untouched in the source file.

Usage:
    python curate_meals.py [--in PATH] [--out PATH] [--per-group-cap N]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

_IN_PATH = Path(__file__).parent / "recipes_ready_to_merge.jsonl"
_RAW_PATH = Path(__file__).parent / "recipes_raw.jsonl"
_OUT_PATH = Path(__file__).parent / "meals_curated.jsonl"

_NON_MEAL_TAGS = {"beverages", "cocktails"}
_MIN_INGREDIENTS = 3
_MAX_INGREDIENTS = 20
_WHITESPACE_RE = re.compile(r"\s{2,}")

# A meal has at least one of these "substantial base" units; a rub / spice mix /
# marinade / dressing is entirely small-amount flavorings (tsp/tbsp/cloves).
_SUBSTANTIAL_UNITS = {"lb", "cup", "cups", "oz", "can", "whole", "slices",
                      "each", "links", "stalks"}
_MAX_CALORIES = 2000  # a single serving over this is Food.com per-recipe/bad data

# HARD non-meal names — a "rub"/"marinade"/"frosting" is never a standalone
# meal, even if it contains sugar (which would otherwise give it a "cup" base).
# Deliberately excludes ambiguous words: "dressing" (also a stuffing side),
# "sauce"/"dip" (can qualify a real dish, e.g. "Chicken with Peanut Sauce").
_HARD_NONMEAL_RE = re.compile(
    r"\b(rub|seasoning|spice (?:mix|blend|rub)|spice-mix|marinade|vinaigrette|"
    r"glaze|frosting|icing|jam|jelly|relish|chutney|brine|seasoned salt|"
    r"dry rub|spice paste|herb paste)\b", re.I)

# SOFT condiment words — only reject if the item ALSO has no substantial base,
# so "Chicken With Mustard Sauce" (chicken=lb) survives but "Honey Mustard
# Sauce" (all flavorings) does not.
_SOFT_CONDIMENT_RE = re.compile(r"\b(dressing|dipping sauce|dip)\b", re.I)


def _has_substantial_base(recipe: dict) -> bool:
    return any(i.get("unit") in _SUBSTANTIAL_UNITS for i in recipe.get("ingredients", []))


def _real_step_count(recipe: dict) -> int:
    return sum(1 for s in recipe.get("instructions", []) if len(s.strip()) > 8)


def _is_non_meal(recipe: dict) -> bool:
    """True if this is a condiment/seasoning/sauce component, not a meal."""
    name = recipe.get("name", "")
    if _HARD_NONMEAL_RE.search(name):
        return True
    if _has_substantial_base(recipe):
        return False
    # No substantial base: drop if it's condiment-named or has trivial steps
    # (a real dessert/snack/side without a "base" unit usually has >2 steps and
    # no condiment word, so it survives).
    return bool(_SOFT_CONDIMENT_RE.search(name)) or _real_step_count(recipe) <= 2


def clean_name(name: str) -> str:
    return _WHITESPACE_RE.sub(" ", name).strip()


def quality_score(recipe: dict) -> float:
    """Higher is better-formed. Used to pick the survivor within a
    near-duplicate group, not as a hard pass/fail filter."""
    score = 0.0
    n_ing = len(recipe.get("ingredients", []))
    # Prefer a moderate ingredient count (too few = incomplete, too many =
    # unwieldy for a weekly plan).
    score -= abs(n_ing - 8)
    cook = recipe.get("cook_time_minutes") or 0
    if 10 <= cook <= 60:
        score += 2
    # Fewer generic "1 unit" quantity fallbacks = more of the ingredients
    # hit a real category default, i.e. more typical/recognizable items.
    fallback_count = sum(1 for i in recipe.get("ingredients", []) if i.get("unit") == "unit")
    score -= fallback_count * 0.5
    # Shorter, cleaner-looking names over run-on/garbled ones.
    score -= len(recipe.get("name", "")) * 0.01
    return score


def passes_hard_filters(recipe: dict, source_tags: set[str]) -> bool:
    n_ing = len(recipe.get("ingredients", []))
    if n_ing < _MIN_INGREDIENTS or n_ing > _MAX_INGREDIENTS:
        return False
    if source_tags & _NON_MEAL_TAGS:
        return False
    if not recipe.get("name"):
        return False
    if _is_non_meal(recipe):
        return False
    # Calories must be present and plausible for a single serving. 0/None is
    # missing data; > _MAX_CALORIES is Food.com per-whole-recipe or bad data.
    cal = recipe.get("calories") or 0
    if cal <= 0 or cal > _MAX_CALORIES:
        return False
    return True


def group_key(recipe: dict) -> tuple:
    ing_names = sorted(i["name"] for i in recipe.get("ingredients", []))[:3]
    return (recipe.get("meal_type"), tuple(ing_names))


def _load_raw_tag_index(raw_path: Path) -> dict[str, set[str]]:
    """id -> set(Food.com tags), so the non-meal (beverages/cocktails) filter
    can actually check the original tags — tag_recipes.py's output only kept
    the derived dietary/allergen/health/meal_type/cuisine tags, not these."""
    index: dict[str, set[str]] = {}
    with open(raw_path, "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rid = str(r.get("id"))
            if rid:
                index[rid] = set(r.get("tags") or [])
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", type=Path, default=_IN_PATH)
    ap.add_argument("--raw", dest="raw_path", type=Path, default=_RAW_PATH)
    ap.add_argument("--out", type=Path, default=_OUT_PATH)
    ap.add_argument("--per-group-cap", type=int, default=2,
                     help="max recipes kept per (meal_type, similar-ingredients) group")
    args = ap.parse_args()

    print("[curate_meals] Loading raw Food.com tags for the non-meal filter...", flush=True)
    raw_tags = _load_raw_tag_index(args.raw_path)

    groups: dict[tuple, list[dict]] = defaultdict(list)
    total_read = 0
    dropped_hard_filter = 0

    with open(args.in_path, "r", encoding="utf-8") as fin:
        for line in fin:
            recipe = json.loads(line)
            total_read += 1
            recipe["name"] = clean_name(recipe["name"])
            # recipe["id"] is "kaggle-<original id>" — strip the prefix to
            # look up the original Food.com tags for the non-meal filter.
            orig_id = str(recipe.get("id", "")).removeprefix("kaggle-")
            source_tags = raw_tags.get(orig_id, set())
            if not passes_hard_filters(recipe, source_tags):
                dropped_hard_filter += 1
                continue
            # meal_type sanity: a Lunch/Dinner under ~150 cal is really a
            # side/dip/snack, not a main (found via the final review — e.g. a
            # 45-cal "Dinner" dip). Reclassify to Snack so it's only offered in
            # the snack slot rather than as someone's dinner.
            if recipe.get("meal_type") in ("Lunch", "Dinner") and (recipe.get("calories") or 0) < 150:
                recipe["meal_type"] = "Snack"
            groups[group_key(recipe)].append(recipe)

    written = 0
    with open(args.out, "w", encoding="utf-8") as fout:
        for key, members in groups.items():
            members.sort(key=quality_score, reverse=True)
            for m in members[: args.per_group_cap]:
                fout.write(json.dumps(m, ensure_ascii=False) + "\n")
                written += 1

    print(f"[curate_meals] Read {total_read}, dropped {dropped_hard_filter} on hard filters "
          f"(ingredient count), {len(groups)} groups formed, kept {written} after "
          f"per-group cap={args.per_group_cap}.", flush=True)
    print(f"[curate_meals] Source file untouched: {args.in_path}", flush=True)
    print(f"[curate_meals] Curated output: {args.out}", flush=True)


if __name__ == "__main__":
    main()
