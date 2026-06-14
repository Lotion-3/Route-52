"""
test_pricing.py  —  rigorous offline tests for find_best_purchase cost-minimization logic
Run with:  python test_pricing.py
No API calls; uses only mocked product dicts.
"""

import sys, io, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from kroger_pricing import find_best_purchase, _dry_oz_per_floz

# ── helpers ──────────────────────────────────────────────────────────────────

def unit_product(desc, price, size_str, promo=None):
    p = {"regular": price}
    if promo is not None:
        p["promo"] = promo
    return {"description": desc, "brand": "Test",
            "items": [{"itemId": desc, "soldBy": "UNIT", "size": size_str, "price": p}]}


def weight_product(desc, price_per_lb):
    return {"description": desc, "brand": "Test",
            "items": [{"itemId": desc, "soldBy": "WEIGHT", "size": "1 lb",
                       "price": {"regular": price_per_lb}}]}


passed = failed = 0


def check(label, result, *, cost, units, size_contains=None, tol=0.015):
    global passed, failed
    if result is None:
        print(f"  FAIL  {label}: got None (expected cost=${cost})")
        failed += 1
        return
    c_ok = abs(result["total_cost"] - cost) <= max(tol * max(cost, 0.01), 0.005)
    u_ok = abs(result["units_to_buy"] - units) < 0.011
    s_ok = size_contains is None or size_contains in result["size_str"]
    if c_ok and u_ok and s_ok:
        print(f"  PASS  {label}:  {result['units_to_buy']} x '{result['size_str']}'  = ${result['total_cost']}")
        passed += 1
    else:
        print(f"  FAIL  {label}")
        print(f"         expected  cost=${cost}  units={units}  size~={size_contains!r}")
        print(f"         got       cost=${result['total_cost']}  units={result['units_to_buy']}  size={result['size_str']!r}")
        print(f"         product:  {result['description']}")
        failed += 1


def check_none(label, result):
    global passed, failed
    if result is None:
        print(f"  PASS  {label}: correctly returned None")
        passed += 1
    else:
        print(f"  FAIL  {label}: expected None, got cost=${result['total_cost']}  ({result['description']})")
        failed += 1


# ── SECTION 1: Core cheapest-combination logic ────────────────────────────────
print("=== 1. Cheapest combination wins ===")

# 30 oz vs 2 x 12 oz
check("30oz beats 2x12oz",
    find_best_purchase("Pasta", 24.0, "oz", [
        unit_product("Box 12oz",  2.50, "12 oz"),   # 2 x $2.50 = $5.00
        unit_product("Box 30oz",  3.99, "30 oz"),   # 1 x $3.99 = $3.99  <-- cheapest
        unit_product("Box 16oz",  2.99, "16 oz"),   # 2 x $2.99 = $5.98
    ]),
    cost=3.99, units=1, size_contains="30 oz")

# Bulk family pack beats many small
check("5lb family pack beats 4x2.5lb",
    find_best_purchase("Chicken", 10.0, "lbs", [
        unit_product("Small 2.5lb",  11.99, "2.5 lb"),  # 4 x $11.99 = $47.96
        unit_product("Family 5lb",   22.99, "5 lb"),    # 2 x $22.99 = $45.98  <-- cheapest
        unit_product("Bulk 10lb",    49.99, "10 lb"),   # 1 x $49.99 = $49.99
    ]),
    cost=45.98, units=2, size_contains="5 lb")

# Large single unit cheapest even at higher per-oz
check("Big 24oz beats 7x3oz",
    find_best_purchase("Liquid", 20.0, "oz", [
        unit_product("Travel 3oz",   0.99, "3 oz"),    # ceil(20/3)=7 x $0.99 = $6.93
        unit_product("Regular 12oz", 4.99, "12 oz"),   # 2 x $4.99 = $9.98
        unit_product("Big 24oz",     5.99, "24 oz"),   # 1 x $5.99 = $5.99  <-- cheapest
    ]),
    cost=5.99, units=1, size_contains="24 oz")

# Many cheapies beat one big
check("7x$0.50 beats 1x$4.99",
    find_best_purchase("Item", 20.0, "oz", [
        unit_product("Small 3oz",    0.50, "3 oz"),    # 7 x $0.50 = $3.50  <-- cheapest
        unit_product("Big 24oz",     4.99, "24 oz"),   # 1 x $4.99 = $4.99
    ]),
    cost=3.50, units=7, size_contains="3 oz")

