"""
Deterministic tests for walmart_pricing parsing + pricing logic.

Uses REAL Walmart __NEXT_DATA__ item shapes (captured from wm_milk_fixture.json)
so they exercise the exact structures live Walmart pages return — fully offline,
no CloakBrowser or network needed.

Run:  python test_walmart_pricing.py   (exits non-zero on failure)
"""
from __future__ import annotations

import json
import os
import sys
import time as _time
import types

import walmart_pricing as wp
from kroger_pricing import find_best_purchase


# ---------------------------------------------------------------------------
# Fixtures — shapes copied from backend/.cache/wm_milk_fixture.json
# plus additional items for other ingredient tests
# ---------------------------------------------------------------------------

def _item(name: str, line_price: str, by_weight: bool = False,
          brand: str = "", seller_badge: bool = False) -> dict:
    return {
        "name": name,
        "brand": brand,
        "usItemId": "wm_" + name[:8].replace(" ", "_"),
        "hasSellerBadge": seller_badge,
        "priceInfo": {
            "linePrice": line_price,
            "linePriceDisplay": line_price,
            "itemPrice": "",
            "finalCostByWeight": by_weight,
        },
    }


MILK_FIXTURE = [
    _item("Feastables Protein Fortified Chocolate Milk, Shelf-Stable, 8 fl oz, 6 Pack", "$8.27"),
    _item("Prairie Farms Dairy Lactose Free 2% Milk Gallon", "$6.07"),
    _item("Organic Valley Grassmilk Organic Grassfed Whole Milk, 59 fl oz", "$6.67"),
    _item("Great Value Whole Vitamin D Milk, Gallon", "$3.16", brand="Great Value"),
    _item("Great Value, 2% Reduced Fat Milk, Gallon", "$3.16", brand="Great Value"),
    _item("Silk Dairy Free, Gluten Free, Unsweet Almond Milk, Plant Based Milk, 64 fl oz Half Gallon", "$3.47"),
    _item("Horizon Organic Grassfed Whole Milk, Vitamin D Whole, 59 fl oz Carton", "$7.47"),
    _item("Pecana USDA Organic Praline Pecan Milk 32 fl oz Shelf-Stable Carton", "$5.68"),
]

EGGS_FIXTURE = [
    _item("Great Value Large White Eggs, 12 Count", "$2.98", brand="Great Value"),
    _item("Great Value Large White Eggs, 24 Count", "$5.56", brand="Great Value"),
    _item("Vital Farms Pasture-Raised Grade A Large Eggs, 12 Count", "$6.99"),
]

CHICKEN_FIXTURE = [
    _item("Great Value All Natural Boneless Skinless Chicken Breasts, 5 lb", "$8.47",
          brand="Great Value"),
    _item("Tyson Frozen Boneless Skinless Chicken Breasts, 2.5 lb", "$6.47"),
    _item("Just Bare Lightly Breaded Chicken Breast Bites Frozen 24 oz", "$9.98"),
    # Third-party marketplace seller — should be filtered out
    _item("Fancy Chicken Breast, 3 lb", "$12.99", seller_badge=True),
]

BANANAS_FIXTURE = [
    _item("Fresh Bananas, Each", "$0.25"),
    _item("Organic Bananas, 2 lb bag", "$1.88"),
    _item("Fresh Bananas, 3 lb bag", "$1.78", brand="Great Value"),
]

ALL_FIXTURES: dict[str, list[dict]] = {
    "milk": MILK_FIXTURE,
    "eggs": EGGS_FIXTURE,
    "chicken breast": CHICKEN_FIXTURE,
    "bananas": BANANAS_FIXTURE,
}


# ---------------------------------------------------------------------------
# 1. Size extractor
# ---------------------------------------------------------------------------

def test_extract_size() -> int:
    print("=== _extract_size ===")
    cases = [
        # (name, expected_size)
        ("Great Value Whole Vitamin D Milk, Gallon", "1 gal"),
        ("Prairie Farms Dairy Lactose Free 2% Milk Gallon", "1 gal"),
        ("Organic Valley Grassmilk Organic Grassfed Whole Milk, 59 fl oz", "59 fl oz"),
        ("Great Value Large White Eggs, 12 Count", "12 Count"),
        ("Great Value All Natural Boneless Skinless Chicken Breasts, 5 lb", "5 lb"),
        ("Silk Dairy Free, Gluten Free, Unsweet Almond Milk, 64 fl oz Half Gallon", "64 fl oz"),
        ("Fresh Bananas, 3 lb bag", "3 lb"),
        ("Quaker Old Fashioned Rolled Oats, 18 oz", "18 oz"),
        ("Tropicana Pure Premium, Half Gallon", "0.5 gal"),
        ("Horizon Organic 2% Milk, 59 fl oz Carton", "59 fl oz"),
    ]
    fails = 0
    for name, expected in cases:
        got = wp._extract_size(name)
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] '{name[:40]}' -> '{got}' (expected '{expected}')")
        fails += not ok
    return fails


# ---------------------------------------------------------------------------
# 2. Price parser
# ---------------------------------------------------------------------------

