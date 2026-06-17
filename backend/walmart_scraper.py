"""
Walmart price scraper using Playwright + __NEXT_DATA__ JSON extraction.

Walmart's Next.js site embeds all search results (prices, units, product names)
in a <script id="__NEXT_DATA__"> tag on every search page. We extract that
directly — no brittle CSS selectors, no SERP API costs.

Results are cached for 24h to minimize requests.

Usage:
    from walmart_scraper import fetch_walmart_prices
    prices = fetch_walmart_prices(["bananas", "whole milk", "chicken breast"])
    # {"bananas": {"price": 0.23, "unit": "each", "name": "Fresh Bananas"}, ...}
"""

import json
import re
import time
import random
from typing import Dict, Optional
from urllib.parse import quote_plus
from cloakbrowser import launch
from cache_manager import cache

PRICE_CACHE_TTL = 60 * 60 * 24  # 24 hours
WALMART_SEARCH_URL = "https://www.walmart.com/search?q={query}"


# ---------------------------------------------------------------------------
# Price extraction from __NEXT_DATA__
# ---------------------------------------------------------------------------

def _extract_best_price(next_data: dict, item_query: str) -> Optional[Dict]:
    """
    Walk the __NEXT_DATA__ JSON tree to find product prices.
    Returns {"price": float, "unit": str, "name": str} for the best match.
    """
    try:
        stacks = (
            next_data["props"]["pageProps"]["initialData"]
            ["searchResult"]["itemStacks"]
        )
    except (KeyError, TypeError):
        return None

    candidates = []
    query_words = set(item_query.lower().split())

    for stack in stacks:
        for item in stack.get("items", []):
            name = item.get("name", "") or ""
            price_info = item.get("priceInfo", {}) or {}
            current = price_info.get("currentPrice", {}) or {}
            price = current.get("price")

            if not price or not isinstance(price, (int, float)):
                continue
            if price < 0.01 or price > 200:
                continue

            # Prefer items whose name contains query words
            name_lower = name.lower()
            relevance = sum(1 for w in query_words if w in name_lower)

            # Unit price (e.g. "$0.23/oz")
            unit_price_info = price_info.get("unitPrice", {}) or {}
            unit = unit_price_info.get("unitPriceDisplayValue", "")
            if not unit:
                # Fall back to price display codes for unit info
                codes = price_info.get("priceDisplayCodes", {}) or {}
                unit = codes.get("priceDisplayCondition", "")

            candidates.append({
                "price": float(price),
                "unit": unit or "each",
                "name": name,
                "relevance": relevance,
            })

    if not candidates:
        return None

    # Pick the most relevant item; break ties by lowest price
    best = max(candidates, key=lambda x: (x["relevance"], -x["price"]))
    return {"price": best["price"], "unit": best["unit"], "name": best["name"]}


# ---------------------------------------------------------------------------
# Playwright page loader
# ---------------------------------------------------------------------------

def _load_walmart_next_data(page, query: str) -> Optional[dict]:
    """Load a Walmart search page and extract __NEXT_DATA__ JSON."""
    url = WALMART_SEARCH_URL.format(query=quote_plus(query))

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        print(f"    [Walmart] Timeout loading page for {query!r}")
        return None

    # Random delay to appear human
    time.sleep(random.uniform(2.0, 4.0))

    # Extract __NEXT_DATA__ from the page
    try:
        raw = page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }
        """)
    except Exception as e:
        print(f"    [Walmart] JS eval error: {e}")
        return None

    if not raw:
        # Check if we hit a bot challenge page
        title = page.title()
        print(f"    [Walmart] No __NEXT_DATA__ found. Page title: {title!r}")
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"    [Walmart] JSON parse error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_walmart_prices(items: list[str]) -> Dict[str, Dict]:
    """
    Fetch Walmart prices for a list of grocery items.

    Returns:
        {
            "bananas":       {"price": 0.23, "unit": "each",  "name": "Fresh Bananas, Each"},
            "whole milk":    {"price": 3.48, "unit": "each",  "name": "Great Value Whole Milk, 1 Gallon"},
            "chicken breast":{"price": 6.97, "unit": "per lb","name": "..."},
        }
    Items with no price found are omitted.
    Results are cached for 24h.
    """
    # Check cache first — avoid Playwright entirely if everything is cached
    results = {}
    items_to_fetch = []
    for item in items:
        cache_key = {"walmart_item": item.lower().strip()}
        cached = cache.get(cache_key, max_age_seconds=PRICE_CACHE_TTL)
        if cached is not None:
            results[item] = cached
            print(f"  [Walmart] {item!r} -> cached ${cached['price']:.2f}")
        else:
            items_to_fetch.append(item)

    if not items_to_fetch:
        return results

    browser = launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

        for item in items_to_fetch:
            print(f"  [Walmart] Searching {item!r}...")
            next_data = _load_walmart_next_data(page, item)

            if next_data is None:
                print(f"    -> failed to load page")
                continue

            price_data = _extract_best_price(next_data, item)
            if price_data:
                results[item] = price_data
                cache_key = {"walmart_item": item.lower().strip()}
                cache.set(cache_key, price_data)
                print(f"    -> ${price_data['price']:.2f} [{price_data['unit']}] — {price_data['name'][:50]}")
            else:
                print(f"    -> no price found in __NEXT_DATA__")

            # Polite delay between requests
            time.sleep(random.uniform(3.0, 6.0))

        browser.close()

    return results


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    TEST_ITEMS = ["bananas", "whole milk gallon", "chicken breast", "spinach", "eggs dozen"]
    print("Testing Walmart scraper...")
    print("=" * 60)
    prices = fetch_walmart_prices(TEST_ITEMS)
    print("\nResults:")
    for item, data in prices.items():
        print(f"  {item:<20} ${data['price']:.2f}  [{data['unit']}]  {data['name'][:40]}")
    missing = [i for i in TEST_ITEMS if i not in prices]
    if missing:
        print(f"\nNo price found for: {missing}")
