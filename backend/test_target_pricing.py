"""
Deterministic tests for target_pricing parsing + pricing logic.

These use REAL RedSky product payloads captured from redsky.target.com (titles,
prices, weight-priced items) so they exercise the exact shapes the live API
returns — but they run fully offline (no CloakBrowser / network needed), so they
work in CI. Live connectivity is exercised separately by `python target_pricing.py`.

Run:  python test_target_pricing.py   (exits non-zero on failure)
"""
from __future__ import annotations

import sys
import time as _time
import types

import target_pricing as tp
from kroger_pricing import find_best_purchase


def _product(title: str, current_retail: float, brand: str = "", tcin: str = "1") -> dict:
    """Minimal real-shape RedSky plp_search_v2 product."""
    return {
        "tcin": tcin,
        "item": {
            "product_description": {"title": title},
            "primary_brand": {"name": brand},
        },
        "price": {"current_retail": current_retail, "reg_retail": current_retail,
                  "formatted_current_price": f"${current_retail:.2f}"},
    }


# Real titles seen in RedSky responses (HTML-escaped exactly as returned).
FIXTURES: dict[str, list[dict]] = {
    "milk": [
        _product("Lactose-Free 2% Reduced Fat Ultra-Filtered Milk - 52 fl oz - Good &#38; Gather&#8482;", 4.99, "Good & Gather"),
        _product("Vitamin D Whole Milk - 1gal - Good &#38; Gather&#8482;", 3.19, "Good & Gather"),
        _product("2% Reduced Fat Milk - 0.5gal - Good &#38; Gather&#8482;", 1.89, "Good & Gather"),
        _product("Fairlife Lactose-Free Whole Milk - 52 fl oz", 5.39, "fairlife"),
    ],
    "eggs": [
        _product("Grade A Large Eggs - 18ct - Good &#38; Gather&#8482; (Packaging May Vary)", 2.19, "Good & Gather"),
        _product("Grade A Large Eggs - 12ct - Good &#38; Gather&#8482; (Packaging May Vary)", 1.49, "Good & Gather"),
        _product("Vital Farms Pasture-Raised Grade A Large Eggs - 12ct", 6.69, "Vital Farms"),
    ],
    "bananas": [
        _product("Fresh Banana - each - Good &#38; Gather&#8482;", 0.29, "Good & Gather"),
        _product("Fresh Organic Bananas - 2lb - Good &#38; Gather&#8482;", 1.79, "Good & Gather"),
    ],
    "chicken breast": [
        _product("Fresh All Natural Boneless &#38; Skinless Chicken Breast Value Pack - 2.5-5.25lbs - price per lb - Good &#38; Gather&#8482;", 2.69, "Good & Gather"),
        _product("Fresh All Natural Boneless &#38; Skinless Chicken Breast - price per lb - Good &#38; Gather&#8482;", 3.99, "Good & Gather"),
        _product("Just Bare Lightly Breaded Chicken Breast Bites - Frozen - 24oz", 10.99, "Just Bare"),
    ],
    "olive oil": [
        _product("Extra Virgin Olive Oil - 16.9oz - Good &#38; Gather&#8482;", 6.39, "Good & Gather"),
        _product("Graza Sizzle Extra Virgin Olive Oil for Cooking - 750ml", 14.29, "Graza"),
    ],
    "garbanzo beans": [
        _product("Chickpeas Garbanzo Beans - 15.5oz - Good &#38; Gather&#8482;", 0.99, "Good & Gather"),
    ],
}


