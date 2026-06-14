"""
Generic Instacart pricing — works for any retailer hosted on instacart.com.

All Instacart storefronts share the same GraphQL API and persisted-query hashes.
One shared session (cookies + x-ic-qp + zoneId) cached in .ic_session.json works
across every retailer listed in RETAILER_REGISTRY.

Entry point:
    slug = get_instacart_slug(store_name)          # "publix", "target", etc.
    name, sid, prices = price_all_instacart(ingredients, lat, lon, slug)

prices format (same as kroger_async):
    {ingredient_name: {"total_cost": float, "description": str, ...}}

Retailers covered (via RETAILER_REGISTRY):
    Publix, Safeway, Albertsons, Target, Meijer, Wegmans, H-E-B, Sprouts,
    Giant Food, Giant Eagle, Stop & Shop, ShopRite, Costco, Jewel-Osco,
    Hy-Vee, Food Lion, Winn-Dixie, Whole Foods, Hannaford, Schnucks,
    Vons, Pavilions, Tom Thumb, Randalls, Shaw's, and more.
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
# Retailer registry  (substring → instacart slug, checked longest-first)
# ---------------------------------------------------------------------------

RETAILER_REGISTRY: dict[str, str] = {
    # Ordered longest-first so "giant eagle" beats "giant", etc.
    "giant eagle":        "giant-eagle",
    "giant food":         "giant",
    "stop & shop":        "stop-and-shop",
    "stop and shop":      "stop-and-shop",
    "shop rite":          "shoprite",
    "whole foods":        "whole-foods-market",
    "stater bros":        "stater-bros-markets",
    "harris teeter":      "harris-teeter",
    "star market":        "star-market",
    "market basket":      "market-basket",
    "kings food":         "kings-food-markets",
    "price rite":         "price-rite",
    "food lion":          "food-lion",
    "tom thumb":          "tom-thumb",
    "h-e-b":              "h-e-b",
    "h.e.b":              "h-e-b",
    "hy-vee":             "hy-vee",
    "hy vee":             "hy-vee",
    "hyvee":              "hy-vee",
    "jewel-osco":         "jewel-osco",
    "jewel osco":         "jewel-osco",
    "publix":             "publix",
    "safeway":            "safeway",
    "albertsons":         "albertsons",
    "target":             "target",
    "meijer":             "meijer",
    "wegmans":            "wegmans",
    "sprouts":            "sprouts",
    "shoprite":           "shoprite",
    "costco":             "costco",
    "jewel":              "jewel-osco",
    "heb":                "h-e-b",
    "giant":              "giant",
    "hannaford":          "hannaford",
    "schnucks":           "schnucks",
    "vons":               "vons",
    "pavilions":          "pavilions",
    "randalls":           "randalls",
    "shaws":              "shaws",
    "shaw's":             "shaws",
    "rouses":             "rouses-markets",
    "brookshire":         "brookshires",
    "dierbergs":          "dierbergs-markets",
}

# Sorted by key length descending so longer keys are checked first
_SORTED_REGISTRY = sorted(RETAILER_REGISTRY.items(), key=lambda kv: -len(kv[0]))


def get_instacart_slug(store_name: str) -> Optional[str]:
    """Return the Instacart retailer slug for a given store name, or None."""
    lower = store_name.lower()
    for keyword, slug in _SORTED_REGISTRY:
        if keyword in lower:
            return slug
    return None


def is_instacart_retailer(store_name: str) -> bool:
    return get_instacart_slug(store_name) is not None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_TTL = 2 * 3600
BASE_GQL = "https://www.instacart.com/graphql"
OPERA_PATH = r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe"
_SESSION_CACHE = Path(__file__).parent / ".ic_session.json"

HASHES = {
    "ShopCollectionScoped":    "f20693c3c551f0e0fbdcac9b2ca7aa6db50f9224a39967ba5ac767bb2b598f85",
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
}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

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
            "cookies": cookies, "qp": qp, "zone_id": zone_id,
            "expires_at": time.time() + SESSION_TTL,
        }))
    except Exception:
        pass


def _bootstrap(slug: str = "publix") -> tuple[dict, str, str]:
    """Open the given retailer's Instacart storefront and capture session data."""
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
            viewport={"width": 1366, "height": 768}, locale="en-US",
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
        print(f"[IC] Bootstrapping session via {slug}...", flush=True)
        page.goto(
            f"https://www.instacart.com/store/{slug}/storefront",
            wait_until="domcontentloaded", timeout=30000,
        )
        time.sleep(4)
        for sel in ["button:has-text('Accept All')", "button:has-text('Accept')",
                    "[aria-label='Close']"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1500):
                    el.click(); time.sleep(1); break
            except Exception:
                pass
        page.keyboard.press("Escape")
        time.sleep(8)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    print(f"[IC] Session ready. cookies={len(cookies)}, qp={'yes' if qp else 'no'}, zoneId={zone_id!r}", flush=True)
    return cookies, qp, zone_id


