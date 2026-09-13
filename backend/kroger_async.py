"""
kroger_async.py

Async Kroger pricing pipeline. Prices all ingredients concurrently using
aiohttp, then returns real prices in the format the optimizer expects.

Entry point (call from sync code with asyncio.run):
    store_name, store_id, prices = asyncio.run(price_all_async(ingredients, lat, lon))

prices format:
    {ingredient_name: {"total_cost": float, "description": str, "brand": str,
                       "size_str": str, "units_to_buy": float, "unit": str}}
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

load_dotenv("config.env")
_CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
_CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
_BASE_URL = "https://api-ce.kroger.com/v1"

# Kroger's /products endpoint 5xx/429s under concurrent load; retry those (and
# timeouts) on the SAME term with jittered backoff before giving up on it — a bare
# "move to the next term" silently drops items when the whole store is throttled.
_RETRY_STATUS = {429, 500, 502, 503, 504}
_PRODUCT_RETRIES = int(os.getenv("KROGER_PRODUCT_RETRIES", "3"))

# Kroger-family banner names (used to match a Google Maps store name to the
# Kroger API). NOTE: "Food Lion" is deliberately NOT here — it's an Ahold Delhaize
# banner, not Kroger; routing it here would mis-price it as the nearest real Kroger.
KROGER_BANNERS = {
    "kroger", "king soopers", "city market", "dillons", "food 4 less", "foods co",
    "fred meyer", "fry's", "frys", "gerbes", "harris teeter", "jay c",
    "mariano", "pay-less", "pay less", "pick 'n save", "pick n save",
    "metro market", "qfc", "ralphs", "ruler foods",
    "smith's", "smiths", "baker's", "owen's",
}

# Google Places banner name  ->  Kroger API `chain` code. The API's `chain` is an
# abbreviated code, NOT the display name (verified live: Harris Teeter -> HART,
# Fred Meyer -> FRED, Food 4 Less -> FOOD4LESS), so we can't match on the name —
# this map lets us resolve a route's specific banner in overlap markets (e.g.
# Ralphs + Food 4 Less in SoCal, Fred Meyer + QFC in the Pacific NW). Unmapped
# banners simply fall back to "nearest Kroger-family store", which is correct in
# the common single-banner market. Keys are matched as apostrophe-stripped
# substrings of the store name.
BANNER_TO_CHAIN = {
    "kroger": "KROGER", "ralphs": "RALPHS", "food 4 less": "FOOD4LESS",
    "foods co": "FOODSCO", "qfc": "QFC", "harris teeter": "HART",
    "mariano": "MARIANOS", "fry": "FRYS", "king soopers": "KINGSOOPERS",
    "smith": "SMITHS", "dillons": "DILLONS", "fred meyer": "FRED",
    "city market": "CITYMARKET", "metro market": "METRO MARKET",
    "pick n save": "PICK N SAVE", "baker": "BAKERS", "gerbes": "GERBES",
    "jay c": "JAYC",
}


def is_kroger_banner(store_name: str) -> bool:
    """Return True if store_name matches any Kroger-family banner.

    Matches as a LEADING term (`startswith`), not "anywhere in the string" —
    confirmed 2026-09-13 that substring-anywhere false-positives on generic
    banner names: Google Places returned a real, unaffiliated small grocery
    named "H L Foods Co [...]" that got misrouted here purely because "foods
    co" appears mid-name, then failed against the Kroger API (which has no
    record of it, correctly) with no indication anywhere that the match
    itself was the actual problem. A real chain listing is always named
    "<Banner> ..." (e.g. "Ralphs", "Food 4 Less #123"), never "<other text>
    <Banner> ...", so requiring the banner as a prefix keeps every genuine
    match (verified against probe_kroger_banners.py's confirmed listings)
    while dropping names that merely contain the words somewhere later on."""
    lower = store_name.lower().strip()
    return any(lower.startswith(banner) for banner in KROGER_BANNERS)


def _chain_for(store_name: Optional[str]) -> Optional[str]:
    """Map a Google Places banner name to its Kroger API `chain` code, or None.
    Prefix match — see is_kroger_banner's docstring for why not substring."""
    if not store_name:
        return None
    lower = store_name.lower().strip().replace("'", "")
    for sub, code in BANNER_TO_CHAIN.items():
        if lower.startswith(sub.replace("'", "")):
            return code
    return None


async def _get_token(session: aiohttp.ClientSession) -> Optional[str]:
    # The token endpoint is fast (~0.5s) but occasionally times out under load
    # when other stores are warming headless browsers. A 25s budget + one retry
    # makes it reliable. Note: asyncio.TimeoutError stringifies to '', so we log
    # the exception *type* — otherwise a timeout prints as a blank "Token error:".
    for attempt in (1, 2):
        try:
            async with session.post(
                f"{_BASE_URL}/connect/oauth2/token",
                data={"grant_type": "client_credentials", "scope": "product.compact"},
                auth=aiohttp.BasicAuth(_CLIENT_ID, _CLIENT_SECRET),
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                data = await resp.json(content_type=None)
                token = data.get("access_token")
                if token:
                    return token
                print(f"[Kroger] Token request returned no access_token "
                      f"(status={resp.status}, attempt {attempt}/2).")
        except Exception as e:
            detail = str(e) or type(e).__name__  # TimeoutError() → '' otherwise
            print(f"[Kroger] Token error (attempt {attempt}/2): {detail}")
    return None


# Location names that aren't shoppable grocery stores — /locations returns fuel
# centers and internal test stores ("E2E Lab", "Picking Lab") whose IDs 400 on
# /products, so drop them before we ever pick one.
_JUNK_LOCATION_TOKENS = ("distribution", "fuel", "lab", "picking")


def _display_name(store: dict) -> str:
    chain = store.get("chain", "Kroger")
    city = store.get("address", {}).get("city", "")
    return f"{chain} ({city})" if city else chain


async def _store_has_products(
    session: aiohttp.ClientSession, token: str, loc_id: str
) -> bool:
    """Liveness probe: does /products actually resolve for this location? Many
    location IDs from /locations (notably most Fred Meyer stores) come back 400
    PRODUCT-4109-404 ('No location found') even though the store is real."""
    try:
        async with session.get(
            f"{_BASE_URL}/products",
            headers={"Authorization": f"Bearer {token}"},
            params={"filter.term": "milk", "filter.locationId": loc_id, "filter.limit": 1},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return False
            data = await resp.json(content_type=None)
            return bool(data.get("data"))
    except Exception:
        return False


async def find_nearest_kroger_store(
    session: aiohttp.ClientSession,
    token: str,
    lat: float,
    lon: float,
    want_banner: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """
    Find the nearest *shoppable* Kroger-family store. When want_banner is given
    (the route's Google Places name, e.g. "Ralphs"), prefer the location whose API
    `chain` code matches that banner; fall back to the nearest store of any banner
    when the market has only one (the common case) or the banner can't be matched.

    Not every location ID that /locations returns actually resolves in /products
    (fuel/lab/stale records 400), so we liveness-probe the nearest candidates
    concurrently and pick the nearest live one — otherwise a dead top result (the
    default for Fred Meyer) silently zeroes out the whole banner.

    Returns (location_id, display_name) or None if none found within 20 miles.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(
            f"{_BASE_URL}/locations",
            headers=headers,
            params={
                "filter.latLong.near": f"{lat},{lon}",
                # Wide net: some banners (King Soopers) have a whole cluster of dead
                # IDs nearest the point before a live store appears, so 15 wasn't
                # enough to reach one.
                "filter.limit": 30,
                "filter.radiusInMiles": 25,
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
    except Exception as e:
        print(f"[Kroger] Location lookup error: {e}")
        return None

    stores = [
        s for s in data.get("data", [])
        if not any(tok in (s.get("name") or "").lower() for tok in _JUNK_LOCATION_TOKENS)
    ]
    if not stores:
        return None

    # Order candidates: requested banner first (correct chain in overlap markets),
    # then any other Kroger-family store as a fallback.
    want_chain = _chain_for(want_banner)
    if want_chain:
        matched = [s for s in stores if (s.get("chain") or "").upper() == want_chain]
        others = [s for s in stores if (s.get("chain") or "").upper() != want_chain]
        candidates = matched + others
        if not matched:
            print(f"[Kroger] No '{want_chain}' store near — using nearest "
                  f"Kroger-family store instead.", flush=True)
    else:
        candidates = stores

    probe = [c for c in candidates if c.get("locationId")]
    # Fast path: the nearest candidate is usually live — one probe, done.
    if probe and await _store_has_products(session, token, probe[0]["locationId"]):
        return probe[0]["locationId"], _display_name(probe[0])
    # Slow path (dense dead-ID markets like King Soopers): probe the rest
    # concurrently and take the nearest that's live.
    rest = probe[1:24]
    live = await asyncio.gather(
        *(_store_has_products(session, token, c["locationId"]) for c in rest)
    )
    for store, is_live in zip(rest, live):
        if is_live:
            return store["locationId"], _display_name(store)

    # None validated — return the top candidate anyway (no worse than before).
    top = candidates[0]
    print(f"[Kroger] No live product endpoint among nearest "
          f"{top.get('chain','Kroger')} stores — trying {top.get('locationId')} anyway.",
          flush=True)
    return top.get("locationId", ""), _display_name(top)


async def _fetch_products(
    session: aiohttp.ClientSession, token: str, term: str, store_id: str
) -> list:
    """GET /products for one term, retrying transient 5xx/429/timeout on the same
    term with jittered backoff. Returns the products list ([] if unavailable or a
    non-transient status like 400/404)."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter.term": term, "filter.locationId": store_id, "filter.limit": 10}
    for attempt in range(_PRODUCT_RETRIES):
        try:
            async with session.get(
                f"{_BASE_URL}/products", headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status == 200:
                    return (await resp.json(content_type=None)).get("data", [])
                if resp.status not in _RETRY_STATUS:
                    return []  # non-transient (e.g. 400/404) — this term is a dead end
        except asyncio.TimeoutError:
            pass  # transient — fall through to backoff + retry
        except Exception as e:
            print(f"[Kroger] Error on '{term}': {e}")
            return []
        if attempt < _PRODUCT_RETRIES - 1:
            await asyncio.sleep(0.4 * (attempt + 1) + random.uniform(0, 0.3))
    return []


async def _price_one_ingredient(
    session: aiohttp.ClientSession,
    token: str,
    store_id: str,
    ingredient_name: str,
    target_qty: float,
    target_unit: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, Optional[dict]]:
    """
    Search all fallback terms for one ingredient and return the cheapest
    total-cost purchase option that meets the target quantity.
    Returns (ingredient_name, find_best_purchase result or None).
    """
    terms = get_all_terms(ingredient_name)

    for term in terms:
        async with semaphore:  # hold the slot through retries → backpressure under 503s
            products = await _fetch_products(session, token, term, store_id)
        if products:
            result = find_best_purchase(ingredient_name, target_qty, target_unit, products)
            if result:
                return ingredient_name, result

    return ingredient_name, None


async def price_all_async(
    ingredients: dict,
    lat: float,
    lon: float,
    store_name: Optional[str] = None,
    max_concurrent: int = 40,
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest Kroger-family store concurrently.

    Parameters
    ----------
    ingredients : dict
        {ingredient_name: {"qty": float, "unit": str, ...}}
    lat, lon : float
        User coordinates.
    store_name : str or None
        The route's banner name (e.g. "Ralphs"); used to resolve the specific
        Kroger-family banner in overlap markets. None ⇒ nearest of any banner.
    max_concurrent : int
        Cap on simultaneous Kroger API calls. Default 40 avoids rate limits.

    Returns
    -------
    (store_display_name, store_location_id, prices)
        store_display_name : str or None
        store_location_id  : str or None
        prices             : {ingredient_name: find_best_purchase() result dict}
                            Empty dict if no Kroger store found or all searches fail.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    connector = aiohttp.TCPConnector(limit=max_concurrent + 10)

    async with aiohttp.ClientSession(connector=connector) as session:
        token = await _get_token(session)
        if not token:
            print("[Kroger] Could not obtain token — skipping real pricing.")
            return None, None, {}

        store_info = await find_nearest_kroger_store(session, token, lat, lon, store_name)
        if not store_info:
            print("[Kroger] No Kroger-family store found within 20 miles.")
            return None, None, {}

        store_id, store_display_name = store_info
        print(f"[Kroger] Pricing at: {store_display_name} (id={store_id})", flush=True)

        tasks = [
            _price_one_ingredient(
                session, token, store_id,
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
                semaphore,
            )
            for name, data in ingredients.items()
        ]

        results = await asyncio.gather(*tasks)

    prices = {name: result for name, result in results if result is not None}
    print(f"[Kroger] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return store_display_name, store_id, prices
