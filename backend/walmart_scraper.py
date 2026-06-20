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

def _coerce_price(value) -> Optional[float]:
    """Turn a Walmart price (float, int, or '$3.16' string) into a sane float."""
    if isinstance(value, (int, float)):
        price = float(value)
    elif isinstance(value, str):
        m = re.search(r"\d+\.?\d*", value)
        if not m:
            return None
        price = float(m.group())
    else:
        return None
    return price if 0.01 <= price <= 200 else None


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
            if not name:
                continue
            price_info = item.get("priceInfo", {}) or {}

            # Walmart dropped priceInfo.currentPrice. The live price is now
            # item.price (float), with priceInfo.linePrice/itemPrice ("$3.16")
            # as string fallbacks.
            price = (
                _coerce_price(item.get("price"))
                or _coerce_price(price_info.get("linePrice"))
                or _coerce_price(price_info.get("itemPrice"))
            )
            if price is None:
                continue

            # Prefer items whose name contains query words
            name_lower = name.lower()
            relevance = sum(1 for w in query_words if w in name_lower)

            # Unit price (e.g. "$0.23/oz")
            unit_info = price_info.get("unitPrice")
            if isinstance(unit_info, dict):
                unit = unit_info.get("unitPriceDisplayValue") or unit_info.get("priceString") or ""
            elif isinstance(unit_info, str):
                unit = unit_info
            else:
                unit = ""

            candidates.append({
                "price": price,
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

# Asset types we never need — the prices live in the HTML's __NEXT_DATA__ blob,
# so blocking these roughly halves page-load time. We deliberately KEEP
# script/xhr/fetch so PerimeterX's sensor still runs (blocking it is a bot tell).
_BLOCK_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


def _install_resource_blocking(context) -> None:
    """Abort heavy assets we don't parse, to speed up every page load."""
    def _route(route):
        if route.request.resource_type in _BLOCK_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()
    context.route("**/*", _route)


def _set_location(page, zip_code: str) -> None:
    """
    Pin Walmart to a store near `zip_code` so search prices are the regional
    pickup/delivery prices for that store, not Walmart's IP-default pricing.
    """
    try:
        page.goto(
            f"https://www.walmart.com/store/finder?location={zip_code}",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        # localStorage is origin-scoped, so it can only be set once we're on
        # walmart.com (which the goto above guarantees).
        page.evaluate(
            f"""() => {{
                try {{ localStorage.setItem('postal-code', '{zip_code}'); }} catch (e) {{}}
                document.cookie = 'deliveryZip={zip_code}; path=/; max-age=86400';
                document.cookie = 'walmart.location={zip_code}; path=/; max-age=86400';
            }}"""
        )
        print(f"  [Walmart] Location pinned to ZIP {zip_code}")
    except Exception as e:
        print(f"  [Walmart] Could not set location ({zip_code}): {e}")


def _read_next_data(page) -> Optional[str]:
    """Read the raw text of the __NEXT_DATA__ script tag, or None if absent."""
    try:
        return page.evaluate(
            "() => { const el = document.getElementById('__NEXT_DATA__');"
            " return el ? el.textContent : null; }"
        )
    except Exception as e:
        print(f"    [Walmart] JS eval error: {e}")
        return None


def _load_walmart_next_data(page, query: str) -> Optional[dict]:
    """Load a Walmart search page and extract __NEXT_DATA__ JSON."""
    url = WALMART_SEARCH_URL.format(query=quote_plus(query))

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        print(f"    [Walmart] Timeout loading page for {query!r}")
        return None

    # __NEXT_DATA__ is server-rendered into the initial HTML, so it's normally
    # present the instant domcontentloaded fires — no blind sleep needed.
    raw = _read_next_data(page)
    if not raw:
        # Absent => still hydrating or a bot-challenge page. Give it one short,
        # bounded wait and retry rather than a fixed sleep on the happy path.
        try:
            page.wait_for_selector("#__NEXT_DATA__", timeout=4000)
            raw = _read_next_data(page)
        except Exception:
            pass

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

def fetch_walmart_prices(items: list[str], zip_code: Optional[str] = None) -> Dict[str, Dict]:
    """
    Fetch Walmart prices for a list of grocery items.

    If `zip_code` is given, the browser is pinned to a store near that ZIP so
    prices are the regional pickup/delivery prices rather than Walmart's
    IP-default. Cached results are keyed by ZIP so regions don't collide.

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
        cache_key = {"walmart_item": item.lower().strip(), "zip": zip_code}
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
    _install_resource_blocking(context)
    page = context.new_page()

    # Pin the store once so every query below returns regional prices.
    if zip_code:
        _set_location(page, zip_code)

    try:
        for idx, item in enumerate(items_to_fetch):
            print(f"  [Walmart] Searching {item!r}...")
            next_data = _load_walmart_next_data(page, item)

            if next_data is None:
                print(f"    -> failed to load page")
                continue

            price_data = _extract_best_price(next_data, item)
            if price_data:
                results[item] = price_data
                cache_key = {"walmart_item": item.lower().strip(), "zip": zip_code}
                cache.set(cache_key, price_data)
                print(f"    -> ${price_data['price']:.2f} [{price_data['unit']}] — {price_data['name'][:50]}")
            else:
                print(f"    -> no price found in __NEXT_DATA__")

            # Light polite delay between requests; skip it after the last item.
            if idx < len(items_to_fetch) - 1:
                time.sleep(random.uniform(1.0, 2.0))
    finally:
        browser.close()

    return results


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    TEST_ITEMS = ["bananas", "whole milk gallon", "chicken breast", "spinach", "eggs dozen"]
    TEST_ZIP = sys.argv[1] if len(sys.argv) > 1 else "46032"  # Indianapolis area
    print(f"Testing Walmart scraper (ZIP {TEST_ZIP})...")
    print("=" * 60)
    prices = fetch_walmart_prices(TEST_ITEMS, zip_code=TEST_ZIP)
    print("\nResults:")
    for item, data in prices.items():
        print(f"  {item:<20} ${data['price']:.2f}  [{data['unit']}]  {data['name'][:40]}")
    missing = [i for i in TEST_ITEMS if i not in prices]
    if missing:
        print(f"\nNo price found for: {missing}")