def _get_session(bootstrap_slug: str = "publix") -> tuple[requests.Session, str]:
    global _mem_cache, _session
    if not _mem_cache:
        _mem_cache = _load_disk_session()
    if not _mem_cache:
        cookies, qp, zone_id = _bootstrap(bootstrap_slug)
        _mem_cache = {"cookies": cookies, "qp": qp, "zone_id": zone_id,
                      "expires_at": time.time() + SESSION_TTL}
        _save_disk_session(cookies, qp, zone_id)
        _session = None
    if _session is None:
        _session = requests.Session()
        _session.cookies.update(_mem_cache["cookies"])
        if _mem_cache.get("qp"):
            _session.headers.update({"x-ic-qp": _mem_cache["qp"]})
    return _session, _mem_cache.get("zone_id", "")


def _invalidate_session() -> None:
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

def _gql(op: str, variables: dict, session: requests.Session, slug: str = "") -> dict:
    referer = (f"https://www.instacart.com/{slug}/search_v3/"
               if slug else "https://www.instacart.com/")
    params = {
        "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": HASHES[op]}},
            separators=(",", ":"),
        ),
    }
    headers = {**BASE_HEADERS, "x-page-view-id": str(uuid.uuid4()), "referer": referer}
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
# Postal code lookup
# ---------------------------------------------------------------------------

_postal_cache: dict[tuple[float, float], str] = {}

def _get_postal(lat: float, lon: float) -> str:
    key = (round(lat, 3), round(lon, 3))
    if key in _postal_cache:
        return _postal_cache[key]
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="basket_buddy_ic")
        loc = geo.reverse(f"{lat},{lon}", language="en", timeout=5)
        postal = (loc.raw.get("address", {}).get("postcode") or "") if loc else ""
    except Exception:
        postal = ""
    _postal_cache[key] = postal
    return postal


# ---------------------------------------------------------------------------
# Store discovery
# ---------------------------------------------------------------------------

def find_nearest_store(
    lat: float, lon: float, slug: str, session: requests.Session, zone_id: str,
) -> Optional[tuple[str, str, str]]:
    """
    Find nearest store for the given Instacart retailer slug.
    Returns (shopId, zoneId, display_name) or None.
    """
    postal = _get_postal(lat, lon)
    data = _gql("ShopCollectionScoped", {
        "retailerSlug": slug,
        "postalCode": postal or None,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
        "allowCanonicalFallback": False,
    }, session, slug)
    shops = (data.get("shopCollection") or {}).get("shops") or []
    if not shops:
        return None

    shop = shops[0]
    shop_id = shop.get("id") or ""
    if not shop_id:
        return None

    retailer = shop.get("retailer") or {}
    name = retailer.get("name") or slug.replace("-", " ").title()
    loc = shop.get("retailerLocation") or shop.get("location") or {}
    city = loc.get("city") or ""
    display = f"{name} ({city})" if city else name
    return shop_id, zone_id, display


# ---------------------------------------------------------------------------
# Product format conversion
# ---------------------------------------------------------------------------

