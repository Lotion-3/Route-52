"""
ALDI pricing pipeline — mirrors kroger_async.py structure.

Flow:
  1. Load cached session (cookies + x-ic-qp + zoneId) from disk, or bootstrap with Playwright.
  2. Find nearest ALDI store via DefaultShop GraphQL.
  3. For each ingredient, try get_all_terms() fallbacks through SearchResultsPlacements + Items.
  4. Convert ALDI product dicts to Kroger-like format; reuse find_best_purchase() for unit math.

Entry point:
    store_name, store_id, prices = price_all_aldi(ingredients, lat, lon)

prices format (same as kroger_async):
    {ingredient_name: {"total_cost": float, "description": str, "size_str": str, ...}}
"""
from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALDI_BANNERS: set[str] = {"aldi"}
SESSION_TTL = 2 * 3600  # re-bootstrap after 2 h

BASE_GQL = "https://www.aldi.us/graphql"
OPERA_PATH = r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe"
_SESSION_CACHE = Path(__file__).parent / ".aldi_session.json"

HASHES = {
    "DefaultShop":             "d389a8d33d63801f1ce5c4929fb181dd10c57b49c3a2dcb6a6baa44212e8e069",
    "SearchResultsPlacements": "387535ff634b5f783192dc1464d1253e514ff092876a1747486d90d83beb4dfd",
    "Items":                   "0362f9eaea7f55c17c95266a64f8c37a10b55d265318f85c761c59c382d96074",
}

BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US",
    "content-type": "application/json",
    "x-client-identifier": "web",
    "x-ic-view-layer": "true",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "referer": "https://www.aldi.us/store/aldi/s?query=",
}


# ---------------------------------------------------------------------------
# Store detection
# ---------------------------------------------------------------------------

def is_aldi_store(store_name: str) -> bool:
    """Return True if the store name is an ALDI banner."""
    lower = store_name.lower()
    return any(b in lower for b in ALDI_BANNERS)


# ---------------------------------------------------------------------------
# Session management (disk cache + Playwright bootstrap)
# ---------------------------------------------------------------------------

# In-process cache so we only hit disk once per server run
_mem_cache: dict = {}
_session: Optional[requests.Session] = None


def _load_disk_session() -> dict:
    try:
        data = json.loads(_SESSION_CACHE.read_text())
        if data.get("expires_at", 0) > time.time():
            return data
    except Exception:
        pass
    return {}


def _save_disk_session(cookies: dict, qp: str, zone_id: str) -> None:
    try:
        _SESSION_CACHE.write_text(json.dumps({
            "cookies": cookies,
            "qp": qp,
            "zone_id": zone_id,
            "expires_at": time.time() + SESSION_TTL,
        }))
    except Exception:
        pass


def _bootstrap() -> tuple[dict, str, str]:
    """Run Playwright to capture cookies, x-ic-qp, and zoneId."""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        _stealth = Stealth()
    except ImportError:
        _stealth = None

    cookies: dict = {}
    qp: str = ""
    zone_id: str = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, executable_path=OPERA_PATH,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            user_agent=BASE_HEADERS["user-agent"],
        )
        page = ctx.new_page()
        if _stealth:
            _stealth.apply_stealth_sync(page)

        def on_req(req):
            nonlocal qp, zone_id
            if "graphql" not in req.url:
                return
            if not qp:
                v = req.headers.get("x-ic-qp", "")
                if v:
                    qp = v
            if "operationName=Items" in req.url and not zone_id:
                try:
                    import urllib.parse
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
                    vv = json.loads(qs.get("variables", ["{}"])[0])
                    z = vv.get("zoneId") or ""
                    if z:
                        zone_id = str(z)
                except Exception:
                    pass

        page.on("request", on_req)
        print("[ALDI] Bootstrapping guest session (Playwright)...", flush=True)
        page.goto("https://www.aldi.us/store/aldi/s?query=eggs",
                  wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click(); time.sleep(2); break
            except Exception:
                pass

        for sel in ["text=Delivery", "a:has-text('Delivery')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2500):
                    el.click(); time.sleep(3); break
            except Exception:
                pass

        time.sleep(8)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    print(f"[ALDI] Session ready. cookies={len(cookies)}, qp={'yes' if qp else 'no'}, zoneId={zone_id!r}", flush=True)
    return cookies, qp, zone_id


def _get_session() -> tuple[requests.Session, str]:
    """Return (session, zone_id), using disk cache or re-bootstrapping as needed."""
    global _mem_cache, _session

    if not _mem_cache:
        _mem_cache = _load_disk_session()

    if not _mem_cache:
        cookies, qp, zone_id = _bootstrap()
        _mem_cache = {"cookies": cookies, "qp": qp, "zone_id": zone_id,
                      "expires_at": time.time() + SESSION_TTL}
        _save_disk_session(cookies, qp, zone_id)
        _session = None  # force rebuild

    if _session is None:
        _session = requests.Session()
        _session.cookies.update(_mem_cache["cookies"])
        if _mem_cache.get("qp"):
            _session.headers.update({"x-ic-qp": _mem_cache["qp"]})

    return _session, _mem_cache.get("zone_id", "")


def _invalidate_session() -> None:
    """Clear cached session so the next call re-bootstraps."""
    global _mem_cache, _session
    _mem_cache = {}
    _session = None
    try:
        _SESSION_CACHE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GraphQL helper
# ---------------------------------------------------------------------------

def _gql(op: str, variables: dict, session: requests.Session) -> dict:
    params = {
        "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": HASHES[op]}},
            separators=(",", ":"),
        ),
    }
    headers = {**BASE_HEADERS, "x-page-view-id": str(uuid.uuid4())}
    try:
        r = session.get(BASE_GQL, params=params, headers=headers, timeout=12)
        if r.status_code in (401, 403):
            _invalidate_session()
            return {}
        if r.status_code != 200:
            return {}
        data = r.json()
        if "errors" in data:
            return {}
        return data.get("data") or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Postal code lookup (needed by DefaultShop)