# Exact match on package size
check("Exact fit: 1 package needed",
    find_best_purchase("Pasta", 16.0, "oz", [
        unit_product("Box 16oz",  1.99, "16 oz"),
        unit_product("Box 32oz",  3.49, "32 oz"),
    ]),
    cost=1.99, units=1, size_contains="16 oz")

# Target smaller than smallest package (ceil gives 1)
check("Target < smallest package: buy 1 cheapest",
    find_best_purchase("Spice", 1.0, "oz", [
        unit_product("Bottle 4oz",   2.99, "4 oz"),   # <-- cheapest 1-pkg
        unit_product("Bottle 8oz",   4.49, "8 oz"),
    ]),
    cost=2.99, units=1, size_contains="4 oz")

# ── SECTION 2: WEIGHT vs UNIT ─────────────────────────────────────────────────
print("\n=== 2. WEIGHT vs UNIT ===")

check("WEIGHT wins over UNIT when cheaper",
    find_best_purchase("Beef", 2.0, "lbs", [
        weight_product("Loose beef",     4.99),         # 2.0 lbs x $4.99 = $9.98  <-- cheapest
        unit_product("Pack 1.5lb",       8.99, "1.5 lb"), # 2 x $8.99 = $17.98
        unit_product("Pack 3lb",        14.99, "3 lb"),   # 1 x $14.99 = $14.99
    ]),
    cost=round(2.0 * 4.99, 2), units=2.0)

check("UNIT wins over WEIGHT when cheaper",
    find_best_purchase("Chicken", 3.0, "lbs", [
        weight_product("Loose chicken",  6.99),             # 3 lbs x $6.99 = $20.97
        unit_product("Frozen 3lb",       8.99, "3 lb"),     # 1 x $8.99  <-- cheapest
        unit_product("Frozen 5lb",      13.99, "5 lb"),     # 1 x $13.99
    ]),
    cost=8.99, units=1, size_contains="3 lb")

# WEIGHT handles fractional target with no rounding
check("WEIGHT exact fractional (0.75 lb)",
    find_best_purchase("Shrimp", 0.75, "lbs", [
        weight_product("Loose shrimp",   8.99),             # 0.75 x $8.99 = $6.74  <-- cheapest
        unit_product("Bag 1lb",          9.99, "1 lb"),     # 1 x $9.99
    ]),
    cost=round(0.75 * 8.99, 2), units=0.75)

# Multiple WEIGHT options — picks cheaper rate
check("WEIGHT: cheaper rate wins",
    find_best_purchase("Produce", 1.0, "lbs", [
        weight_product("Pricey loose",   3.99),
        weight_product("Cheap loose",    1.29),  # <-- cheaper
    ]),
    cost=1.29, units=1.0)

# ── SECTION 3: Count items ────────────────────────────────────────────────────
print("\n=== 3. Count items ===")

check("18-pack cheapest for 36 eggs",
    find_best_purchase("Eggs", 36.0, "whole", [
        unit_product("Dozen 12ct",   3.99, "12 ct"),  # 3 x $3.99 = $11.97
        unit_product("18-Pack",      5.49, "18 ct"),  # 2 x $5.49 = $10.98  <-- cheapest
        unit_product("2-Dozen 24ct", 7.99, "24 ct"),  # 2 x $7.99 = $15.98
    ]),
    cost=10.98, units=2, size_contains="18 ct")

check("Exact count fit (8 tortillas, 8-ct pack)",
    find_best_purchase("Tortillas", 8.0, "whole", [
        unit_product("Pack 8ct",  2.99, "8 ct"),
        unit_product("Pack 10ct", 3.49, "10 ct"),
    ]),
    cost=2.99, units=1, size_contains="8 ct")

check("15-pc bag cheaper than 6 singles",
    find_best_purchase("Limes", 6.0, "whole", [
        unit_product("Single lime",   0.89, "1 ct"),    # 6 x $0.89 = $5.34
        unit_product("Bag 15pc",      1.79, "15 pc"),   # 1 x $1.79 = $1.79  <-- cheapest
    ]),
    cost=1.79, units=1, size_contains="15 pc")

check("Need ceil even for count items",
    find_best_purchase("Items", 7.0, "whole", [
        unit_product("4-pack", 2.00, "4 ct"),  # ceil(7/4)=2 x $2.00 = $4.00
        unit_product("6-pack", 2.99, "6 ct"),  # ceil(7/6)=2 x $2.99 = $5.98
        unit_product("8-pack", 2.49, "8 ct"),  # 1 x $2.49 = $2.49  <-- cheapest
    ]),
    cost=2.49, units=1, size_contains="8 ct")

# ── SECTION 4: Volume targets ─────────────────────────────────────────────────
print("\n=== 4. Volume targets ===")

