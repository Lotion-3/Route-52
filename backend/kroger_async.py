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
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

load_dotenv("config.env")
_CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
_CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
_BASE_URL = "https://api-ce.kroger.com/v1"

# Kroger-family banner names (used to match against Google Maps store names)
KROGER_BANNERS = {
    "kroger", "king soopers", "city market", "dillons", "food 4 less",
    "fred meyer", "fry's", "frys", "gerbes", "harris teeter", "jay c",
    "mariano", "pay-less", "pick 'n save", "qfc", "ralphs", "ruler foods",
    "smith's", "smiths", "food lion", "baker's", "owen's",
}


def is_kroger_banner(store_name: str) -> bool:
    """Return True if store_name matches any Kroger-family banner."""
    lower = store_name.lower()
    return any(banner in lower for banner in KROGER_BANNERS)


async def _get_token(session: aiohttp.ClientSession) -> Optional[str]:
    try:
        async with session.post(
            f"{_BASE_URL}/connect/oauth2/token",
            data={"grant_type": "client_credentials", "scope": "product.compact"},
            auth=aiohttp.BasicAuth(_CLIENT_ID, _CLIENT_SECRET),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
            return data.get("access_token")
    except Exception as e:
        print(f"[Kroger] Token error: {e}")
        return None


async def find_nearest_kroger_store(
    session: aiohttp.ClientSession,
    token: str,
    lat: float,
    lon: float,
) -> Optional[tuple[str, str]]:
    """
    Find the nearest Kroger-family store.
    Returns (location_id, display_name) or None if none found within 20 miles.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(
            f"{_BASE_URL}/locations",
            headers=headers,
            params={
                "filter.latLong.near": f"{lat},{lon}",
                "filter.limit": 3,
                "filter.radiusInMiles": 20,
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
            stores = data.get("data", [])
            if not stores:
                return None
            store = next(
                (s for s in stores if "distribution" not in (s.get("name") or "").lower()),
                stores[0],
            )
            loc_id = store.get("locationId", "")
            chain = store.get("chain", "Kroger")
            city = store.get("address", {}).get("city", "")
            display = f"{chain} ({city})" if city else chain
            return loc_id, display
    except Exception as e:
        print(f"[Kroger] Location lookup error: {e}")
        return None


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
    headers = {"Authorization": f"Bearer {token}"}
    terms = get_all_terms(ingredient_name)

    for term in terms:
        async with semaphore:
            try:
                async with session.get(
                    f"{_BASE_URL}/products",
                    headers=headers,
                    params={
                        "filter.term": term,
                        "filter.locationId": store_id,
                        "filter.limit": 10,
                    },
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    products = data.get("data", [])
                    if products:
                        result = find_best_purchase(ingredient_name, target_qty, target_unit, products)
                        if result:
                            return ingredient_name, result
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[Kroger] Error on '{term}': {e}")
                continue

    return ingredient_name, None


async def price_all_async(
    ingredients: dict,
    lat: float,
    lon: float,
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

        store_info = await find_nearest_kroger_store(session, token, lat, lon)
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