# ---------------------------------------------------------------------------

_postal_cache: dict[tuple[float, float], str] = {}

def _get_postal(lat: float, lon: float) -> str:
    """Reverse-geocode lat/lon to postal code; cached in memory."""
    key = (round(lat, 3), round(lon, 3))
    if key in _postal_cache:
        return _postal_cache[key]
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="basket_buddy_aldi")
        loc = geo.reverse(f"{lat},{lon}", language="en", timeout=5)
        postal = (loc.raw.get("address", {}).get("postcode") or "") if loc else ""
    except Exception:
        postal = ""
    _postal_cache[key] = postal
    return postal


# ---------------------------------------------------------------------------
# Store discovery
# ---------------------------------------------------------------------------

def find_nearest_aldi_store(
    lat: float,
    lon: float,
    session: requests.Session,
    zone_id: str,
) -> Optional[tuple[str, str, str]]:
    """
    Find the nearest ALDI store.
    Returns (shopId, zoneId, display_name) or None if nothing found within range.
    """
    postal = _get_postal(lat, lon)
    data = _gql("DefaultShop", {
        "postalCode": postal or None,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
    }, session)
    shop = data.get("defaultShop") or {}
    shop_id = shop.get("id", "")
    if not shop_id:
        return None

    # zoneId from bootstrap is more reliable than DefaultShop response
    store_zone = zone_id or shop.get("zoneId") or ""

    # Build display name from store info
    name = shop.get("name") or "ALDI"
    address = shop.get("address") or {}
    city = address.get("city") or address.get("locality") or ""
    display = f"{name} ({city})" if city else name

    return shop_id, store_zone, display


# ---------------------------------------------------------------------------
# Product format conversion
# ---------------------------------------------------------------------------

