"""
IGA (Australia, via Metcash's igashop.com.au) grocery pricing.

Unlike Coles/Woolworths, IGA's storefront API has NO bot-management gate at
all — it's a plain public JSON endpoint, no cookies, no session, no browser
warm needed. Validated 2026-07-24 with a bare curl_cffi request from a
datacenter IP: 200 OK, zero headers beyond the defaults.

The real endpoint was hidden behind a red herring: the page's Next.js
`_next/data/<buildId>/search/1.json` route just serves a cached page shell
(Vercel edge cache doesn't vary it by query string) — the actual product
data comes from a separate call the page fires client-side:
    GET /api/storefront/stores/{store_id}/search?q={term}&take={n}

IGA is a franchise network (independently-owned stores under Metcash), so
pricing is store-resolved via `store_id` in the URL, and prices may
legitimately vary more store-to-store here than at a corporate chain.

Store resolution: `find_nearest_iga_store(lat, lon)` hits the same public,
unauthenticated `GET /api/storefront/stores` endpoint (no lat/lon filter
server-side — it returns all ~483 stores in one call), caches that list for
24h, and picks the closest via haversine distance. `retailerStoreId` on each
entry is the id `price_all_iga`'s `store_id` param expects.

Entry point:
    store_id = find_nearest_iga_store(lat, lon) or "32600"
    store_name, store_id, prices = price_all_iga(ingredients, store_id=store_id)

Self-test:  python iga_pricing.py
"""
from __future__ import annotations

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

IGA_BANNERS: set[str] = {"iga"}
_SEARCH_URL = "https://www.igashop.com.au/api/storefront/stores/{store_id}/search"
_STORE_LIST_URL = "https://www.igashop.com.au/api/storefront/stores"
_IMPERSONATE = os.environ.get("IGA_IMPERSONATE", "chrome")
_HTTP_CONCURRENCY = int(os.environ.get("IGA_HTTP_CONCURRENCY", "10"))
_SEARCH_TTL = int(os.environ.get("IGA_SEARCH_TTL", str(6 * 3600)))
_TAKE = int(os.environ.get("IGA_SEARCH_TAKE", "20"))
_STORE_LIST_TTL = int(os.environ.get("IGA_STORE_LIST_TTL", str(24 * 3600)))

_store_list_cache: Optional[tuple[float, list[dict]]] = None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _get_all_stores() -> list[dict]:
    """Fetch (and cache for 24h) the full ~483-store IGA list. Public,
    unauthenticated endpoint — no session needed."""
    global _store_list_cache
    if _store_list_cache and _store_list_cache[0] > time.time():
        return _store_list_cache[1]
    from curl_cffi import requests as _ccffi
    resp = _ccffi.get(_STORE_LIST_URL, impersonate=_IMPERSONATE, timeout=20)
    resp.raise_for_status()
    stores = resp.json().get("items") or []
    _store_list_cache = (time.time() + _STORE_LIST_TTL, stores)
    return stores


def find_nearest_iga_store(lat: float, lon: float) -> Optional[str]:
    """Resolve coordinates to the nearest active IGA store's retailerStoreId
    (the id price_all_iga's store_id param expects). Returns None on failure
    — caller should fall back to a default store id."""
    try:
        stores = _get_all_stores()
        candidates = [
            s for s in stores
            if s.get("status") == "Active" and s.get("retailerStoreId") and s.get("location")
        ]
        if not candidates:
            return None
        nearest = min(
            candidates,
            key=lambda s: _haversine_km(lat, lon, s["location"]["latitude"], s["location"]["longitude"]),
        )
        dist = _haversine_km(lat, lon, nearest["location"]["latitude"], nearest["location"]["longitude"])
        print(f"[IGA] Nearest store: {nearest.get('name')} ({dist:.1f} km) — "
              f"id {nearest['retailerStoreId']}", flush=True)
        return str(nearest["retailerStoreId"])
    except Exception as e:
        print(f"[IGA] Store lookup failed ({repr(e)[:100]}).", flush=True)
        return None


def is_iga_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in IGA_BANNERS)


def is_in_australia(lat: float, lon: float) -> bool:
    """Rough bounding box for mainland Australia + Tasmania.

    Gates this AU-only igashop.com.au integration away from US IGA-banner
    stores: IGA is also a common independent-grocer banner in the US
    (especially rural Midwest), which this Metcash API has zero data for.
    Without this check, a US "IGA" store name resolves to the nearest
    *Australian* IGA (often thousands of km away) and gets priced against
    that instead — wrong prices silently mislabeled as the real store."""
    return -44.0 <= lat <= -10.0 and 112.0 <= lon <= 154.0