def test_parse_title() -> int:
    print("=== _parse_title ===")
    cases = [
        # title, (name, size, sold_by)  — or sold_by=="WEIGHT" only
        ("Vitamin D Whole Milk - 1gal - Good &#38; Gather&#8482;",
         ("Vitamin D Whole Milk", "1gal", "UNIT")),
        ("Fairlife Lactose-Free Whole Milk - 52 fl oz",
         ("Fairlife Lactose-Free Whole Milk", "52 fl oz", "UNIT")),
        ("Grade A Large Eggs - 18ct - Good &#38; Gather&#8482; (Packaging May Vary)",
         ("Grade A Large Eggs", "18ct", "UNIT")),
        ("Fresh Banana - each - Good &#38; Gather&#8482;",
         ("Fresh Banana", "1 each", "UNIT")),
        ("Fresh Parmesan Chicken Breast Cutlets - 20oz/4ct - Good &#38; Gather&#8482;",
         ("Fresh Parmesan Chicken Breast Cutlets", "20oz", "UNIT")),
        ("Fresh All Natural Boneless &#38; Skinless Chicken Breast - price per lb - Good &#38; Gather&#8482;",
         "WEIGHT"),
    ]
    fails = 0
    for title, exp in cases:
        got = tp._parse_title(title)
        ok = (got[2] == "WEIGHT") if exp == "WEIGHT" else (got == exp)
        print(f"  [{'PASS' if ok else 'FAIL'}] {got}")
        fails += not ok
    return fails


def test_pricing() -> int:
    print("\n=== find_best_purchase on real fixtures ===")
    # term, qty, unit, max_cost, why
    checks = [
        ("milk",           1,  "gallon", 3.30, "1gal Whole Milk = $3.19"),
        ("eggs",           12, "count",  1.60, "12ct eggs = $1.49"),
        ("bananas",        3,  "pound",  4.00, "3lb bananas ~ $3.48-3.58"),
        ("chicken breast", 3,  "pound",  8.50, "weight-priced value pack 3lb*$2.69 = $8.07"),
        ("olive oil",      16, "fl oz",  6.50, "16.9oz olive oil = $6.39"),
        ("garbanzo beans", 1,  "count",  1.20, "1 can chickpeas = $0.99"),
    ]
    fails = 0
    for term, qty, unit, maxcost, why in checks:
        products = [p for p in (tp._to_kroger_format(x) for x in FIXTURES[term]) if p]
        res = find_best_purchase(term, qty, unit, products)
        if not res:
            print(f"  [FAIL] {term}: no purchase found"); fails += 1; continue
        tc = res["total_cost"]
        ok = 0 < tc <= maxcost
        print(f"  [{'PASS' if ok else 'FAIL'}] {term:16s} ${tc:6.2f} [{res['sold_by']}] "
              f"{res['description'][:34]} ({res['size_str']})  (<= ${maxcost}: {why})")
        fails += not ok
    return fails


def test_store_detection() -> int:
    print("\n=== is_target_store ===")
    cases = [("Target", True), ("SuperTarget", True),
             ("Target Optical", False), ("Walmart", False)]
    fails = 0
    for name, exp in cases:
        got = tp.is_target_store(name)
        ok = got == exp
        print(f"  [{'PASS' if ok else 'FAIL'}] {name!r} -> {got}")
        fails += not ok
    return fails


def _drive_do_pricing(price_one_behavior, max_refreshes=5):
    """Run _do_pricing with browser/network/sleep stubbed out; returns
    (prices, rotation_count)."""
    saved = {k: getattr(tp, k) for k in
             ("_ensure_ctx", "_resolve_store_id", "_price_one", "_teardown_session",
              "_bootstrap_session", "_rotate_proxy_session", "time", "MAX_IP_REFRESHES")}
    rot = {"n": 0}
    try:
        tp._ensure_ctx = lambda: None
        tp._resolve_store_id = lambda lat, lon: "9999"
        tp._teardown_session = lambda: None
        tp._bootstrap_session = lambda: None
        tp._rotate_proxy_session = lambda: rot.__setitem__("n", rot["n"] + 1)
        tp.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time)
        tp.MAX_IP_REFRESHES = max_refreshes
        tp._price_one = price_one_behavior
        _, prices = tp._do_pricing(
            {"milk": {"qty": 1, "unit": "gallon"},
             "eggs": {"qty": 12, "unit": "count"},
             "bread": {"qty": 1, "unit": "loaf"}}, 0.0, 0.0)
        return prices, rot["n"]
    finally:
        for k, v in saved.items():
            setattr(tp, k, v)


