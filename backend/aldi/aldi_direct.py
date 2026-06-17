"""
ALDI pricing via Instacart GraphQL — direct HTTP after a one-shot Playwright session bootstrap.

Flow:
  1. Playwright opens ALDI once, accepts cookies, clicks Delivery.
     We capture the browser cookies + x-ic-qp session header.
  2. Playwright closes — all further calls are plain requests.GET.
  3. For each ingredient:
       a. SearchResultsPlacements  → item IDs
       b. Items                    → prices
  4. Results cached 24 h.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Optional
import requests
from cloakbrowser import launch
from cache_manager import cache

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_GQL = "https://www.aldi.us/graphql"
CACHE_TTL = 60 * 60 * 24   # 24 h

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
# Session bootstrap (Playwright, one-shot)
# ---------------------------------------------------------------------------

def _bootstrap_session() -> tuple[dict, str, str]:
    """
    Open ALDI in Opera, accept cookies, click Delivery.
    Returns (cookies_dict, x_ic_qp_value, zone_id).
    Also captures the zoneId from the first Items GraphQL request on the page.
    """
    cookies_dict: dict = {}
    qp_value: str = ""
    zone_id: str = ""

    browser = launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        user_agent=BASE_HEADERS["user-agent"],
    )
    page = ctx.new_page()

        def on_request(req):
            nonlocal qp_value, zone_id
            if "graphql" not in req.url:
                return
            # Capture x-ic-qp
            if not qp_value:
                qp = req.headers.get("x-ic-qp", "")
                if qp:
                    qp_value = qp
            # Capture zoneId from Items requests
            if "operationName=Items" in req.url and not zone_id:
                try:
                    import urllib.parse
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
                    v = json.loads(qs.get("variables", ["{}"])[0])
                    z = v.get("zoneId") or v.get("zone_id") or ""
                    if z:
                        zone_id = str(z)
                except Exception:
                    pass

        page.on("request", on_request)

        print("[ALDI] Bootstrapping guest session...", flush=True)
        page.goto("https://www.aldi.us/store/aldi/s?query=eggs", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Accept cookies
        for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(2)
                    print("[ALDI] Accepted cookies", flush=True)
                    break
            except Exception:
                pass

        # Click Delivery to unlock store pricing
        for sel in ["text=Delivery", "a:has-text('Delivery')", "div[role='button']:has-text('Delivery')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2500):
                    el.click()
                    time.sleep(3)
                    print("[ALDI] Set fulfillment to Delivery", flush=True)
                    break
            except Exception:
                pass

        # Wait for Items GraphQL to fire so we capture zoneId + qp
        time.sleep(8)

        raw_cookies = ctx.cookies()
        cookies_dict = {c["name"]: c["value"] for c in raw_cookies}
        browser.close()

    print(f"[ALDI] Session ready. Cookies: {len(cookies_dict)}, qp={'yes' if qp_value else 'no'}, zoneId={zone_id!r}", flush=True)
    return cookies_dict, qp_value, zone_id


# ---------------------------------------------------------------------------
# GraphQL caller (requests)
# ---------------------------------------------------------------------------

def _gql(operation: str, variables: dict, session: requests.Session) -> dict:
    params = {
        "operationName": operation,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({
            "persistedQuery": {"version": 1, "sha256Hash": HASHES[operation]}
        }, separators=(",", ":")),
    }
    headers = {**BASE_HEADERS, "x-page-view-id": str(uuid.uuid4())}
    try:
        r = session.get(BASE_GQL, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        if "errors" in data:
            return {}
        return data.get("data") or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Store discovery (no auth needed)
# ---------------------------------------------------------------------------

def _find_aldi_shop(postal_code: str, lat: float, lon: float, session: requests.Session) -> tuple[str, str]:
    """Returns (shopId, zoneId) for the nearest ALDI."""
    cache_key = {"aldi_shop": postal_code}
    cached = cache.get(cache_key, max_age_seconds=60 * 60 * 24 * 7)  # 1 week
    if cached:
        return cached["shopId"], cached["zoneId"]

    data = _gql("DefaultShop", {
        "postalCode": postal_code,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
    }, session)

    shop = data.get("defaultShop") or {}
    shop_id = shop.get("id", "")
    # zoneId lives in a nested field; fall back to empty and let the API use defaults
    zone_id = shop.get("zoneId") or ""
    if not zone_id:
        # Try to extract from viewSection ids which encode the zone
        raw = json.dumps(shop)
        m = re.search(r'"zoneId"\s*:\s*"(\d+)"', raw)
        zone_id = m.group(1) if m else ""

    if shop_id:
        cache.set(cache_key, {"shopId": shop_id, "zoneId": zone_id})
    return shop_id, zone_id


# ---------------------------------------------------------------------------
# Item search + pricing
# ---------------------------------------------------------------------------

def _search_items(query: str, shop_id: str, postal: str, zone_id: str,
                  session: requests.Session) -> list[str]:
    """Returns list of item IDs from SearchResultsPlacements."""
    data = _gql("SearchResultsPlacements", {
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
        "postalCode": postal,
        "zoneId": zone_id if zone_id else None,
        "first": 20,
    }, session)

    raw = json.dumps(data)
    return list(dict.fromkeys(re.findall(r'items_\d+-\d+', raw)))  # preserve order, dedup


def _fetch_items(ids: list[str], shop_id: str, postal: str, zone_id: str,
                 session: requests.Session) -> list[dict]:
    """Returns product dicts with prices from Items operation."""
    if not ids:
        return []
    data = _gql("Items", {
        "ids": ids[:20],
        "shopId": shop_id,
        "zoneId": zone_id if zone_id else None,
        "postalCode": postal,
    }, session)
    return data.get("items") or []


def _parse_price(price_str) -> Optional[float]:
    if not price_str:
        return None
    try:
        val = float(re.sub(r"[^\d.]", "", str(price_str)))
        return val if 0.01 <= val <= 300 else None
    except (ValueError, TypeError):
        return None


def _best_match(items: list[dict], query: str) -> Optional[dict]:
    query_words = set(query.lower().split())
    candidates = []
    for item in items:
        name = item.get("name") or ""
        size = item.get("size") or ""
        price_sec = ((item.get("price") or {}).get("viewSection")) or {}
        price = _parse_price(price_sec.get("priceValueString"))
        if price is None:
            continue
        unit = ""
        try:
            unit = price_sec["itemDetails"]["pricePerUnitString"] or ""
        except (KeyError, TypeError):
            pass
        unit = unit or size or "each"
        name_lower = name.lower()
        name_words = set(name_lower.split())
        # Match if query word is substring of a name word OR vice versa (handles banana/bananas)
        relevance = sum(
            1 for qw in query_words
            if any(qw in nw or nw in qw for nw in name_words)
        )
        candidates.append({"price": price, "unit": unit, "name": name, "relevance": relevance})

    if not candidates:
        return None
    best = max(candidates, key=lambda x: (x["relevance"], -x["price"]))
    return best if best["relevance"] > 0 else None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_aldi_prices(items: list, postal_code: str, lat: float, lon: float) -> dict[str, dict]:
    """
    Fetch real ALDI prices for a list of grocery items.
    Returns {item_name: {"price": float, "unit": str, "name": str}}.
    Items with no match omitted. Results cached 24 h.
    """
    results = {}
    to_fetch = []
    for item in items:
        ck = {"aldi_item_v2": item.lower().strip(), "postal": postal_code}
        cached = cache.get(ck, max_age_seconds=CACHE_TTL)
        if cached is not None:
            results[item] = cached
            print(f"  [ALDI] {item!r} -> cached ${cached['price']:.2f}", flush=True)
        else:
            to_fetch.append(item)

    if not to_fetch:
        return results

    # Bootstrap browser session once — also captures zoneId from page Items requests
    cookies, qp, bootstrapped_zone_id = _bootstrap_session()

    session = requests.Session()
    session.cookies.update(cookies)
    if qp:
        session.headers.update({"x-ic-qp": qp})

    shop_id, zone_id = _find_aldi_shop(postal_code, lat, lon, session)
    # Prefer the zoneId captured from the live browser (more reliable than DefaultShop)
    if bootstrapped_zone_id and not zone_id:
        zone_id = bootstrapped_zone_id
    if not shop_id:
        print("[ALDI] Could not find ALDI store for this location.", flush=True)
        return results

    print(f"[ALDI] Store found: shopId={shop_id} zoneId={zone_id}", flush=True)

    for item in to_fetch:
        print(f"  [ALDI] Searching {item!r}...", flush=True)
        ids = _search_items(item, shop_id, postal_code, zone_id, session)
        print(f"    -> {len(ids)} item IDs", flush=True)

        if not ids:
            continue

        products = _fetch_items(ids, shop_id, postal_code, zone_id, session)
        match = _best_match(products, item)
        if match:
            ck = {"aldi_item_v2": item.lower().strip(), "postal": postal_code}
            cache.set(ck, match)
            results[item] = match
            print(f"    -> ${match['price']:.2f} [{match['unit']}] — {match['name'][:50]}", flush=True)
        else:
            print(f"    -> no match", flush=True)

    return results


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST = ["bananas", "whole milk", "chicken breast", "eggs", "spinach"]
    print("Testing ALDI direct pricing (Houston 77003)...")
    print("=" * 60)
    prices = fetch_aldi_prices(TEST, "77003", 29.7515, -95.3615)
    print("\nResults:")
    for item, d in prices.items():
        print(f"  {item:<22} ${d['price']:.2f}  [{d['unit']}]  {d['name'][:40]}")
    missing = [i for i in TEST if i not in prices]
    if missing:
        print(f"\nNo match: {missing}")
