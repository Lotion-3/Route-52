"""
Live store pricing tests — runs against real retailer APIs with a real browser.

PURPOSE
-------
This is the canonical integration test to run after touching any direct-pricing
module (target_pricing.py, walmart_pricing.py, …). It verifies:
  1. Prices come back (not empty / not all None).
  2. Prices are in a sane range (grocery sanity: $0.10 – $200 per basket).
  3. Cross-region price differences are detected (confirming store resolution
     is live, not returning a cached default everywhere).
  4. A standard basket of common ingredients is fully priced (no ingredient
     returning None for every city).

USAGE
-----
    python test_live_stores.py                   # all stores, all cities
    python test_live_stores.py walmart           # only Walmart
    python test_live_stores.py target            # only Target
    python test_live_stores.py walmart --fast    # first 3 cities only

PASS/FAIL
---------
The test exits non-zero if any HARD assertion fails. Hard assertions:
  - At least MIN_PRICED_FRACTION of the basket is priced in every city.
  - Every returned price is within PRICE_SANITY_RANGE.
  - At least one ingredient shows a price difference across cities
    (detects "same price everywhere" → likely not doing live store lookup).

Soft assertions (printed as WARN, not a failure):
  - Individual ingredients that come back unpriced in some cities.

ADDING A NEW STORE
------------------
Add an entry to STORE_CONFIGS below. Provide:
  - key: short identifier used on the CLI and in reports
  - label: human display name
  - fn: callable(ingredients, lat, lon) -> (name, store_id, prices)
  - shutdown: callable() to close its browser on exit (may be no-op)
  - skip_reason: non-empty string to skip the store (e.g. "needs residential proxy")
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Standard basket — used for every store / every city
# ---------------------------------------------------------------------------

BASKET = {
    "milk":           {"qty": 1,  "unit": "gallon"},
    "eggs":           {"qty": 12, "unit": "count"},
    "bananas":        {"qty": 3,  "unit": "pound"},
    "chicken breast": {"qty": 3,  "unit": "pound"},
    "white rice":     {"qty": 5,  "unit": "pound"},
    "olive oil":      {"qty": 1,  "unit": "count"},
    "bread":          {"qty": 1,  "unit": "loaf"},
}

# ---------------------------------------------------------------------------
# Cities — geographically spread to catch regional price variation
# ---------------------------------------------------------------------------

CITIES = [
    # (label, lat, lon)
    ("New York, NY",         40.7128,  -74.0060),
    ("Los Angeles, CA",      34.0522, -118.2437),
    ("Chicago, IL",          41.8781,  -87.6298),
    ("Houston, TX",          29.7604,  -95.3698),
    ("Phoenix, AZ",          33.4484, -112.0740),
    ("Philadelphia, PA",     39.9526,  -75.1652),
    ("San Antonio, TX",      29.4241,  -98.4936),
    ("San Diego, CA",        32.7157, -117.1611),
    ("Dallas, TX",           32.7767,  -96.7970),
    ("Seattle, WA",          47.6062, -122.3321),
    ("Denver, CO",           39.7392, -104.9903),
    ("Atlanta, GA",          33.7490,  -84.3880),
]

# Fast mode: only use the first N cities
FAST_CITIES = 3

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_PRICED_FRACTION = 0.60   # at least 60% of basket ingredients must price
PRICE_SANITY_MIN = 0.10      # $/basket-unit floor
PRICE_SANITY_MAX = 200.0     # $/basket-unit ceiling
REGIONAL_DIFF_MIN = 0.01     # two cities must differ by at least this for "regional prices detected"


# ---------------------------------------------------------------------------
# Store registry
# ---------------------------------------------------------------------------

@dataclass
class StoreConfig:
    key: str
    label: str
    fn: Callable                        # fn(ingredients, lat, lon) -> (name, store_id, prices)
    shutdown_fn: Callable = field(default=lambda: None)
    skip_reason: str = ""               # non-empty → skip
    regional_prices: bool = True        # False for stores with national/flat online pricing (Walmart)
    max_ip_block_cities: int = 0        # CloakBrowser stores allow N cities to hit the IP block ceiling
                                        # without failing — expected without a residential proxy


def _build_configs() -> list[StoreConfig]:
    cfgs = []

    try:
        import target_pricing
        cfgs.append(StoreConfig(
            key="target",
            label="Target (RedSky via CloakBrowser)",
            fn=target_pricing.price_all_target,
            shutdown_fn=target_pricing.shutdown,
            # CloakBrowser defeats Imperva's fingerprint check but not IP reputation.
            # Each test run hammers the same exit IP → Imperva degrades it.
            # Allow up to 2 cities to be fully blocked before flagging as a test failure.
            # In production with CLOAK_PROXY (residential) this number should be 0.
            max_ip_block_cities=2,
        ))
    except ImportError as e:
        cfgs.append(StoreConfig(key="target", label="Target", fn=lambda *a: (None, None, {}),
                                skip_reason=f"import error: {e}"))

    try:
        import walmart_pricing
        cfgs.append(StoreConfig(
            key="walmart",
            label="Walmart (NEXT_DATA via CloakBrowser)",
            fn=walmart_pricing.price_all_walmart,
            shutdown_fn=walmart_pricing.shutdown,
            regional_prices=False,  # walmart.com uses national online pricing; identical prices everywhere is correct
        ))
    except ImportError as e:
        cfgs.append(StoreConfig(key="walmart", label="Walmart", fn=lambda *a: (None, None, {}),
                                skip_reason=f"import error: {e}"))

    return cfgs


# ---------------------------------------------------------------------------
# Per-city result
# ---------------------------------------------------------------------------

@dataclass
class CityResult:
    city: str
    store_label: str
    store_id: Optional[str]
    prices: dict        # ingredient -> result dict
    elapsed: float
    error: Optional[str] = None

    @property
    def priced_ingredients(self) -> list[str]:
        return [k for k, v in self.prices.items() if v and v.get("total_cost", 0) > 0]

    @property
    def fraction_priced(self) -> float:
        return len(self.priced_ingredients) / len(BASKET)


# ---------------------------------------------------------------------------
# Run one store × all cities
# ---------------------------------------------------------------------------

def run_store(cfg: StoreConfig, cities: list[tuple]) -> list[CityResult]:
    results: list[CityResult] = []
    for city_label, lat, lon in cities:
        print(f"  [{cfg.key}] {city_label} ({lat:.2f}, {lon:.2f}) ... ", end="", flush=True)
        t0 = time.time()
        try:
            _, store_id, prices = cfg.fn(BASKET, lat, lon)
            elapsed = time.time() - t0
            results.append(CityResult(city_label, cfg.label, store_id, prices or {}, elapsed))
            n = len([v for v in (prices or {}).values() if v])
            print(f"  {n}/{len(BASKET)} priced  store={store_id}  {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            results.append(CityResult(city_label, cfg.label, None, {}, elapsed, error=str(e)))
            print(f"  ERROR: {e}")
    return results


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def assert_store_results(cfg: StoreConfig, results: list[CityResult]) -> int:
    """Returns number of hard failures."""
    failures = 0
    city_prices: dict[str, dict] = {}  # ingredient -> {city: total_cost}

    ip_block_cities = 0  # cities that returned 0 prices after exhausting IP refreshes

    for r in results:
        if r.error:
            print(f"  [FAIL] {r.city}: exception — {r.error}")
            failures += 1
            continue

        # Hard: enough basket coverage — but allow up to max_ip_block_cities to be
        # completely empty (IP-rotation ceiling hit, expected without residential proxy).
        if r.fraction_priced < MIN_PRICED_FRACTION:
            if r.fraction_priced == 0 and ip_block_cities < cfg.max_ip_block_cities:
                ip_block_cities += 1
                print(f"  [WARN] {r.city}: 0/{len(BASKET)} priced — IP block ceiling hit "
                      f"(proxy-free tolerance {ip_block_cities}/{cfg.max_ip_block_cities})")
            else:
                print(f"  [FAIL] {r.city}: only {len(r.priced_ingredients)}/{len(BASKET)} priced "
                      f"(need >= {MIN_PRICED_FRACTION:.0%})")
                failures += 1
        else:
            print(f"  [PASS] {r.city}: {len(r.priced_ingredients)}/{len(BASKET)} priced  "
                  f"store={r.store_id}  {r.elapsed:.1f}s")

        # Hard: sanity range on each price (skip cities that returned nothing)
        if r.fraction_priced > 0:
            for ing, res in r.prices.items():
                if not res:
                    continue
                tc = res.get("total_cost", 0)
                if not (PRICE_SANITY_MIN <= tc <= PRICE_SANITY_MAX):
                    print(f"    [FAIL] {r.city} {ing}: total_cost={tc:.2f} outside "
                          f"[{PRICE_SANITY_MIN}, {PRICE_SANITY_MAX}]")
                    failures += 1
                else:
                    city_prices.setdefault(ing, {})[r.city] = tc

        # Soft: list any missing ingredients
        missing = [k for k in BASKET if k not in r.priced_ingredients]
        if missing:
            print(f"    [WARN] {r.city}: unpriced: {', '.join(missing)}")

    good_results = [r for r in results if not r.error]
    if not good_results:
        return failures

    if cfg.regional_prices:
        # Hard: at least one ingredient shows regional price variation (store-resolved pricing).
        varying = []
        for ing, by_city in city_prices.items():
            vals = list(by_city.values())
            if len(vals) >= 2 and (max(vals) - min(vals)) >= REGIONAL_DIFF_MIN:
                varying.append((ing, min(vals), max(vals)))
        if not varying and len(good_results) >= 2:
            print(f"  [FAIL] No regional price variation detected across {len(good_results)} cities — "
                  f"store resolution may be returning the same data everywhere.")
            failures += 1
        else:
            for ing, lo, hi in varying[:3]:
                print(f"  [PASS] Regional diff — {ing}: ${lo:.2f} – ${hi:.2f}")
    else:
        # National pricing: verify prices are consistent across cities (idempotency).
        inconsistent = []
        for ing, by_city in city_prices.items():
            vals = list(by_city.values())
            if len(vals) >= 2 and (max(vals) - min(vals)) > REGIONAL_DIFF_MIN:
                inconsistent.append((ing, min(vals), max(vals)))
        if inconsistent:
            for ing, lo, hi in inconsistent:
                print(f"  [FAIL] National-price store returned inconsistent prices for "
                      f"{ing}: ${lo:.2f} – ${hi:.2f} (cache or parser bug)")
                failures += 1
        else:
            sample_total = sum(
                v.get("total_cost", 0) for v in good_results[0].prices.values() if v
            )
            print(f"  [PASS] National pricing consistent across {len(good_results)} cities "
                  f"(basket total ${sample_total:.2f})")

    return failures


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(cfg: StoreConfig, results: list[CityResult]):
    print(f"\n{'City':<24} {'Store ID':<14} {'Priced':>7} {'Total $':>9} {'Time':>6}  Ingredients")
    print("-" * 90)
    for r in results:
        if r.error:
            print(f"  {r.city:<22} {'ERROR':<14} {'':>7} {'':>9} {r.elapsed:>5.1f}s  {r.error[:40]}")
            continue
        total = sum(v.get("total_cost", 0) for v in r.prices.values() if v)
        detail = "  ".join(
            f"{ing}=${v.get('total_cost', 0):.2f}" for ing, v in sorted(r.prices.items()) if v
        )
        print(f"  {r.city:<22} {str(r.store_id):<14} "
              f"{len(r.priced_ingredients):>2}/{len(BASKET):<4} "
              f"${total:>7.2f} {r.elapsed:>5.1f}s  {detail[:60]}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    fast = "--fast" in args
    filter_keys = {a for a in args if not a.startswith("--")}

    configs = _build_configs()
    if filter_keys:
        configs = [c for c in configs if c.key in filter_keys]
    if not configs:
        print(f"No matching stores. Available: {[c.key for c in _build_configs()]}")
        sys.exit(1)

    cities = CITIES[:FAST_CITIES] if fast else CITIES
    total_failures = 0

    for cfg in configs:
        print(f"\n{'='*70}")
        print(f"  STORE: {cfg.label}")
        if cfg.skip_reason:
            print(f"  SKIP: {cfg.skip_reason}")
            continue
        print(f"  Cities: {len(cities)}{'  [fast mode]' if fast else ''}")
        print(f"{'='*70}")

        t0 = time.time()
        results = run_store(cfg, cities)
        elapsed = time.time() - t0

        print(f"\n--- Assertions ---")
        failures = assert_store_results(cfg, results)
        total_failures += failures

        print_summary(cfg, results)
        print(f"\n  Total elapsed: {elapsed:.1f}s  |  Hard failures: {failures}")

        try:
            cfg.shutdown_fn()
        except Exception:
            pass

    print(f"\n{'='*70}")
    print(f"  {'ALL STORES PASS' if total_failures == 0 else f'{total_failures} HARD FAILURE(S)'}")
    print(f"{'='*70}\n")
    sys.exit(1 if total_failures else 0)