check("Full gallon cheaper than 2 half-gallons",
    find_best_purchase("Milk", 1.0, "gal", [
        unit_product("Half gal", 2.49, "1/2 gal"),  # 2 x $2.49 = $4.98
        unit_product("Full gal", 3.99, "1 gal"),    # 1 x $3.99 = $3.99  <-- cheapest
    ]),
    cost=3.99, units=1, size_contains="1 gal")

check("2 half-gallons cheaper than 1 full gallon",
    find_best_purchase("Milk", 1.0, "gal", [
        unit_product("Half gal", 1.79, "1/2 gal"),  # 2 x $1.79 = $3.58  <-- cheapest
        unit_product("Full gal", 4.99, "1 gal"),    # 1 x $4.99
    ]),
    cost=3.58, units=2, size_contains="1/2 gal")

# 2 cups = 16 fl oz; 8.45 fl oz bottle needs 2; 17 fl oz bottle needs 1
check("17 fl oz bottle beats 2x8.45oz for 2-cup target",
    find_best_purchase("Oil", 2.0, "cups", [
        unit_product("Small 8.45 fl oz",  4.99, "8.45 fl oz"),  # 2 x $4.99 = $9.98
        unit_product("Medium 17 fl oz",   7.99, "17 fl oz"),    # 1 x $7.99 = $7.99  <-- cheapest
        unit_product("Large 34 fl oz",   12.99, "34 fl oz"),    # 1 x $12.99
    ]),
    cost=7.99, units=1, size_contains="17 fl oz")

check("qt beats 2xpt when cheaper",
    find_best_purchase("Cream", 1.0, "qt", [
        unit_product("Pint", 2.99, "1 pt"),   # 2 x $2.99 = $5.98
        unit_product("Quart", 4.49, "1 qt"),  # 1 x $4.49  <-- cheapest
    ]),
    cost=4.49, units=1, size_contains="1 qt")

# ── SECTION 5: Dry goods (volume → mass cross-family) ────────────────────────
print("\n=== 5. Dry goods: cups/tsp -> oz cross-family ===")

density_oats = _dry_oz_per_floz("Rolled oats")
tgt_oz_oats = 2.0 * 8.0 * density_oats   # 2 cups in fl_oz * density
print(f"  [oats density: {density_oats:.4f} oz/fl_oz  →  2 cups = {tgt_oz_oats:.2f} oz]")

# All 3 require 1 package; cheapest wins
check("Smallest oats canister wins (all need 1 pkg)",
    find_best_purchase("Rolled oats", 2.0, "cups", [
        unit_product("Canister 8oz",  2.49, "8 oz"),   # 1 x $2.49  <-- cheapest
        unit_product("Regular 18oz",  4.99, "18 oz"),
        unit_product("Family 42oz",   8.99, "42 oz"),
    ]),
    cost=2.49, units=1, size_contains="8 oz")

density_g = _dry_oz_per_floz("Garlic powder")
tgt_fl = 10.0 / 6.0   # 10 tsp in fl_oz
tgt_oz_g = tgt_fl * density_g
print(f"  [garlic powder density: {density_g:.4f} oz/fl_oz  →  10 tsp = {tgt_oz_g:.4f} oz]")

# Large spice jar may require only 1 purchase; compare costs
# 10 tsp = 1.667 fl_oz; garlic powder density ≈ 0.4375 oz/fl_oz → target ≈ 0.73 oz
# 0.5oz bottle: ceil(0.73/0.5)=2 → $3.98  <-- cheaper than 1×$3.99
# 2.37oz bottle: 1 → $3.99
# Function correctly picks the cheapest TOTAL, which is 2×$1.99=$3.98
_expected_g_units = math.ceil(tgt_oz_g / 0.5)
_expected_g_cost  = round(_expected_g_units * 1.99, 2)
check("Cheapest total for garlic powder: 2x0.5oz beats 1x2.37oz",
    find_best_purchase("Garlic powder", 10.0, "tsp", [
        unit_product("Tiny 0.5oz",   1.99, "0.5 oz"),
        unit_product("Std 2.37oz",   3.99, "2.37 oz"),
        unit_product("Bulk 8oz",     4.99, "8 oz"),
    ]),
    cost=_expected_g_cost, units=_expected_g_units, size_contains="0.5 oz")

# ── SECTION 6: Cans / jars ────────────────────────────────────────────────────
print("\n=== 6. Cans / jars ===")

