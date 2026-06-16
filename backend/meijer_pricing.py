"""
Meijer pricing pipeline using Constructor.io (Meijer's search backend).

Flow:
  1. Query Constructor.io search endpoint (no WAF protection, just an API key).
  2. For each ingredient, try get_all_terms() fallbacks until we get results.
  3. Convert Constructor.io product dicts to Kroger-like format; reuse find_best_purchase().

Store ID:
  Constructor.io filters pricing and availability to a specific Meijer store via
  the `availableInStores` query param.  Set MEIJER_STORE_ID env var to override;
  defaults to 130 (Grand Rapids, MI area).

Entry point:
    store_name, store_id, prices = price_all_meijer(ingredients, lat, lon)

prices format (same as kroger_async / aldi_pricing):
    {ingredient_name: {"total_cost": float, "description": str, "size_str": str, ...}}
"""
from __future__ import annotations

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEIJER_BANNERS: set[str] = {"meijer"}

CNSTRC_KEY = "key_GdYuTcnduTUtsZd6"
CNSTRC_BASE = "https://ac.cnstrc.com/search"

# Default: Grand Rapids-area store. Override with MEIJER_STORE_ID env var.
_DEFAULT_STORE_ID = "130"

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://www.meijer.com",
    "referer": "https://www.meijer.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


# ---------------------------------------------------------------------------
# Store detection
# ---------------------------------------------------------------------------

def is_meijer_store(store_name: str) -> bool:
    lower = store_name.lower()
    # Exclude Meijer Express (smaller gas-station format, different assortment)
    return any(b in lower for b in MEIJER_BANNERS) and "express" not in lower


# ---------------------------------------------------------------------------
# Product format conversion
# ---------------------------------------------------------------------------

_SIZE_WORDS = frozenset({
    "dozen", "gallon", "half gallon", "quart", "pint", "liter", "litre",
    "each", "pack", "pound", "ounce", "fluid ounce",
})

_SIZE_SUFFIX_RE = re.compile(
    r",?\s*("
    r"\d[\d./\s]*(?:oz|fl oz|lb|lbs|kg|g|mg|ml|l|ct|count|pack|pk|"
    r"gallon|gal|quart|qt|pint|pt|liter|litre|dozen|doz|each|ea|"
    r"ounce|ounces|pound|pounds|piece|pieces)"
    r"s?\b"
    r"|dozen|gallon|half gallon|quart|pint)"
    r"\s*$",
    re.IGNORECASE,
)


def _extract_size(value: str) -> tuple[str, str]:
    """
    Split 'Brand Product Name, 24 Count' into ('Brand Product Name', '24 Count').
    Returns (name, size_str).  size_str is '' when no size found.
    """
    # Try regex extraction first (handles embedded sizes without a comma)
    m = _SIZE_SUFFIX_RE.search(value)
    if m:
        size = m.group(1).strip()
        name = value[: m.start()].rstrip(", ").strip()
        return name, size

    # Fall back: split on last comma
    if ", " in value:
        parts = value.rsplit(", ", 1)
        last = parts[-1].strip()
        if last.lower() in _SIZE_WORDS or re.search(r"\d", last):
            return parts[0].strip(), last

    return value, ""