def _to_kroger_format(prod: dict) -> Optional[dict]:
    price_sec = ((prod.get("price") or {}).get("viewSection")) or {}
    price_str = price_sec.get("priceValueString")
    try:
        price = float(re.sub(r"[^\d.]", "", str(price_str)))
        if not (0.01 <= price <= 300):
            return None
    except Exception:
        return None
    return {
        "description": prod.get("name") or "",
        "brand": prod.get("brandName") or "",
        "items": [{
            "itemId": str(prod.get("id") or ""),
            "soldBy": "UNIT",
            "size": prod.get("size") or "1 each",
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Relevance filter
# ---------------------------------------------------------------------------

# Non-food items that the loose substring match lets through (e.g. a search
# for "bananas" matching "Turtle Wax Banana Scent"). Always rejected.
_NONFOOD = (
    "wax", "scent", "candle", "soap", "lotion", "shampoo", "detergent",
    "air freshener", "perfume", "deodorant", "lip balm",
)

# Processing qualifiers that usually signal the wrong form of a fresh staple
# (e.g. "Banana Chips", "Frozen Sliced Bananas"). Rejected only when the user
# did NOT ask for that form — so "dried black beans" still matches "dried".
_QUALIFIERS = (
    "chips", "frozen", "dried", "freeze-dried", "freeze dried", "dehydrated",
    "powder", "powdered", "flavored", "candied", "pickled",
    "spray", "no-stick", "non-stick", "nonstick",
)


def _is_relevant(name: str, query: str) -> bool:
    """True if a product name is a plausible match for the search query."""
    if any(bad in name for bad in _NONFOOD):
        return False
    for q in _QUALIFIERS:
        if q in name and q not in query:
            return False
    return True


# ---------------------------------------------------------------------------
# Search + price helpers
# ---------------------------------------------------------------------------

def _search_and_fetch(
    query: str, shop_id: str, zone_id: str, postal: str,
    session: requests.Session, slug: str,
) -> list[dict]:
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
    }, session, slug)

    ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', json.dumps(d))))[:20]
    if not ids:
        return []

    d2 = _gql("Items", {
        "ids": ids,
        "shopId": shop_id,
        "zoneId": zone_id if zone_id else None,
        "postalCode": postal or None,
    }, session, slug)
    products = d2.get("items") or []

    query_low = query.lower()
    query_words = set(query_low.split())
    results = []
    for prod in products:
        name = (prod.get("name") or "").lower()
        name_words = set(name.split())
        if not any(qw in nw or nw in qw for qw in query_words for nw in name_words):
            continue
        if not _is_relevant(name, query_low):
            continue
        fmt = _to_kroger_format(prod)
        if fmt:
            results.append(fmt)
    return results


def _price_one(
    ingredient: str, qty: float, unit: str,
    shop_id: str, zone_id: str, postal: str,
    session: requests.Session, slug: str,
) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search_and_fetch(term, shop_id, zone_id, postal, session, slug)
        if products:
            result = find_best_purchase(ingredient, qty, unit, products)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_instacart(
    ingredients: dict,
    lat: float,
    lon: float,
    slug: str,
    max_workers: int = 10,
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest store for the given Instacart slug.

    Parameters
    ----------
    ingredients : {name: {"qty": float, "unit": str, ...}}
    lat, lon    : user coordinates
    slug        : Instacart retailer slug (e.g. "publix", "target")
    max_workers : parallel threads

    Returns
    -------
    (store_display_name, shop_id, prices)
    """
    session, zone_id = _get_session(bootstrap_slug=slug)

    store_info = find_nearest_store(lat, lon, slug, session, zone_id)
    if not store_info:
        print(f"[IC:{slug}] No store found near this location.", flush=True)
        return None, None, {}

    shop_id, store_zone, display_name = store_info
    effective_zone = zone_id or store_zone
    postal = _get_postal(lat, lon)
    print(f"[IC:{slug}] Pricing at: {display_name} (shopId={shop_id})", flush=True)

    prices: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _price_one,
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
                shop_id, effective_zone, postal, session, slug,
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
                print(f"[IC:{slug}] Error pricing '{name}': {e}", flush=True)

    print(f"[IC:{slug}] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return display_name, shop_id, prices
