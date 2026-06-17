"""
ALDI price scraper using Playwright + GraphQL interception.

ALDI's site runs on Instacart's platform. Products are delivered via GraphQL
'Items' operations after React renders. We intercept those responses directly.

Flow per search:
  1. Navigate to search URL
  2. Accept cookie banner
  3. Click Delivery fulfillment option (sets store context)
  4. Collect all Items GraphQL responses
  5. Score items by relevance to query, return best match

Results are cached for 24h.

Usage:
    from aldi_scraper import fetch_aldi_prices
    prices = fetch_aldi_prices(["bananas", "whole milk", "chicken breast"])
    # {"whole milk": {"price": 3.15, "unit": "$0.02/fl oz", "name": "Friendly Farms Whole Milk"}, ...}
"""

import re
import time
import random
from typing import Dict, List, Optional
from cloakbrowser import launch
from cache_manager import cache

PRICE_CACHE_TTL = 60 * 60 * 24  # 24 hours
ALDI_SEARCH_URL = "https://www.aldi.us/store/aldi/s?query={query}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_price(price_str: Optional[str]) -> Optional[float]:
    if not price_str:
        return None
    try:
        val = float(re.sub(r"[^\d.]", "", str(price_str)))
        return val if 0.01 <= val <= 300 else None
    except (ValueError, TypeError):
        return None


def _try_click(page, selectors: List[str], label: str) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(1.5)
                print(f"    [{label}] clicked {sel!r}")
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# GraphQL Items extraction
# ---------------------------------------------------------------------------

def _extract_best_match(items: List[Dict], query: str) -> Optional[Dict]:
    query_words = set(query.lower().split())
    candidates = []

    for item in items:
        name = item.get("name") or ""
        size = item.get("size") or ""
        price_section = (item.get("price") or {}).get("viewSection") or {}

        price = _parse_price(price_section.get("priceValueString"))
        if price is None:
            continue

        unit = ""
        try:
            unit = price_section["itemDetails"]["pricePerUnitString"] or ""
        except (KeyError, TypeError):
            pass
        if not unit:
            unit = size or "each"

        relevance = sum(1 for w in query_words if w in name.lower())
        candidates.append({"price": price, "unit": unit, "name": name, "relevance": relevance})

    if not candidates:
        return None

    best = max(candidates, key=lambda x: (x["relevance"], -x["price"]))
    if best["relevance"] == 0:
        return None  # nothing matched the query at all

    return {"price": best["price"], "unit": best["unit"], "name": best["name"]}


# ---------------------------------------------------------------------------
# Page loader
# ---------------------------------------------------------------------------

def _load_aldi_items(page, query: str) -> List[Dict]:
    captured: List[Dict] = []

    def on_response(response):
        if "graphql" not in response.url or "operationName=Items" not in response.url:
            return
        try:
            body = response.json()
            items = body.get("data", {}).get("items") or []
            captured.extend(items)
        except Exception:
            pass

    page.on("response", on_response)

    url = ALDI_SEARCH_URL.format(query=query.replace(" ", "+"))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        print(f"    [ALDI] Timeout loading {query!r}")
        page.remove_listener("response", on_response)
        return captured

    time.sleep(3)

    # Accept cookie banner (only fires on first load)
    _try_click(page, [
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
    ], "cookies")

    # Set delivery fulfillment mode (unlocks store-specific pricing)
    _try_click(page, ["text=Delivery"], "fulfillment")

    # Wait for all Items batches to arrive
    time.sleep(random.uniform(7.0, 9.0))

    page.remove_listener("response", on_response)
    return captured


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_aldi_prices(items: list) -> Dict[str, Dict]:
    """
    Fetch ALDI prices for a list of grocery items.

    Returns dict mapping item name -> {"price": float, "unit": str, "name": str}.
    Items with no match are omitted. Results cached 24h.
    """
    results = {}
    to_fetch = []

    for item in items:
        cache_key = {"aldi_item": item.lower().strip()}
        cached = cache.get(cache_key, max_age_seconds=PRICE_CACHE_TTL)
        if cached is not None:
            results[item] = cached
            print(f"  [ALDI] {item!r} -> cached ${cached['price']:.2f}")
        else:
            to_fetch.append(item)

    if not to_fetch:
        return results

    browser = launch(headless=False)
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

        for item in to_fetch:
            print(f"  [ALDI] Searching {item!r}...")
            all_items = _load_aldi_items(page, item)
            print(f"    -> {len(all_items)} items captured")

            if not all_items:
                print(f"    -> no GraphQL responses captured")
                continue

            price_data = _extract_best_match(all_items, item)
            if price_data:
                results[item] = price_data
                cache.set({"aldi_item": item.lower().strip()}, price_data)
                print(f"    -> ${price_data['price']:.2f} [{price_data['unit']}] — {price_data['name'][:50]}")
            else:
                print(f"    -> no relevant match found")

            time.sleep(random.uniform(2.0, 4.0))

        browser.close()

    return results


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    TEST_ITEMS = ["bananas", "whole milk", "chicken breast", "spinach", "eggs"]
    print("Testing ALDI scraper...")
    print("=" * 60)
    prices = fetch_aldi_prices(TEST_ITEMS)
    print("\nResults:")
    for item, data in prices.items():
        print(f"  {item:<20} ${data['price']:.2f}  [{data['unit']}]  {data['name'][:40]}")
    missing = [i for i in TEST_ITEMS if i not in prices]
    if missing:
        print(f"\nNo match found for: {missing}")