def _to_kroger_format(item: dict) -> Optional[dict]:
    """
    Convert a Constructor.io result dict into the Kroger product shape that
    find_best_purchase() expects.
    """
    data = item.get("data") or {}
    price = data.get("price")
    try:
        price = float(price)
        if not (0.01 <= price <= 500):
            return None
    except (TypeError, ValueError):
        return None

    # Skip out-of-stock items
    status = (data.get("stockLevelStatus") or "").lower()
    if status and status not in ("instock", ""):
        return None

    value = item.get("value") or ""
    name, size = _extract_size(value)

    return {
        "description": name,
        "brand": "",
        "items": [{
            "itemId": str(data.get("id") or data.get("ean") or ""),
            "soldBy": "UNIT",
            "size": size or "1 each",
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Search helper
# ---------------------------------------------------------------------------

def _search(query: str, store_id: str, num_results: int = 10) -> list[dict]:
    """
    Query Constructor.io for `query` at `store_id`.
    Returns Kroger-format product dicts filtered to items whose name
    contains at least one query word.
    """
    sess = _get_session()
    try:
        resp = sess.get(
            f"{CNSTRC_BASE}/{requests.utils.quote(query)}",
            params={
                "key": CNSTRC_KEY,
                "c": "ciojs-client-2.68.1",
                "i": str(uuid.uuid4()),
                "s": "1",
                "filters[availableInStores]": store_id,
                "num_results_per_page": str(num_results),
            },
            timeout=12,
        )
        resp.raise_for_status()
        results = resp.json().get("response", {}).get("results", [])
    except Exception:
        return []

    query_words = set(query.lower().split())
    # Try strict (ALL) filtering first; fall back to ANY if no results survive.
    # This keeps "Russet Potatoes" from accepting "Red Potatoes", while still
    # matching garlic products when no product literally says "cloves".
    def _matches_strict(name_lower: str) -> bool:
        return all(qw in name_lower for qw in query_words)

    def _matches_any(name_lower: str) -> bool:
        return any(qw in name_lower for qw in query_words)

    # First pass: strict (all query words must appear)
    out = []
    for item in results:
        name_lower = (item.get("value") or "").lower()
        if _matches_strict(name_lower):
            fmt = _to_kroger_format(item)
            if fmt:
                out.append(fmt)

    # Fallback: any query word matches (for cases like "garlic cloves" where no
    # product literally contains "cloves")
    if not out:
        for item in results:
            name_lower = (item.get("value") or "").lower()
            if _matches_any(name_lower):
                fmt = _to_kroger_format(item)
                if fmt:
                    out.append(fmt)

    return out


# ---------------------------------------------------------------------------
# Per-ingredient pricing
# ---------------------------------------------------------------------------

def _price_one(
    ingredient: str,
    qty: float,
    unit: str,
    store_id: str,
) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search(term, store_id)
        if not products:
            continue
        result = find_best_purchase(ingredient, qty, unit, products)
        if result:
            return result
        # find_best_purchase's relevance filter may reject products when the
        # store uses a different name (e.g. "garbanzo beans" for chickpeas).
        # Retry with the search term as the ingredient name so the filter matches.
        if term.lower() != ingredient.lower():
            result = find_best_purchase(term, qty, unit, products)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_meijer(
    ingredients: dict,
    lat: float,
    lon: float,
    max_workers: int = 10,
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest Meijer store.

    Parameters
    ----------
    ingredients : {name: {"qty": float, "unit": str, ...}}
    lat, lon    : user coordinates (unused for store lookup in current impl)
    max_workers : parallel threads

    Returns
    -------
    (display_name, store_id, prices)
        prices: {ingredient_name: find_best_purchase() result dict}
    """
    store_id = os.environ.get("MEIJER_STORE_ID", _DEFAULT_STORE_ID)
    display_name = f"Meijer (store #{store_id})"
    print(f"[Meijer] Pricing at: {display_name}", flush=True)

    prices: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _price_one,
                name,
                float(data.get("qty", 1) or 1),
                str(data.get("unit", "whole")),
                store_id,
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
                print(f"[Meijer] Error pricing '{name}': {e}", flush=True)

    print(f"[Meijer] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return display_name, store_id, prices


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST = {
        "Large eggs":                           {"qty": 12, "unit": "whole"},
        "Whole milk":                           {"qty": 1,  "unit": "gal"},
        "Bananas":                              {"qty": 5,  "unit": "whole"},
        "Boneless skinless chicken breast":     {"qty": 2,  "unit": "lb"},
        "Ground beef 80/20":                    {"qty": 1,  "unit": "lb"},
        "Russet potatoes":                      {"qty": 3,  "unit": "lb"},
        "Canned black beans":                   {"qty": 2,  "unit": "cans"},
        "Shredded cheddar cheese":              {"qty": 8,  "unit": "oz"},
        "Penne pasta":                          {"qty": 16, "unit": "oz"},
        "Olive oil":                            {"qty": 8,  "unit": "fl oz"},
    }
    print("Testing Meijer pricing pipeline (Grand Rapids, MI)...")
    print("=" * 60)
    name, sid, prices = price_all_meijer(TEST, 42.9634, -85.6681)
    print(f"\nStore: {name} (store_id={sid})")
    print(f"{'Item':<40} {'Cost':>7}  {'Pkg':>5}  Product")
    print("-" * 85)
    for item, d in prices.items():
        print(
            f"{item:<40} ${d['total_cost']:>5.2f}  "
            f"x{d.get('units_to_buy', 1):<4.0f}  "
            f"{str(d.get('description',''))[:35]}"
        )
    missing = [k for k in TEST if k not in prices]
    if missing:
        print(f"\nNo match: {missing}")
