"""
Trader Joe's pricing via traderjoes.com Magento GraphQL API.

TJ's has no online ordering, but their site runs Magento 2 with a /api/graphql
endpoint that supports the `products` query with retail prices. Prices are
uniform nationally (no location parameter needed).

Akamai EdgeSuite rate-limits repeated requests from the same IP, so searches go
through a shared minimum-interval limiter and a term cache; a small worker pool
overlaps the round-trips so a full basket completes inside the server's pricing
budget. If blocked, a search returns empty and that ingredient is simply left
unpriced (the store is excluded rather than given made-up prices).

Entry point:
    store_name, prices = price_all_tj(ingredients)
"""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

import pricing_pool
from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TJ_BANNERS: set[str] = {"trader joe", "trader joes", "trader joe's"}
_GQL_URL = "https://www.traderjoes.com/api/graphql"

_PRODUCTS_QUERY = """
query SearchProducts($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    items {
      sku
      name
      price_range {
        minimum_price {
          regular_price { value currency }
        }
      }
    }
    total_count
  }
}
"""

_SIZE_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(fl\.?\s*oz|oz|ounce|lb|lbs|pound|gal|gallon|count|ct|pk|pack|each|liter|ml|g|kg)',
    re.IGNORECASE,
)

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.traderjoes.com",
    "Referer": "https://www.traderjoes.com/home/products/",
})

# ---------------------------------------------------------------------------
# Banner detection
# ---------------------------------------------------------------------------

