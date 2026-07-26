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
    Hy-Vee, Food Lion, Winn-Dixie, Hannaford, Schnucks,
    Vons, Pavilions, Tom Thumb, Randalls, Shaw's, and more.
"""
from __future__ import annotations

import json
import math
import re
import threading
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
# Serializes session bootstrap so concurrent callers (Whole Foods, a Target/
# Walmart Instacart fallback, Costco) don't each launch a bootstrap browser and
# clobber the shared session.
_session_lock = threading.Lock()


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
    from browser_gate import launch  # gated: 1 browser at a time + low-mem flags (was cloakbrowser.launch)

    cookies: dict = {}
    qp: str = ""
    zone_id: str = ""

    browser = launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768}, locale="en-US",
        user_agent=BASE_HEADERS["user-agent"],
    )
    page = ctx.new_page()

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
    # Fast path: a built session can be shared across threads without locking.
    if _session is not None and _mem_cache:
        return _session, _mem_cache.get("zone_id", "")
    # Slow path: only one thread bootstraps; the rest wait and reuse the result.
    with _session_lock:
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
# Nearest-covered-store search (expanding rings) — used by the Costco proxy
# ---------------------------------------------------------------------------
#
# Costco's grocery prices are near-uniform nationally (a handful of regional
# tiers, not per-store variation), so when the user's local warehouse isn't on
# Instacart Same-Day we can price at the nearest *covered* Costco and flag the
# result as an estimate. This is ONLY sound for Costco — chains like Kroger /
# Safeway price per store, so a distant proxy would be misleading for them.


# Major US metros (postal, lat, lon) used as proxy anchors. ShopCollectionScoped
# REQUIRES a postal (coordinates alone return nothing), so we can't jitter
# arbitrary points — instead we walk these known postals outward from the user.
# The runtime query confirms Costco coverage, so a listed metro without Same-Day
# is simply skipped; a generous, well-spread list just improves nearest-distance
# resolution. (lat, lon, postal, label)
_US_METROS: tuple[tuple[float, float, str, str], ...] = (
    (47.61, -122.33, "98101", "Seattle, WA"), (45.52, -122.68, "97201", "Portland, OR"),
    (47.66, -117.43, "99201", "Spokane, WA"), (43.62, -116.21, "83702", "Boise, ID"),
    (37.77, -122.42, "94102", "San Francisco, CA"), (37.34, -121.89, "95110", "San Jose, CA"),
    (38.58, -121.49, "95814", "Sacramento, CA"), (36.74, -119.79, "93721", "Fresno, CA"),
    (34.05, -118.24, "90012", "Los Angeles, CA"), (32.72, -117.16, "92101", "San Diego, CA"),
    (36.17, -115.14, "89101", "Las Vegas, NV"), (39.53, -119.81, "89501", "Reno, NV"),
    (33.45, -112.07, "85004", "Phoenix, AZ"), (32.22, -110.97, "85701", "Tucson, AZ"),
    (40.76, -111.89, "84101", "Salt Lake City, UT"), (39.74, -104.99, "80202", "Denver, CO"),
    (38.83, -104.82, "80903", "Colorado Springs, CO"), (35.08, -106.65, "87102", "Albuquerque, NM"),
    (31.76, -106.49, "79901", "El Paso, TX"), (32.78, -96.80, "75201", "Dallas, TX"),
    (29.76, -95.37, "77002", "Houston, TX"), (29.42, -98.49, "78205", "San Antonio, TX"),
    (30.27, -97.74, "78701", "Austin, TX"), (26.20, -98.23, "78501", "McAllen, TX"),
    (33.58, -101.86, "79401", "Lubbock, TX"), (35.47, -97.52, "73102", "Oklahoma City, OK"),
    (36.15, -95.99, "74103", "Tulsa, OK"), (37.69, -97.34, "67202", "Wichita, KS"),
    (39.10, -94.58, "64106", "Kansas City, MO"), (38.63, -90.20, "63101", "St. Louis, MO"),
    (41.26, -95.93, "68102", "Omaha, NE"), (44.98, -93.27, "55401", "Minneapolis, MN"),
    (41.59, -93.62, "50309", "Des Moines, IA"), (43.55, -96.70, "57104", "Sioux Falls, SD"),
    (46.88, -96.79, "58102", "Fargo, ND"), (41.88, -87.63, "60601", "Chicago, IL"),
    (43.04, -87.91, "53202", "Milwaukee, WI"), (39.77, -86.16, "46204", "Indianapolis, IN"),
    (39.96, -82.99, "43215", "Columbus, OH"), (41.50, -81.69, "44114", "Cleveland, OH"),
    (39.10, -84.51, "45202", "Cincinnati, OH"), (42.33, -83.05, "48226", "Detroit, MI"),
    (42.96, -85.67, "49503", "Grand Rapids, MI"), (36.16, -86.78, "37203", "Nashville, TN"),
    (35.15, -90.05, "38103", "Memphis, TN"), (35.96, -83.92, "37902", "Knoxville, TN"),
    (38.25, -85.76, "40202", "Louisville, KY"), (33.75, -84.39, "30303", "Atlanta, GA"),
    (35.23, -80.84, "28202", "Charlotte, NC"), (35.78, -78.64, "27601", "Raleigh, NC"),
    (36.07, -79.79, "27401", "Greensboro, NC"), (33.52, -86.81, "35203", "Birmingham, AL"),
    (29.95, -90.07, "70112", "New Orleans, LA"), (30.45, -91.19, "70801", "Baton Rouge, LA"),
    (34.75, -92.29, "72201", "Little Rock, AR"), (30.33, -81.66, "32202", "Jacksonville, FL"),
    (28.54, -81.38, "32801", "Orlando, FL"), (27.95, -82.46, "33602", "Tampa, FL"),
    (25.76, -80.19, "33131", "Miami, FL"), (32.78, -79.93, "29401", "Charleston, SC"),
    (34.00, -81.03, "29201", "Columbia, SC"), (37.54, -77.44, "23219", "Richmond, VA"),
    (36.85, -75.98, "23451", "Virginia Beach, VA"), (38.91, -77.02, "20001", "Washington, DC"),
    (39.29, -76.61, "21201", "Baltimore, MD"), (39.95, -75.16, "19102", "Philadelphia, PA"),
    (40.44, -79.99, "15222", "Pittsburgh, PA"), (40.75, -73.99, "10001", "New York, NY"),
    (40.74, -74.17, "07102", "Newark, NJ"), (41.76, -72.67, "06103", "Hartford, CT"),
    (42.36, -71.06, "02108", "Boston, MA"), (41.82, -71.41, "02903", "Providence, RI"),
    (43.66, -70.26, "04101", "Portland, ME"), (42.99, -71.46, "03101", "Manchester, NH"),
    (42.65, -73.75, "12207", "Albany, NY"), (42.89, -78.88, "14202", "Buffalo, NY"),
    (43.16, -77.61, "14604", "Rochester, NY"), (45.78, -108.50, "59101", "Billings, MT"),
    (46.87, -113.99, "59802", "Missoula, MT"), (21.31, -157.86, "96813", "Honolulu, HI"),
    (61.22, -149.90, "99501", "Anchorage, AK"),
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _shop_at_postal(
    lat: float, lon: float, postal: str, slug: str,
    session: requests.Session, zone_id: str,
) -> Optional[tuple[str, str, str]]:
    """ShopCollectionScoped at an explicit (lat, lon, postal). Returns
    (shop_id, zone, "Name (City)") or None when no shop serves that postal."""
    data = _gql("ShopCollectionScoped", {
        "retailerSlug": slug,
        "postalCode": postal,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
        "allowCanonicalFallback": False,  # only real serving shops, no fake fallback
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
    return shop_id, zone_id, (f"{name} ({city})" if city else name)


def find_covered_store_expanding(
    lat: float, lon: float, slug: str, session: requests.Session, zone_id: str,
    max_metros: int = 12,
) -> Optional[tuple[str, str, str, float]]:
    """Find the nearest Instacart-covered store, walking outward through known
    metro postals.

    Returns (shop_id, zone, display_name, distance_km) or None. distance_km == 0
    means the store serves the user's exact location (an exact price, not an
    estimate). A positive distance means the nearest covered store is that far
    away and the price should be treated as an estimate.
    """
    # 1. Exact location first (uses the user's real postal — reliable).
    local = find_nearest_store(lat, lon, slug, session, zone_id)
    if local:
        return local[0], local[1], local[2], 0.0

    # 2. Walk the nearest metros outward; the GQL query confirms coverage.
    ranked = sorted(_US_METROS, key=lambda m: _haversine_km(lat, lon, m[0], m[1]))
    for mlat, mlon, mpostal, _label in ranked[:max_metros]:
        s = _shop_at_postal(mlat, mlon, mpostal, slug, session, zone_id)
        if s:
            return s[0], s[1], s[2], _haversine_km(lat, lon, mlat, mlon)
    return None


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


def _price_ingredients_at(
    ingredients: dict, shop_id: str, zone_id: str, postal: str,
    session: requests.Session, slug: str, max_workers: int = 10,
) -> dict:
    """Run the search+price loop for every ingredient at a resolved store."""
    prices: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _price_one,
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
                shop_id, zone_id, postal, session, slug,
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
    return prices


def price_all_costco(
    ingredients: dict,
    lat: float,
    lon: float,
    max_workers: int = 10,
) -> tuple[Optional[str], Optional[str], dict, dict]:
    """
    Price all ingredients at Costco via Instacart, with a national-uniform-price
    PROXY fallback for markets where the local warehouse isn't on Same-Day.

    Costco's grocery prices are near-uniform nationally, so when no Costco serves
    the user's exact location we price at the nearest *covered* Costco and flag
    the result as an estimate. (This proxy is sound only for Costco — see
    find_covered_store_expanding.)

    Returns (display_name, shop_id, prices, meta) where
        meta = {"is_estimate": bool, "distance_km": float|None, "store": str}.
    prices is empty (and the caller drops Costco) only if no covered Costco
    exists within the search radius.
    """
    slug = "costco"
    session, zone_id = _get_session(bootstrap_slug=slug)

    found = find_covered_store_expanding(lat, lon, slug, session, zone_id)
    if not found:
        print("[IC:costco] No covered Costco within range — excluding.", flush=True)
        return None, None, {}, {"is_estimate": False, "distance_km": None, "store": ""}

    shop_id, store_zone, display_name, dist = found
    effective_zone = zone_id or store_zone
    is_estimate = dist > 0
    # The user's own postal is fine for the search payload context; the shopId +
    # zoneId are what actually pin pricing to the (proxy) warehouse.
    postal = _get_postal(lat, lon)

    if is_estimate:
        print(f"[IC:costco] Local Costco not on Instacart — using nearest covered "
              f"Costco '{display_name}' (~{int(dist)} km) as a national-price estimate.",
              flush=True)
    else:
        print(f"[IC:costco] Pricing at: {display_name} (shopId={shop_id})", flush=True)

    prices = _price_ingredients_at(
        ingredients, shop_id, effective_zone, postal, session, slug, max_workers
    )
    print(f"[IC:costco] Priced {len(prices)}/{len(ingredients)} ingredients"
          f"{' (estimate)' if is_estimate else ''}.", flush=True)

    meta = {"is_estimate": is_estimate, "distance_km": dist, "store": display_name}
    return display_name, shop_id, prices, meta