def test_price_from_lineprice() -> int:
    print("\n=== _price_from_lineprice ===")
    cases = [
        ({"linePrice": "$3.16"}, 3.16),
        ({"linePrice": "$8.27"}, 8.27),
        ({"linePrice": "", "linePriceDisplay": "$6.07"}, 6.07),
        ({"linePrice": "", "linePriceDisplay": "", "itemPrice": "$1.25"}, 1.25),
        ({"linePrice": "$1,234.56"}, None),  # >$500 cap filters it (no grocery costs that much)
        ({"linePrice": ""}, None),
        ({}, None),
    ]
    fails = 0
    for pi, expected in cases:
        got = wp._price_from_lineprice(pi)
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {pi} -> {got} (expected {expected})")
        fails += not ok
    return fails


# ---------------------------------------------------------------------------
# 3. Item -> Kroger format conversion
# ---------------------------------------------------------------------------

def test_item_to_kroger_format() -> int:
    print("\n=== _item_to_kroger_format ===")
    fails = 0

    # Normal item — should convert
    item = _item("Great Value Whole Vitamin D Milk, Gallon", "$3.16", brand="Great Value")
    fmt = wp._item_to_kroger_format(item)
    ok = (fmt is not None and fmt["description"] == "Great Value Whole Vitamin D Milk, Gallon"
          and fmt["items"][0]["price"]["regular"] == 3.16
          and fmt["items"][0]["size"] == "1 gal"
          and fmt["items"][0]["soldBy"] == "UNIT")
    print(f"  [{'PASS' if ok else 'FAIL'}] normal gallon item: size={fmt['items'][0]['size'] if fmt else None}, price=${fmt['items'][0]['price']['regular'] if fmt else None}")
    fails += not ok

    # Marketplace seller — should be filtered
    item2 = _item("Some Brand Milk, Gallon", "$5.00", seller_badge=True)
    fmt2 = wp._item_to_kroger_format(item2)
    ok2 = fmt2 is None
    print(f"  [{'PASS' if ok2 else 'FAIL'}] marketplace seller filtered: {fmt2 is None}")
    fails += not ok2

    # No price — should be filtered
    item3 = _item("Milk", "")
    item3["priceInfo"]["linePrice"] = ""
    item3["priceInfo"]["linePriceDisplay"] = ""
    item3["priceInfo"]["itemPrice"] = ""
    fmt3 = wp._item_to_kroger_format(item3)
    ok3 = fmt3 is None
    print(f"  [{'PASS' if ok3 else 'FAIL'}] no-price item filtered: {fmt3 is None}")
    fails += not ok3

    # Weight-priced item
    item4 = _item("Fresh Ground Beef, per lb", "$4.98", by_weight=True)
    fmt4 = wp._item_to_kroger_format(item4)
    ok4 = (fmt4 is not None and fmt4["items"][0]["soldBy"] == "WEIGHT"
           and fmt4["items"][0]["size"] == "1 lb")
    print(f"  [{'PASS' if ok4 else 'FAIL'}] weight-priced item: soldBy={fmt4['items'][0]['soldBy'] if fmt4 else None}")
    fails += not ok4

    return fails


# ---------------------------------------------------------------------------
# 4. find_best_purchase on fixture data
# ---------------------------------------------------------------------------

def test_pricing() -> int:
    print("\n=== find_best_purchase on real fixtures ===")
    checks = [
        # (ingredient, qty, unit, max_cost, note)
        ("milk",           1,  "gallon", 3.25, "Great Value Whole Milk Gallon = $3.16"),
        ("eggs",           12, "count",  3.10, "Great Value 12ct eggs = $2.98"),
        ("chicken breast", 3,  "pound",  9.00, "GV 5lb=$8.47 -> 3lb portion"),
        ("bananas",        3,  "pound",  2.00, "3lb bag = $1.78"),
    ]
    fails = 0
    for term, qty, unit, maxcost, note in checks:
        raw = ALL_FIXTURES[term]
        products = [p for p in (wp._item_to_kroger_format(it) for it in raw) if p]
        res = find_best_purchase(term, qty, unit, products)
        if not res:
            print(f"  [FAIL] {term}: no purchase found  ({note})")
            fails += 1
            continue
        tc = res["total_cost"]
        ok = 0 < tc <= maxcost
        print(f"  [{'PASS' if ok else 'FAIL'}] {term:16s} ${tc:6.2f} [{res['sold_by']}] "
              f"{res['description'][:36]} ({res['size_str']})  (<= ${maxcost}: {note})")
        fails += not ok
    return fails


# ---------------------------------------------------------------------------
# 5. is_walmart_store detection
# ---------------------------------------------------------------------------

def test_store_detection() -> int:
    print("\n=== is_walmart_store ===")
    cases = [
        ("Walmart", True),
        ("Walmart Supercenter", True),
        ("Walmart Neighborhood Market", True),
        ("walmart", True),
        ("Target", False),
        ("Sam's Club", False),
    ]
    fails = 0
    for name, expected in cases:
        got = wp.is_walmart_store(name)
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name!r} -> {got}")
        fails += not ok
    return fails


