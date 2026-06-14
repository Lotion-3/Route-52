"""
Walmart grocery pricing — scrapes walmart.com search results directly.

Walmart is not on Instacart and has uniform national pricing, so we don't
need a location-specific session. We extract product data from the Next.js
__NEXT_DATA__ blob embedded in the search page HTML.

Falls back to Playwright if the plain-requests path is blocked (Akamai).

Entry point:
    store_name, prices = price_all_walmart(ingredients)

prices format (same as kroger_async):
    {ingredient_name: {"total_cost": float, "description": str, ...}}
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WALMART_BANNERS: set[str] = {"walmart"}

_SEARCH_URL = "https://www.walmart.com/search?q={query}&affinityOverride=default&ps=40"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# Regex to extract size info from product names
_SIZE_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(fl\.?\s*oz|fluid\s*ounce|oz|ounce|lb|lbs|pound|gal|gallon|'
    r'count|ct|pk|pack|each|liter|litre|ml|g|kg)',
    re.IGNORECASE,
)

OPERA_PATH = r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe"

# ---------------------------------------------------------------------------
# Banner detection
# ---------------------------------------------------------------------------

def is_walmart_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in WALMART_BANNERS)


# ---------------------------------------------------------------------------
# Product size extraction
# ---------------------------------------------------------------------------

def _extract_size(name: str, item: dict) -> str:
    """Extract a parseable size string from product name or Walmart item fields."""
    # Try dedicated size field first
    for field in ("salesUnit", "orderType"):
        val = item.get(field) or ""
        if val and val.upper() not in ("EACH", ""):
            return val

    m = _SIZE_RE.search(name)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return "1 each"


# ---------------------------------------------------------------------------
# HTML search → item list
# ---------------------------------------------------------------------------

def _extract_items_from_html(html: str) -> list[dict]:
    """Pull the item list from Walmart's __NEXT_DATA__ JSON blob."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    # Try both current and older page prop paths
    search_result = (
        (data.get("props") or {}).get("pageProps") or {}
    ).get("initialData") or {}
    if "searchResult" not in search_result:
        search_result = ((data.get("props") or {}).get("pageProps") or {})

    stacks = (search_result.get("searchResult") or {}).get("itemStacks") or []
    items: list[dict] = []
    for stack in stacks:
        items.extend(stack.get("items") or [])
    return items


def _search_requests(query: str) -> list[dict]:
    """Plain HTTP search — works unless Walmart blocks the IP."""
    url = _SEARCH_URL.format(query=requests.utils.quote(query))
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        return _extract_items_from_html(r.text)
    except Exception:
        return []


def _search_playwright(query: str) -> list[dict]:
    """Playwright fallback for when plain requests are blocked."""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        _stealth = Stealth()
    except ImportError:
        _stealth = None

    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, executable_path=OPERA_PATH,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 768}, locale="en-US",
            user_agent=_HEADERS["User-Agent"],
        )
        page = ctx.new_page()
        if _stealth:
            _stealth.apply_stealth_sync(page)
        try:
            url = _SEARCH_URL.format(query=requests.utils.quote(query))
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)
            html = page.content()
        except Exception:
            pass
        browser.close()
    return _extract_items_from_html(html)


def _search_walmart(query: str) -> list[dict]:
    # Walmart enforces PerimeterX bot detection (CAPTCHA) for all automated requests.
    # Plain requests return 412 / redirect-to-blocked. Playwright triggers a
    # press-and-hold human CAPTCHA that cannot be solved programmatically.
    # Until a non-interactive data source is available, return empty so the
    # server falls back to synthetic prices for Walmart stores.
    return _search_requests(query)


# ---------------------------------------------------------------------------
# Item → Kroger format conversion
# ---------------------------------------------------------------------------

def _item_to_kroger_format(item: dict) -> Optional[dict]:
    """Convert a Walmart search result item to find_best_purchase() input format."""
    name = item.get("name") or ""

    # Price: try several nested paths Walmart has used over time
    price: Optional[float] = None
    price_info = item.get("priceInfo") or {}
    current_price = price_info.get("currentPrice") or {}
    price = current_price.get("price")
    if not price:
        price = (item.get("price") or {}).get("currentPrice")
    if not price:
        # Some items embed price directly
        price = item.get("salePrice") or item.get("regularPrice")
    if not price:
        return None
    try:
        price = float(price)
        if not (0.01 <= price <= 500):
            return None
    except Exception:
        return None

    size_str = _extract_size(name, item)

    return {
        "description": name,
        "brand": item.get("brand") or "",
        "items": [{
            "itemId": str(item.get("usItemId") or item.get("id") or ""),
            "soldBy": "UNIT",
            "size": size_str,
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Per-ingredient pricing
# ---------------------------------------------------------------------------

def _price_one(ingredient: str, qty: float, unit: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        raw_items = _search_walmart(term)
        if not raw_items:
            continue
        products = [p for p in (_item_to_kroger_format(i) for i in raw_items) if p]
        if not products:
            continue
        # Keyword pre-filter: at least one query word must appear in product name
        query_words = set(term.lower().split())
        matched = [
            p for p in products
            if any(qw in p["description"].lower() for qw in query_words)
        ]
        products = matched or products  # fall back to unfiltered if all rejected
        result = find_best_purchase(ingredient, qty, unit, products)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_walmart(
    ingredients: dict,
    max_workers: int = 6,
) -> tuple[str, dict]:
    """
    Price all ingredients at Walmart (national prices).

    Parameters
    ----------
    ingredients : {name: {"qty": float, "unit": str, ...}}
    max_workers : parallel threads (keep low to avoid rate limiting)

    Returns
    -------
    (store_display_name, prices)
        prices: {ingredient_name: find_best_purchase() result dict}
    """
    print("[Walmart] Pricing ingredients via walmart.com ...", flush=True)

    prices: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _price_one,
                name,
                float(data.get("qty", 1)),
                str(data.get("unit", "whole")),
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
                print(f"[Walmart] Error pricing '{name}': {e}", flush=True)

    print(f"[Walmart] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "Walmart", prices


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST = {
        "Large eggs":           {"qty": 12, "unit": "whole"},
        "Whole milk":           {"qty": 1,  "unit": "gal"},
        "Bananas":              {"qty": 5,  "unit": "whole"},
        "Boneless skinless chicken breast": {"qty": 2, "unit": "lb"},
        "Ground beef 80/20":    {"qty": 1,  "unit": "lb"},
        "Russet potatoes":      {"qty": 3,  "unit": "lb"},
        "Canned black beans":   {"qty": 2,  "unit": "can"},
        "Shredded cheddar":     {"qty": 8,  "unit": "oz"},
    }
    print("Testing Walmart pricing pipeline...")
    print("=" * 60)
    store, prices = price_all_walmart(TEST, max_workers=4)
    print(f"\nStore: {store}")
    print("-" * 60)
    total = 0.0
    for ing, r in sorted(prices.items()):
        cost = r.get("total_cost", 0)
        total += cost
        print(f"  {ing:<40} ${cost:.2f}  ({r.get('description','')[:40]})")
    print(f"\n  TOTAL: ${total:.2f}  ({len(prices)}/{len(TEST)} priced)")
    if len(prices) < len(TEST):
        print(f"  Missing: {', '.join(k for k in TEST if k not in prices)}")