def test_ip_refresh() -> int:
    print("\n=== IP-refresh / Instacart fallback ===")
    fails = 0

    # Always blocked -> after exactly MAX_IP_REFRESHES rotations, give up (empty).
    def always_blocked(*a, **k):
        raise tp._ImpervaBlocked()
    prices, rotations = _drive_do_pricing(always_blocked, max_refreshes=5)
    ok = prices == {} and rotations == 5
    print(f"  [{'PASS' if ok else 'FAIL'}] always-blocked -> empty after 5 refreshes "
          f"(got prices={prices}, rotations={rotations})")
    fails += not ok

    # Block once mid-basket -> 1 rotation, basket still completes (progressive).
    state = {"calls": 0}
    def block_once(ingredient, qty, unit, store_id):
        state["calls"] += 1
        if state["calls"] == 2:
            raise tp._ImpervaBlocked()
        return {"total_cost": 1.0, "description": ingredient, "size_str": "1 each", "units_to_buy": 1}
    prices, rotations = _drive_do_pricing(block_once)
    ok = len(prices) == 3 and rotations == 1
    print(f"  [{'PASS' if ok else 'FAIL'}] block-once -> all priced, 1 rotation "
          f"(got {len(prices)}/3, rotations={rotations})")
    fails += not ok

    # Never blocked -> 0 rotations.
    def never_blocked(ingredient, qty, unit, store_id):
        return {"total_cost": 2.0, "description": ingredient, "size_str": "x", "units_to_buy": 1}
    prices, rotations = _drive_do_pricing(never_blocked)
    ok = len(prices) == 3 and rotations == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] never-blocked -> all priced, 0 rotations "
          f"(got {len(prices)}/3, rotations={rotations})")
    fails += not ok
    return fails


def test_proxy_rotation() -> int:
    print("\n=== proxy session rotation ===")
    saved = tp._PROXY
    try:
        tp._PROXY = "http://u-session-{session}:p@gate:7000"
        tp._rotate_proxy_session(); a = tp._current_proxy()
        tp._rotate_proxy_session(); b = tp._current_proxy()
        ok = a != b and "{session}" not in a and "{session}" not in b
        print(f"  [{'PASS' if ok else 'FAIL'}] fresh token each rotation: {a} != {b}")
        return 0 if ok else 1
    finally:
        tp._PROXY = saved


def test_search_cache() -> int:
    print("\n=== search-result TTL cache ===")
    saved = {"get": tp._redsky_get, "cache": dict(tp._search_cache)}
    calls = {"n": 0}
    try:
        tp._search_cache.clear()
        def fake_get(url):
            calls["n"] += 1
            return ('{"data":{"search":{"products":[{"tcin":"1","item":'
                    '{"product_description":{"title":"Whole Milk - 1gal - Good & Gather"},'
                    '"primary_brand":{"name":"Good & Gather"}},"price":{"current_retail":3.19}}]}}}')
        tp._redsky_get = fake_get
        r1 = tp._search("milk", "100")
        r2 = tp._search("milk", "100")   # should be served from cache
        ok = calls["n"] == 1 and r1 == r2 and len(r1) == 1
        print(f"  [{'PASS' if ok else 'FAIL'}] 2 searches -> 1 network call "
              f"(network_calls={calls['n']}, products={len(r1)})")
        return 0 if ok else 1
    finally:
        tp._redsky_get = saved["get"]
        tp._search_cache.clear()
        tp._search_cache.update(saved["cache"])


if __name__ == "__main__":
    total = (test_parse_title() + test_pricing() + test_store_detection()
             + test_ip_refresh() + test_proxy_rotation() + test_search_cache())
    print(f"\n{'ALL PASS' if total == 0 else f'{total} FAILURE(S)'}")
    sys.exit(1 if total else 0)