def _to_kroger_format(prod: dict) -> Optional[dict]:
    """
    Convert an ALDI Items product dict into a Kroger API product dict shape
    so that find_best_purchase() can process it unchanged.
    """
    price_sec = ((prod.get("price") or {}).get("viewSection")) or {}
    price_str = price_sec.get("priceValueString")
    try:
        price = float(re.sub(r"[^\d.]", "", str(price_str)))
        if not (0.01 <= price <= 300):
            return None
    except Exception:
        return None

    # ALDI's "size" field: usually "12 Count", "1 gal", "16 oz", etc.
    size = prod.get("size") or "1 each"

    return {
        "description": prod.get("name") or "",
        "brand": "",
        "items": [{
            "itemId": str(prod.get("id") or ""),
            "soldBy": "UNIT",
            "size": size,
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Search + price helpers
# ---------------------------------------------------------------------------

def _search_and_fetch(
    query: str,
    shop_id: str,
    zone_id: str,
    postal: str,
    session: requests.Session,
) -> list[dict]:
    """
    Search ALDI for `query` and return Kroger-format product dicts
    filtered to items with at least one query-word match in the product name.
    """
    d = _gql("SearchResultsPlacements", {
        "action": None,
        "query": query,
        "pageViewId": str(uuid.uuid4()),
        "elevatedProductId": None,
        "searchSource": "search",
        "filters": [],
        "disableReformulation": False,
        "disableLlm": False,
        "forceInspiration": False,
        "orderBy": "bestMatch",
        "clusterId": None,
        "includeDebugInfo": False,
        "clusteringStrategy": None,
        "contentManagementSearchParams": {"itemGridColumnCount": 6},
        "shopId": shop_id,
        "postalCode": postal or None,
        "zoneId": zone_id if zone_id else None,
        "first": 20,
    }, session)

    ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', json.dumps(d))))[:20]
    if not ids:
        return []

    d2 = _gql("Items", {
        "ids": ids,
        "shopId": shop_id,
        "zoneId": zone_id if zone_id else None,
        "postalCode": postal or None,
    }, session)
    products = d2.get("items") or []

    query_words = set(query.lower().split())
    results = []
    for prod in products:
        name = (prod.get("name") or "").lower()
        name_words = set(name.split())
        if not any(qw in nw or nw in qw for qw in query_words for nw in name_words):
            continue
        fmt = _to_kroger_format(prod)
        if fmt:
            results.append(fmt)

    return results


def _price_one(
    ingredient: str,
    qty: float,
    unit: str,
    shop_id: str,
    zone_id: str,
    postal: str,
    session: requests.Session,
) -> Optional[dict]:
    """
    Try get_all_terms() fallback sequence for one ingredient.
    Returns a find_best_purchase() result dict on the first successful hit.
    """
    for term in get_all_terms(ingredient):
        products = _search_and_fetch(term, shop_id, zone_id, postal, session)
        if products:
            result = find_best_purchase(ingredient, qty, unit, products)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_aldi(
    ingredients: dict,
    lat: float,
    lon: float,
    max_workers: int = 10,
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest ALDI store.

    Parameters
    ----------
    ingredients : {name: {"qty": float, "unit": str, ...}}
    lat, lon    : user coordinates
    max_workers : parallel threads for ingredient searches

    Returns
    -------
    (store_display_name, shop_id, prices)
        prices: {ingredient_name: find_best_purchase() result dict}
    """
    session, zone_id = _get_session()

    store_info = find_nearest_aldi_store(lat, lon, session, zone_id)
    if not store_info:
        print("[ALDI] No ALDI store found near this location.", flush=True)
        return None, None, {}

    shop_id, store_zone_id, display_name = store_info
    # Prefer the bootstrapped zoneId; fall back to what DefaultShop returned
    effective_zone = zone_id or store_zone_id
    postal = _get_postal(lat, lon)
    print(f"[ALDI] Pricing at: {display_name} (shopId={shop_id})", flush=True)

    prices: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _price_one,
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
                shop_id,
                effective_zone,
                postal,
                session,
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
                print(f"[ALDI] Error pricing '{name}': {e}", flush=True)

    print(f"[ALDI] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return display_name, shop_id, prices


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST = {
        "Large eggs":           {"qty": 12, "unit": "whole"},
        "Whole milk gallon":    {"qty": 1,  "unit": "gal"},
        "Bananas":              {"qty": 5,  "unit": "whole"},
        "Boneless skinless chicken breast": {"qty": 2, "unit": "lb"},
        "Ground beef 80/20":    {"qty": 1,  "unit": "lb"},
        "Russet potatoes":      {"qty": 3,  "unit": "lb"},
        "Canned black beans":   {"qty": 2,  "unit": "cans"},
        "Shredded cheddar":     {"qty": 8,  "unit": "oz"},
    }
    print("Testing ALDI pricing pipeline (Houston TX)...")
    print("=" * 60)
    name, sid, prices = price_all_aldi(TEST, 29.7515, -95.3615)
    print(f"\nStore: {name} (shopId={sid})")
    print(f"{'Item':<35} {'Cost':>7}  {'Pkg':>5}  Product")
    print("-" * 80)
    for item, d in prices.items():
        print(f"{item:<35} ${d['total_cost']:>5.2f}  ×{d['units_to_buy']:<4.0f}  {d['description'][:35]}")
    missing = [k for k in TEST if k not in prices]
    if missing:
        print(f"\nNo match: {missing}")
