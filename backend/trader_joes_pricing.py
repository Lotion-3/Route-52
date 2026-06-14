"""
Trader Joe's pricing via traderjoes.com Magento GraphQL API.

TJ's has no online ordering, but their site runs Magento 2 with a /api/graphql
endpoint that supports the `products` query with retail prices. Prices are
uniform nationally (no location parameter needed).

Akamai EdgeSuite rate-limits repeated requests from the same IP. The module
tries each search with a small delay; if blocked it returns empty and the
server keeps synthetic prices for that ingredient. On a fresh IP the first
~5-10 searches usually succeed.

Entry point:
    store_name, prices = price_all_tj(ingredients)
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

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
# Per-ingredient pricing  (sequential to respect rate limits)
# ---------------------------------------------------------------------------

def _price_one(ingredient: str, qty: float, unit: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        time.sleep(0.6)
        raw = _search_tj(term)
        if not raw:
            continue
        products = [p for p in (_item_to_kroger_format(i) for i in raw) if p]
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

    Returns (store_display_name, prices). May return partial results if Akamai
    rate-limits the IP; unpriced ingredients fall back to synthetic prices.
    """
    print("[TJ] Pricing ingredients via traderjoes.com ...", flush=True)
    prices: dict = {}
    for name, data in ingredients.items():
        try:
            result = _price_one(
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
            )
            if result:
                prices[name] = result
        except Exception as e:
            print(f"[TJ] Error pricing '{name}': {e}", flush=True)

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
