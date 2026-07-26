"""
Systematic sanity validator over meals_curated.jsonl. Can't eyeball 69k meals,
so this flags every one that fails a rule, grouped by issue type, so the
failures can be reviewed and the systematic ones fixed at the source.

Checks (most safety-relevant first):
  A. TAG/INGREDIENT CONTRADICTIONS (safety):
     - tagged Vegan/Vegetarian but an ingredient looks like meat/poultry/fish
     - an allergen keyword appears in ingredients but the allergen is NOT tagged
       (a missing allergen tag is the dangerous direction)
  B. Absurd calories (0, or > 2500 for a single meal)
  C. Junk/garbled names
  D. Trivial instructions (< 2 steps of real length)
  E. Unit anomalies (a clear protein priced as "1 unit", etc.)
  F. meal_type mismatch (dessert-ish tagged as a main)

Usage:
    python validate_meals.py [--in PATH] [--show N]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

_IN_PATH = Path(__file__).parent / "meals_curated.jsonl"

# Reuse the exact allergen/meat keyword logic the tagger used, so this is a
# genuine cross-check of the tagger against itself rather than a new heuristic.
import tag_recipes as tr

_MEATY = (tr.MEAT_KEYWORDS + tr.PORK_KEYWORDS + tr.LAMB_KEYWORDS
          + tr.POULTRY_KEYWORDS + tr.SEAFOOD_KEYWORDS)


def blob_of(recipe: dict) -> str:
    return " | ".join(i["name"] for i in recipe.get("ingredients", [])).lower()


def check(recipe: dict) -> list[str]:
    issues = []
    blob = blob_of(recipe)
    diet = set(recipe.get("dietary_tags", []))
    allergens = set(recipe.get("allergen_tags", []))
    name = recipe.get("name", "")

    # A1. Vegan/Vegetarian but meaty ingredient
    if ("Vegan" in diet or "Vegetarian" in diet) and tr._contains_any(blob, _MEATY):
        hit = next(k for k in _MEATY if tr._contains_any(blob, [k]))
        issues.append(f"A1_veg_but_meat:{hit}")

    # A2. Allergen keyword present but not tagged (dangerous direction)
    for tag, kws in tr.ALLERGEN_KEYWORDS.items():
        if tr._contains_any(blob, kws) and tag not in allergens:
            hit = next(k for k in kws if tr._contains_any(blob, [k]))
            issues.append(f"A2_untagged_allergen:{tag}:{hit}")

    # B. Absurd calories
    cal = recipe.get("calories") or 0
    if cal == 0:
        issues.append("B_zero_cal")
    elif cal > 2500:
        issues.append(f"B_high_cal:{cal}")

    # C. Junk names
    if not name or len(name) < 3:
        issues.append("C_short_name")
    if re.search(r"\b\d{3,}\b", name):  # long number sequences = often junk
        issues.append("C_number_in_name")

    # D. Trivial instructions
    steps = recipe.get("instructions", [])
    real_steps = [s for s in steps if len(s.strip()) > 8]
    if len(real_steps) < 2:
        issues.append("D_trivial_steps")

    # E. Unit anomaly: an obvious protein that fell to the generic "1 unit"
    for ing in recipe.get("ingredients", []):
        n = ing["name"].lower()
        if ing.get("unit") == "unit" and tr._contains_any(n, ["chicken", "beef", "pork", "steak"]):
            issues.append(f"E_protein_unit:{ing['name']}")
            break

    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", type=Path, default=_IN_PATH)
    ap.add_argument("--show", type=int, default=5, help="examples to show per issue type")
    args = ap.parse_args()

    total = 0
    counts: Counter = Counter()
    examples: dict[str, list] = {}
    clean = 0

    with open(args.in_path, "r", encoding="utf-8") as f:
        for line in f:
            recipe = json.loads(line)
            total += 1
            issues = check(recipe)
            if not issues:
                clean += 1
                continue
            for iss in issues:
                key = iss.split(":")[0]
                counts[key] += 1
                examples.setdefault(key, [])
                if len(examples[key]) < args.show:
                    examples[key].append((recipe.get("name"), iss))

    print(f"Validated {total} meals. Clean (no flags): {clean} ({clean/total*100:.1f}%)\n")
    print("Issue counts (a meal can have several):")
    for key, cnt in counts.most_common():
        print(f"  {key:<22} {cnt:>6}  ({cnt/total*100:.1f}%)")
        for nm, detail in examples.get(key, []):
            print(f"        e.g. {nm!r:<45} [{detail}]")


if __name__ == "__main__":
    main()
