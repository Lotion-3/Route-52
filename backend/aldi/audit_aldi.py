"""
Full audit of ALDI pricing quality (Houston TX).
Shows every ingredient with matched product name, price, size.
"""
import json, pathlib
from aldi_pricing import price_all_aldi

meals_path = pathlib.Path(__file__).parent / "meals.json"
meals_data = json.loads(meals_path.read_text(encoding="utf-8"))
seen = {}
for meal in meals_data[:35]:
    for ing in meal.get("ingredients", []):
        name = ing["name"]
        if name not in seen:
            seen[name] = {"qty": float(ing.get("qty", 1)), "unit": ing.get("unit", "whole")}
        if len(seen) >= 78:
            break
    if len(seen) >= 78:
        break

INGREDIENTS = seen
print(f"Auditing {len(INGREDIENTS)} ingredients at ALDI (Houston TX)")

store_name, store_id, prices = price_all_aldi(INGREDIENTS, 29.7515, -95.3615)

hits = [(n, INGREDIENTS[n]["qty"], INGREDIENTS[n]["unit"], prices[n])
        for n in INGREDIENTS if n in prices]
misses = [n for n in INGREDIENTS if n not in prices]

print(f"\nALDI AUDIT — {store_name} (shopId={store_id})")
print(f"PRICED {len(hits)}/{len(INGREDIENTS)}")
print("=" * 100)
print(f"{'Ingredient':<32} {'Qty':>5} {'Unit':<8} {'Cost':>7}  {'Product matched':<45}  Size")
print("-" * 100)
for n, q, u, res in sorted(hits, key=lambda x: x[0]):
    cost = res.get("total_cost", 0)
    desc = res.get("description", "")[:45]
    sz = res.get("size_str", "")
    print(f"{n:<32} {q:>5.1f} {u:<8} ${cost:>5.2f}  {desc:<45}  {sz}")

if misses:
    print(f"\nMISSED ({len(misses)}):")
    for n in sorted(misses):
        print(f"  {n} ({INGREDIENTS[n]['qty']} {INGREDIENTS[n]['unit']})")
