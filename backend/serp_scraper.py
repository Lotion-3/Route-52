"""
Bing Search API price fetcher.
Queries Bing for "[item] price at [store]" and parses prices + units
from the rich snippets in search results.

Setup:
  1. Create a free Azure account at portal.azure.com
  2. Create a "Bing Search v7" resource (free tier: 1,000 calls/month)
  3. Copy your API key to config.env as: BING_SEARCH_KEY=your_key_here

Free tier limits: 1,000 transactions/month, 3 req/sec
Results are cached for 24h so repeated app runs don't burn quota.
"""

import os
import re
import time
import requests
from typing import Dict, List, Optional
from cache_manager import cache

BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
BING_KEY = os.environ.get("BING_SEARCH_KEY")

SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
SEARCHAPI_KEY = os.environ.get("SEARCHAPI_API_KEY")

PRICE_CACHE_TTL = 60 * 60 * 24  # 24 hours

# Maps fragments of a store name (lowercase) to our canonical store names.
# Used to filter Bing results to only the store we queried.
STORE_ALIASES = {
    "walmart":      "Walmart",
    "kroger":       "Kroger",
    "aldi":         "Aldi",
    "whole foods":  "Whole Foods",
    "wholefoodsmarket": "Whole Foods",
    "trader joe":   "Trader Joe's",
    "meijer":       "Meijer",
    "costco":       "Costco",
    "target":       "Target",
    "jewel":        "Jewel Osco",
    "jewel-osco":   "Jewel Osco",
}

# Unit normalization: raw strings we might see → canonical unit label
UNIT_MAP = {
    r"/lb|per\s+lb|per\s+pound":    "per lb",
    r"/oz|per\s+oz|per\s+ounce":    "per oz",
    r"/gal|per\s+gal(?:lon)?":      "per gallon",
    r"/bunch|per\s+bunch":          "per bunch",
    r"/each|per\s+each|/ea\b|each": "each",
    r"/ct|per\s+ct|per\s+count":    "per count",
    r"/pkg|per\s+pkg|per\s+pack":   "per pack",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_prices(text: str) -> List[Dict]:
    """
    Extract all (price, unit) pairs from a text snippet.
    Returns list of {"price": float, "unit": str}.

    Handles formats like:
      $0.20    $1.71/lb    50.0 cents/lb    $3.49 per gallon
    """
    results = []

    # Dollar amounts
    for m in re.finditer(r"\$(\d+\.?\d*)", text):
        price = float(m.group(1))
        if price < 0.01 or price > 150:
            continue
        after = text[m.end(): m.end() + 50]
        unit = _extract_unit(after)
        results.append({"price": price, "unit": unit})

    # Cent amounts (e.g. "50.0 ¢/lb" or "28 cents/lb")
    for m in re.finditer(r"(\d+\.?\d*)\s*(?:¢|cents?)\s*/?\s*(lb|oz|each|ea)", text, re.IGNORECASE):
        price = round(float(m.group(1)) / 100, 4)
        unit = _normalize_unit(m.group(2))
        results.append({"price": price, "unit": unit})

    return results


def _extract_unit(text: str) -> str:
    """Pull the first unit mention out of a short text fragment."""
    for pattern in UNIT_MAP:
        if re.search(pattern, text, re.IGNORECASE):
            return UNIT_MAP[pattern]
    return ""


def _normalize_unit(raw: str) -> str:
    for pattern, canonical in UNIT_MAP.items():
        if re.search(pattern, raw, re.IGNORECASE):
            return canonical
    return raw.lower()


# ---------------------------------------------------------------------------
# Bing API call
# ---------------------------------------------------------------------------

def _bing_search(query: str) -> List[str]:
    """
    Call Bing Web Search API (or SearchAPI.io as fallback) and return a flat
    list of text snippets (titles + descriptions from the top results).
    """
    if BING_KEY:
        return _bing_search_native(query)
    if SEARCHAPI_KEY:
        return _searchapi_search(query)
    raise RuntimeError(
        "No search API key set. Add BING_SEARCH_KEY or SEARCHAPI_API_KEY to config.env."
    )


def _bing_search_native(query: str) -> List[str]:
    headers = {"Ocp-Apim-Subscription-Key": BING_KEY}
    params = {
        "q":              query,
        "mkt":            "en-US",
        "count":          10,
        "responseFilter": "Webpages",
        "safeSearch":     "Off",
    }
    resp = requests.get(BING_ENDPOINT, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    snippets = []
    for page in data.get("webPages", {}).get("value", []):
        snippets.append(page.get("name", "") + " " + page.get("snippet", ""))
    return snippets


def _searchapi_search(query: str) -> List[str]:
    params = {
        "engine":  "bing",
        "q":       query,
        "api_key": SEARCHAPI_KEY,
        "num":     10,
    }
    resp = requests.get(SEARCHAPI_ENDPOINT, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    snippets = []
    for result in data.get("organic_results", []):
        snippets.append(result.get("title", "") + " " + result.get("snippet", ""))
    return snippets


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_item_prices(item: str, target_stores: List[str]) -> Dict[str, Dict]:
    """
    Search Bing for `item` at each store and return real prices.

    Returns:
        {
            "Walmart":     {"price": 0.20, "unit": "per lb"},
            "Kroger":      {"price": 0.25, "unit": "per lb"},
            ...
        }
    Only stores where a price was found are included.
    Results are cached for 24h.
    """
    cache_key = {"bing_item": item.lower().strip(), "stores": sorted(target_stores)}
    cached = cache.get(cache_key, max_age_seconds=PRICE_CACHE_TTL)
    if cached is not None:
        return cached

    found: Dict[str, Dict] = {}

    for store in target_stores:
        query = f"{store} {item} price"
        print(f"  [Bing] {query!r}")

        try:
            snippets = _bing_search(query)
        except Exception as e:
            print(f"    Error: {e}")
            time.sleep(0.5)
            continue

        # Parse all price mentions from all snippets
        all_prices = []
        for snippet in snippets:
            # Only trust snippets that mention the store name
            if not any(alias in snippet.lower() for alias in STORE_ALIASES if STORE_ALIASES[alias] == store):
                continue
            all_prices.extend(_parse_prices(snippet))

        # Keep the lowest plausible price (most likely the base shelf price)
        if all_prices:
            best = min(all_prices, key=lambda x: x["price"])
            found[store] = best
            print(f"    -> ${best['price']:.2f} {best['unit']}")
        else:
            print(f"    -> no price found")

        time.sleep(0.35)  # stay under 3 req/sec free tier limit

    cache.set(cache_key, found)
    return found


def fetch_all_prices(
    items: List[str],
    target_stores: List[str],
) -> Dict[str, Dict[str, Dict]]:
    """
    Fetch prices for all items across all stores.

    Returns:
        {
            "chicken breast": {
                "Walmart":  {"price": 4.97, "unit": "per lb"},
                "Kroger":   {"price": 5.49, "unit": "per lb"},
            },
            "spinach": { ... },
            ...
        }

    Items with no results are omitted — data_manager.py falls back to
    Gemini synthetic pricing for those.
    """
    all_prices: Dict[str, Dict[str, Dict]] = {}

    for item in items:
        result = fetch_item_prices(item, target_stores)
        if result:
            all_prices[item] = result

    return all_prices