# ---------------------------------------------------------------------------
# 6. IP-refresh / Instacart fallback loop
# ---------------------------------------------------------------------------

def _drive_do_pricing(price_one_behavior, max_refreshes=5):
    """Run _do_pricing with browser/network/sleep stubbed out."""
    saved = {k: getattr(wp, k) for k in
             ("_ensure_ctx", "_teardown_session", "_rotate_proxy_session",
              "_price_one", "MAX_IP_REFRESHES")}
    saved_time = wp.time
    rot = {"n": 0}
    try:
        wp._ensure_ctx = lambda: None
        wp._teardown_session = lambda: None
        wp._rotate_proxy_session = lambda: rot.__setitem__("n", rot["n"] + 1)
        wp.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time)
        wp.MAX_IP_REFRESHES = max_refreshes
        wp._price_one = price_one_behavior
        prices = wp._do_pricing(
            {"milk": {"qty": 1, "unit": "gallon"},
             "eggs": {"qty": 12, "unit": "count"},
             "bread": {"qty": 1, "unit": "loaf"}}
        )
        return prices, rot["n"]
    finally:
        for k, v in saved.items():
            setattr(wp, k, v)
        wp.time = saved_time


def test_ip_refresh() -> int:
    print("\n=== IP-refresh / Instacart fallback ===")
    fails = 0

    # Always blocked -> empty after MAX_IP_REFRESHES rotations
    def always_blocked(*a, **k):
        raise wp._Blocked("captcha")
    prices, rotations = _drive_do_pricing(always_blocked, max_refreshes=5)
    ok = prices == {} and rotations == 5
    print(f"  [{'PASS' if ok else 'FAIL'}] always-blocked -> empty after 5 refreshes "
          f"(got prices={prices}, rotations={rotations})")
    fails += not ok

    # Block once mid-basket -> 1 rotation, basket still completes (progressive)
    state = {"calls": 0}
    def block_once(ingredient, qty, unit):
        state["calls"] += 1
        if state["calls"] == 2:
            raise wp._Blocked("captcha")
        return {"total_cost": 1.0, "description": ingredient,
                "size_str": "1 each", "units_to_buy": 1}
    prices, rotations = _drive_do_pricing(block_once)
    ok = len(prices) == 3 and rotations == 1
    print(f"  [{'PASS' if ok else 'FAIL'}] block-once -> all 3 priced, 1 rotation "
          f"(got {len(prices)}/3, rotations={rotations})")
    fails += not ok

    # Never blocked -> 0 rotations
    def never_blocked(ingredient, qty, unit):
        return {"total_cost": 2.0, "description": ingredient,
                "size_str": "x", "units_to_buy": 1}
    prices, rotations = _drive_do_pricing(never_blocked)
    ok = len(prices) == 3 and rotations == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] never-blocked -> all 3 priced, 0 rotations "
          f"(got {len(prices)}/3, rotations={rotations})")
    fails += not ok
    return fails


# ---------------------------------------------------------------------------
# 7. Proxy session rotation
# ---------------------------------------------------------------------------

def test_proxy_rotation() -> int:
    print("\n=== proxy session rotation ===")
    saved = wp._PROXY
    try:
        wp._PROXY = "http://user-session-{session}:pass@gate:7000"
        wp._rotate_proxy_session(); a = wp._current_proxy()
        wp._rotate_proxy_session(); b = wp._current_proxy()
        ok = a != b and "{session}" not in a and "{session}" not in b
        print(f"  [{'PASS' if ok else 'FAIL'}] fresh token each rotation: ...{a[-20:]} != ...{b[-20:]}")
        return 0 if ok else 1
    finally:
        wp._PROXY = saved


# ---------------------------------------------------------------------------
# 8. Search TTL cache
# ---------------------------------------------------------------------------

def test_search_cache() -> int:
    print("\n=== search-result TTL cache ===")
    saved_fetch = wp._fetch_items
    saved_cache = dict(wp._search_cache)
    calls = {"n": 0}
    try:
        wp._search_cache.clear()
        def fake_fetch(term):
            calls["n"] += 1
            return [_item("Great Value Whole Vitamin D Milk, Gallon", "$3.16")]
        wp._fetch_items = fake_fetch
        r1 = wp._search("milk")
        r2 = wp._search("milk")   # cache hit
        ok = calls["n"] == 1 and r1 == r2 and len(r1) >= 1
        print(f"  [{'PASS' if ok else 'FAIL'}] 2 searches -> 1 network call "
              f"(calls={calls['n']}, products={len(r1)})")
        return 0 if ok else 1
    finally:
        wp._fetch_items = saved_fetch
        wp._search_cache.clear()
        wp._search_cache.update(saved_cache)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    total = (
        test_extract_size()
        + test_price_from_lineprice()
        + test_item_to_kroger_format()
        + test_pricing()
        + test_store_detection()
        + test_ip_refresh()
        + test_proxy_rotation()
        + test_search_cache()
    )
    print(f"\n{'ALL PASS' if total == 0 else f'{total} FAILURE(S)'}")
    sys.exit(1 if total else 0)