check("Cheapest can wins for 4-can target",
    find_best_purchase("Canned black beans", 4.0, "cans", [
        unit_product("Generic 15.5oz",  1.29, "15.5 oz"),  # ceil(4*15.5/15.5)=4 x $1.29=$5.16  <-- cheapest
        unit_product("Premium 15.5oz",  1.79, "15.5 oz"),  # 4 x $1.79=$7.16
        unit_product("Large 31oz",      2.99, "31 oz"),    # ceil(62/31)=2 x $2.99=$5.98
    ]),
    cost=round(4 * 1.29, 2), units=4)

check("Single large can cheapest",
    find_best_purchase("Canned black beans", 4.0, "cans", [
        unit_product("Small 8oz",   0.89, "8 oz"),    # ceil(62/8)=8 x $0.89=$7.12
        unit_product("Std 15.5oz",  1.69, "15.5 oz"), # 4 x $1.69=$6.76
        unit_product("Big 62oz",    4.49, "62 oz"),   # ceil(62/62)=1 x $4.49=$4.49  <-- cheapest
    ]),
    cost=4.49, units=1, size_contains="62 oz")

# ── SECTION 7: Promo price ────────────────────────────────────────────────────
print("\n=== 7. Promo price ===")

check("Promo price used when lower than regular",
    find_best_purchase("Ground beef", 2.0, "lbs", [
        unit_product("Beef 1lb", 7.49, "1 lb", promo=4.49),  # promo: 2 x $4.49=$8.98  <-- cheapest
        unit_product("Beef 2lb", 9.99, "2 lb"),              # 1 x $9.99
    ]),
    cost=8.98, units=2)

check("Regular used when promo is higher",
    find_best_purchase("Beef", 1.0, "lbs", [
        unit_product("Beef 1lb", 5.99, "1 lb", promo=7.99),  # promo higher -> use regular $5.99
    ]),
    cost=5.99, units=1)

# ── SECTION 8: Multiple options same total cost ───────────────────────────────
print("\n=== 8. Equal-cost tiebreaker ===")

r = find_best_purchase("Pasta", 16.0, "oz", [
    unit_product("Box A 16oz", 2.99, "16 oz"),
    unit_product("Box B 16oz", 2.99, "16 oz"),
])
if r is not None and abs(r["total_cost"] - 2.99) < 0.01 and abs(r["units_to_buy"] - 1) < 0.01:
    print(f"  PASS  Tiebreaker: returned valid option at ${r['total_cost']}")
    passed += 1
else:
    print(f"  FAIL  Tiebreaker: {r}")
    failed += 1

# ── SECTION 9: Edge cases ─────────────────────────────────────────────────────
print("\n=== 9. Edge cases ===")

check_none("Empty product list",
    find_best_purchase("X", 1.0, "oz", []))

check_none("Product with no price",
    find_best_purchase("X", 5.0, "oz", [
        {"description": "No Price", "brand": "T",
         "items": [{"itemId": "x", "soldBy": "UNIT", "size": "12 oz", "price": {}}]}
    ]))

check_none("All products wrong unit family (count target, mass products)",
    find_best_purchase("Eggs", 12.0, "whole", [
        unit_product("Flour 5lb", 3.99, "5 lb"),
    ]))

check_none("Unrecognized recipe unit",
    find_best_purchase("X", 1.0, "furlongs", [
        unit_product("Prod", 1.99, "8 oz")
    ]))

check("Target well under 1 package (buy 1)",
    find_best_purchase("Spice", 0.1, "oz", [
        unit_product("Big Bottle", 3.99, "4 oz"),
    ]),
    cost=3.99, units=1)

check("Many units needed (large target)",
    find_best_purchase("Rice", 10.0, "lbs", [
        unit_product("Bag 2lb",   2.99, "2 lb"),   # ceil(160/32)=5 x $2.99=$14.95
        unit_product("Bag 5lb",   5.99, "5 lb"),   # ceil(160/80)=2 x $5.99=$11.98  <-- cheapest
        unit_product("Bag 10lb", 11.99, "10 lb"),  # 1 x $11.99
    ]),
    cost=11.98, units=2, size_contains="5 lb")

check("Product with unparseable size treated as 1 ct (volume target skips it)",
    find_best_purchase("Sauce", 8.0, "fl oz", [
        unit_product("Parseable 16 fl oz",    3.99, "16 fl oz"),
        unit_product("Unparseable size",       2.99, "variable"),  # treated as 1 ct -- incompatible
    ]),
    cost=3.99, units=1)

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"  Results: {passed} passed,  {failed} failed  ({passed + failed} total)")
if failed == 0:
    print("  All tests passed.")
else:
    print("  SOME TESTS FAILED.")
print("=" * 60)