def _fetch_products(term: str, store_id: str) -> list[dict]:
    """Plain public request — no cookies, no session, no WAF to defeat."""
    from curl_cffi import requests as _ccffi
    url = _SEARCH_URL.format(store_id=store_id)
    try:
        resp = _ccffi.get(url, params={"q": term, "take": str(_TAKE)},
                           impersonate=_IMPERSONATE, timeout=20)
    except Exception as e:
        print(f"[IGA] Request error for '{term}': {repr(e)[:80]}", flush=True)
        return []
    if resp.status_code != 200:
        print(f"[IGA] '{term}' -> status {resp.status_code}", flush=True)
        return []
    try:
        return resp.json().get("items") or []
    except Exception:
        return []


def _item_to_kroger_format(item: dict) -> Optional[dict]:
    name = item.get("name") or ""
    if not name or not item.get("available", True):
        return None
    price = item.get("priceNumeric")
    if price is None or not (0.01 <= float(price) <= 500):
        return None

    uos = item.get("unitOfSize") or {}
    size_type = (uos.get("type") or "").lower()
    is_weighted = size_type in ("kg", "g")
    size = f"{uos.get('size', 1)} {uos.get('abbreviation') or 'each'}" if uos else "1 each"

    return {
        "description": name,
        "brand": item.get("brand") or "",
        "items": [{
            "itemId": str(item.get("productId") or item.get("sku") or ""),
            "soldBy": "WEIGHT" if is_weighted else "UNIT",
            "size": "1 kg" if is_weighted else size,
            "price": {"regular": float(price), "promo": None},
        }],
    }


_search_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def _search(term: str, store_id: str) -> list[dict]:
    key = (term.lower(), store_id)
    cached = _search_cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]

    raw = _fetch_products(term, store_id)
    query_words = set(term.lower().split())
    out = []
    for it in raw:
        fmt = _item_to_kroger_format(it)
        if fmt and any(w in fmt["description"].lower() for w in query_words):
            out.append(fmt)
    if not out:
        out = [f for f in (_item_to_kroger_format(it) for it in raw) if f]
    _search_cache[key] = (time.time() + _SEARCH_TTL, out)
    return out


def _price_one(ingredient: str, qty: float, unit: str, store_id: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search(term, store_id)
        if not products:
            continue
        result = find_best_purchase(ingredient, qty, unit, products)
        if result:
            return result
        if term.lower() != ingredient.lower():
            result = find_best_purchase(term, qty, unit, products)
            if result:
                return result
    return None


def price_all_iga(
    ingredients: dict,
    store_id: str,
    lat: float = 0.0,
    lon: float = 0.0,
) -> tuple[Optional[str], Optional[str], dict]:
    """Price all ingredients at a specific IGA store.

    NOTE: lat/lon accepted for interface parity but not used to resolve a
    store yet — store_id must be supplied (see module docstring)."""
    items = list(ingredients.items())
    if not items or not store_id:
        return None, None, {}

    prices: dict = {}

    def _work(item):
        name, data = item
        try:
            r = _price_one(name, float(data.get("qty", 1) or 1),
                            str(data.get("unit", "whole")), store_id)
            return name, r
        except Exception as e:
            print(f"[IGA] Error pricing '{name}': {e}", flush=True)
            return name, None

    with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(items)),
                             thread_name_prefix="iga-http") as pool:
        for name, r in pool.map(_work, items):
            if r:
                prices[name] = r

    if not prices:
        return None, None, {}
    print(f"[IGA] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "IGA", store_id, prices


def shutdown() -> None:
    pass


# ---------------------------------------------------------------------------
# Self-test:  python iga_pricing.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 32600 = the store captured during discovery (2026-07-24).
    TEST_STORE_ID = os.environ.get("IGA_TEST_STORE_ID", "32600")
    sample = {
        "milk":           {"qty": 2, "unit": "litre"},
        "eggs":           {"qty": 12, "unit": "count"},
        "bananas":        {"qty": 1, "unit": "kg"},
        "chicken breast": {"qty": 1, "unit": "kg"},
        "white rice":     {"qty": 1, "unit": "kg"},
    }
    name, sid, out = price_all_iga(sample, store_id=TEST_STORE_ID)
    print(f"\n=== {name} ({sid}) ===")
    if not out:
        print("No prices — check store_id or endpoint changes.")
    for ing, res in out.items():
        print(f"  {ing:16s} ${res.get('total_cost', 0):7.2f}  "
              f"{res.get('description', '')[:40]} ({res.get('size_str', '')})")
    shutdown()