def is_trader_joes_store(store_name: str) -> bool:
    lower = store_name.lower()
    return any(b in lower for b in TJ_BANNERS)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _search_tj(query: str, page_size: int = 20) -> list[dict]:
    """Return product list or empty list on any error/block."""
    try:
        r = _session.post(
            _GQL_URL,
            json={
                "operationName": "SearchProducts",
                "variables": {"search": query, "pageSize": page_size, "currentPage": 1},
                "query": _PRODUCTS_QUERY,
            },
            timeout=12,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if "errors" in data:
            return []
        return ((data.get("data") or {}).get("products") or {}).get("items") or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Item → Kroger format
# ---------------------------------------------------------------------------

def _item_to_kroger_format(item: dict) -> Optional[dict]:
    name = item.get("name") or ""
    try:
        price = float(
            (item.get("price_range") or {})
            .get("minimum_price", {})
            .get("regular_price", {})
            .get("value") or 0
        )
        if not (0.01 <= price <= 300):
            return None
    except Exception:
        return None

    m = _SIZE_RE.search(name)
    if m:
        size_str = f"{m.group(1)} {m.group(2)}"
    elif "dozen" in name.lower():
        size_str = "12 count"
    else:
        size_str = "1 each"

    return {
        "description": name.title(),
        "brand": "Trader Joe's",
        "items": [{
            "itemId": str(item.get("sku") or ""),
            "soldBy": "UNIT",
            "size": size_str,
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Rate limiting + search cache
# ---------------------------------------------------------------------------
#
# This used to be strictly sequential: `time.sleep(0.6)` before every search,
# one ingredient at a time. At ~0.6s sleep + ~1s round-trip that is ~0.6
# searches/sec, so a 90-ingredient basket took 3-5 MINUTES against the server's
# 75s pricing budget — Trader Joe's was guaranteed to be dropped from every
# plan, and the abandoned thread then kept issuing those same searches in the
# background for nobody.
#
# Now: a shared minimum-interval limiter caps the REQUEST RATE (the thing
# Akamai actually meters) while a small worker pool overlaps the round-trips,
# and a per-process cache means repeated fallback terms ("milk", "eggs", ...)
# shared across ingredients are fetched once. Net effect is fewer total
# requests to traderjoes.com than before, finishing inside the budget.

_TJ_WORKERS = int(os.environ.get("TJ_MAX_WORKERS", "4"))
_TJ_MIN_INTERVAL = float(os.environ.get("TJ_MIN_REQUEST_INTERVAL", "0.35"))
_TJ_CACHE_TTL = float(os.environ.get("TJ_SEARCH_TTL", "900"))  # 15 min

_rate_lock = threading.Lock()
_last_request_at = 0.0

# term -> (expiry_ts, products in kroger format)
_search_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _throttle() -> None:
    """Block until at least _TJ_MIN_INTERVAL has passed since the last request,
    process-wide. Holds the lock across the sleep so concurrent workers space
    out rather than all waking at once."""
    global _last_request_at
    with _rate_lock:
        wait = _last_request_at + _TJ_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _search_cached(term: str) -> list[dict]:
    """Search TJ for `term`, in kroger-product format, memoised for _TJ_CACHE_TTL."""
    now = time.monotonic()
    with _cache_lock:
        hit = _search_cache.get(term)
        if hit and hit[0] > now:
            return hit[1]

    _throttle()
    raw = _search_tj(term)
    products = [p for p in (_item_to_kroger_format(i) for i in raw) if p]

    with _cache_lock:
        _search_cache[term] = (now + _TJ_CACHE_TTL, products)
        # Bound the cache: search terms come from a fixed vocabulary, but never
        # let a long-lived process grow this without limit.
        if len(_search_cache) > 2000:
            for k, (exp, _) in list(_search_cache.items()):
                if exp <= now:
                    _search_cache.pop(k, None)
    return products


# ---------------------------------------------------------------------------
# Per-ingredient pricing
# ---------------------------------------------------------------------------

def _price_one(ingredient: str, qty: float, unit: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        if pricing_pool.expired():
            return None
        products = _search_cached(term)
        if not products:
            continue
        query_words = set(term.lower().split())
        matched = [p for p in products if any(qw in p["description"].lower() for qw in query_words)]
        result = find_best_purchase(ingredient, qty, unit, matched or products)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_tj(ingredients: dict) -> tuple[str, dict]:
    """
    Price all ingredients at Trader Joe's (national catalog, no location needed).

    Round-trips are overlapped across a small worker pool while a shared
    minimum-interval limiter caps the request rate, so a full basket finishes
    inside the server's pricing budget instead of running for minutes and being
    discarded. Returns (store_display_name, prices); partial results are normal
    if Akamai rate-limits the IP or the budget elapses mid-run.
    """
    if not ingredients:
        return "Trader Joe's", {}

    print(f"[TJ] Pricing {len(ingredients)} ingredients via traderjoes.com "
          f"({_TJ_WORKERS} workers, {_TJ_MIN_INTERVAL:.2f}s min interval) ...", flush=True)
    prices: dict = {}
    workers = max(1, min(_TJ_WORKERS, len(ingredients)))

    # bind_current_deadline carries this chain's budget onto the nested workers
    # (the deadline is thread-local, so they would otherwise run unbounded).
    price_one = pricing_pool.bind_current_deadline(_price_one)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tj") as pool:
        futures = {
            pool.submit(
                price_one,
                name,
                float(data.get("qty", 1) or 1),
                str(data.get("unit", "whole")),
            ): name
            for name, data in ingredients.items()
        }
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
                if result:
                    prices[name] = result
            except Exception as e:
                print(f"[TJ] Error pricing '{name}': {e}", flush=True)

    if pricing_pool.expired():
        print(f"[TJ] Pricing budget elapsed — returning {len(prices)}/"
              f"{len(ingredients)} priced.", flush=True)
    else:
        print(f"[TJ] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "Trader Joe's", prices


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST = {
        "Large eggs":           {"qty": 12, "unit": "whole"},
        "Whole milk":           {"qty": 1,  "unit": "gal"},
        "Bananas":              {"qty": 5,  "unit": "whole"},
        "Boneless skinless chicken breast": {"qty": 2, "unit": "lb"},
        "Russet potatoes":      {"qty": 3,  "unit": "lb"},
        "Canned black beans":   {"qty": 2,  "unit": "can"},
        "Shredded cheddar":     {"qty": 8,  "unit": "oz"},
    }
    print("Testing Trader Joe's pricing pipeline...")
    print("=" * 60)
    store, prices = price_all_tj(TEST)
    print(f"\nStore: {store}")
    print("-" * 60)
    total = 0.0
    for ing, r in sorted(prices.items()):
        cost = r.get("total_cost", 0)
        total += cost
        print(f"  {ing:<40} ${cost:.2f}  ({r.get('description','')[:40]})")
    print(f"\n  TOTAL: ${total:.2f}  ({len(prices)}/{len(TEST)} priced)")
