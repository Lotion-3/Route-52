"""
Meijer pricing pipeline using Constructor.io (Meijer's search backend).

Flow:
  1. Query Constructor.io search endpoint (no WAF protection, just an API key).
  2. For each ingredient, try get_all_terms() fallbacks until we get results.
  3. Convert Constructor.io product dicts to Kroger-like format; reuse find_best_purchase().

Store ID:
  Constructor.io filters pricing and availability to a specific Meijer store via
  the `availableInStores` query param.  The store number is resolved from the
  caller's coordinates via Meijer's store locator (_resolve_store_id) — curl_cffi
  clears its WAF, no browser needed.  Set MEIJER_STORE_ID to force a store.

Entry point:
    store_name, store_id, prices = price_all_meijer(ingredients, lat, lon)

prices format (same as kroger_async / aldi_pricing):
    {ingredient_name: {"total_cost": float, "description": str, "size_str": str, ...}}
"""
from __future__ import annotations

import os
import random
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Proxy — same CLOAK_PROXY convention as walmart_pricing.py/target_pricing.py/
# coles_pricing.py/woolworths_pricing.py: a single URL, a single URL with a
# {session} placeholder, or a comma/whitespace-separated pool. Meijer has no
# CloakBrowser step to mint a reusable cookie — every request is a direct
# curl_cffi/requests call, so the proxy is applied per-request rather than
# just at a "warm" step.
# ---------------------------------------------------------------------------


def _parse_proxies(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]


_PROXIES = _parse_proxies(os.environ.get("CLOAK_PROXY") or os.environ.get("MEIJER_PROXY"))


def _pick_proxy() -> Optional[str]:
    if not _PROXIES:
        return None
    base = random.choice(_PROXIES)
    if "{session}" in base:
        return base.replace("{session}", os.urandom(6).hex())
    return base


def _proxy_dict() -> Optional[dict]:
    p = _pick_proxy()
    return {"http": p, "https": p} if p else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEIJER_BANNERS: set[str] = {"meijer"}

CNSTRC_KEY = "key_GdYuTcnduTUtsZd6"
CNSTRC_BASE = "https://ac.cnstrc.com/search"

# Ultimate fallback only — the store is normally resolved from the caller's
# coordinates (see _resolve_store_id). Set MEIJER_STORE_ID to force a store.
_DEFAULT_STORE_ID = "130"

# Meijer's store locator. It's WAF-protected (plain requests get 403), but
# curl_cffi's Chrome-JA3 impersonation passes it with no cookie/browser needed.
# Returns stores sorted by distance, each with a geoPoint + store number.
_STORE_LOCATOR = "https://www.meijer.com/bin/meijer/store/search"

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
# Store resolution (nearest Meijer to the caller's coordinates)
# ---------------------------------------------------------------------------

_store_id_cache: dict[tuple, str] = {}  # (round(lat,2), round(lon,2)) -> store_id


def _haversine_miles(la1: float, lo1: float, la2: float, lo2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(la2 - la1)
    dlon = radians(lo2 - lo1)
    a = sin(dlat / 2) ** 2 + cos(radians(la1)) * cos(radians(la2)) * sin(dlon / 2) ** 2
    return 3959.0 * 2 * asin(sqrt(a))


def _resolve_store_id(lat: float, lon: float) -> str:
    """Resolve the nearest full Meijer store number for (lat, lon) via Meijer's
    store locator (curl_cffi Chrome-JA3 clears the WAF — no browser/cookie).
    Picks the nearest GROCERY store (skips pharmacy/clinic-only locations) by
    exact coordinates, cached per ~rounded location. Falls back to the default."""
    if not lat and not lon:
        return _DEFAULT_STORE_ID
    cache_key = (round(lat, 2), round(lon, 2))
    if cache_key in _store_id_cache:
        return _store_id_cache[cache_key]

    try:
        from instacart_pricing import _get_postal
        postal = _get_postal(lat, lon)
    except Exception:
        postal = ""
    if not postal:
        return _DEFAULT_STORE_ID

    try:
        from curl_cffi import requests as _ccffi
        # Direct first — Meijer's WAF (Akamai) has repeatedly tested cleaner
        # from this server's own IP than from Webshare's free *datacenter*
        # pool, which is a known blocklist target for Akamai precisely because
        # it's a heavily-shared scraping range. Measured 2026-07-25: only 2/10
        # of the free pool's IPs are actually clean for this endpoint — Akamai
        # returns a 200 with an HTML block page for the rest (NOT a 4xx), so a
        # single fallback attempt has just a ~20% chance of working. Walk the
        # whole (shuffled) pool on failure rather than trying just one.
        proxy_attempts = list(_PROXIES)
        random.shuffle(proxy_attempts)
        attempts: list[Optional[dict]] = [None] + [
            {"http": p, "https": p} for p in proxy_attempts
        ]
        resp = None
        body = None
        for proxies in attempts:
            resp = _ccffi.get(
                _STORE_LOCATOR,
                params={"locationQuery": postal, "radius": "50"},
                headers={**HEADERS, "accept": "application/json",
                         "referer": "https://www.meijer.com/shopping/store-finder.html"},
                impersonate="chrome", timeout=15,
                proxies=proxies,
            )
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    if "pointsOfService" in body or "data" in body:
                        break  # a real API response, not an HTML block page
                except Exception:
                    pass
            body = None
        if body is None:
            print(f"[Meijer] Store locator blocked on direct IP + all {len(proxy_attempts)} "
                  f"proxies; using #{_DEFAULT_STORE_ID}.", flush=True)
            return _DEFAULT_STORE_ID
        stores = (body.get("data", {}).get("pointsOfService")
                  or body.get("pointsOfService") or [])
        best = None  # (distance_miles, store_id, display_name)
        for s in stores:
            dn = (s.get("displayName") or "").lower()
            if any(x in dn for x in ("pharmacy", "clinic", "express")):
                continue  # not a full grocery store
            sid = str(s.get("name") or s.get("mfcStoreId") or "").strip()
            gp = s.get("geoPoint") or {}
            slat, slon = gp.get("latitude"), gp.get("longitude")
            if not sid or slat is None or slon is None:
                continue
            dist = _haversine_miles(lat, lon, slat, slon)
            if best is None or dist < best[0]:
                best = (dist, sid, s.get("displayName") or sid)
        if best:
            _, sid, dn = best
            _store_id_cache[cache_key] = sid
            print(f"[Meijer] Resolved store #{sid} ({dn}, {best[0]:.1f} mi) "
                  f"for {postal}.", flush=True)
            return sid
        print(f"[Meijer] No Meijer store near {postal}; using #{_DEFAULT_STORE_ID}.", flush=True)
    except Exception as e:
        print(f"[Meijer] Store resolution failed ({e}); using #{_DEFAULT_STORE_ID}.", flush=True)
    return _DEFAULT_STORE_ID


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
    lat, lon    : coordinates of the target store (used to resolve store #)
    max_workers : parallel threads

    Returns
    -------
    (display_name, store_id, prices)
        prices: {ingredient_name: find_best_purchase() result dict}
    """
    store_id = os.environ.get("MEIJER_STORE_ID") or _resolve_store_id(lat, lon)
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
