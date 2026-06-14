"""
Playwright-based grocery price scraper.
Searches Google for "price of {item} at {store}" and extracts the
rich shopping snippet that Google shows at the top of results.

Test items: bananas, oranges, watermelon, milk
Run with: python test_price_scraper.py
"""

import re
import time
import random
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

STORES = ["Walmart", "Kroger", "Aldi", "Whole Foods", "Target"]

ITEMS = {
    "bananas":    "price of bananas at",
    "oranges":    "price of oranges at",
    "watermelon": "price of watermelon at",
    "milk":       "price of whole milk gallon at",
}


def parse_price(text: str):
    """Extract all (price, unit) pairs from a block of text."""
    results = []
    # Match patterns: $0.20, $1.71 followed by optional unit context
    for m in re.finditer(r"\$(\d+\.?\d*)", text):
        price = float(m.group(1))
        if price < 0.01 or price > 200:
            continue
        # Grab text after the price to find a unit
        after = text[m.end():m.end() + 60]
        unit = ""
        unit_match = re.search(
            r"([\d.]+\s*[¢$]?\s*[-/]\s*(?:lb|oz|gal(?:lon)?|each|ea|bunch|ct|count|fl oz))",
            after, re.IGNORECASE
        )
        if unit_match:
            unit = unit_match.group(1).strip()
        results.append({"price": price, "unit": unit})
    return results


def scrape_google_rich_snippet(page, query: str) -> str:
    """Navigate to Google search and return the text of the top rich result block."""
    page.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us")

    # Wait for results to load
    page.wait_for_load_state("domcontentloaded")
    time.sleep(random.uniform(1.5, 2.5))

    # Dismiss any consent/cookie popups (EU users)
    try:
        btn = page.locator("button:has-text('Accept all'), button:has-text('I agree')")
        if btn.count() > 0:
            btn.first.click()
            time.sleep(1)
    except Exception:
        pass

    # The rich snippet for shopping/products sits in various containers.
    # Try selectors from most to least specific.
    selectors = [
        # Product carousel / rich result
        "[data-attrid='kc:/shopping/gpc:cluster_items']",
        # Inline shopping results block
        ".sh-np__click-target",
        # Knowledge panel with price list
        "[data-attrid*='price']",
        # Featured snippet
        ".xpdopen .ifM9O",
        # Generic rich result container
        ".g .kp-blk",
        # Top result description block
        ".V3FYCf",
        # Any block mentioning $ near the top results
        "#search .g:first-child",
        # Broad fallback — first organic result snippet
        "#rso > div:first-child",
    ]

    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                text = el.inner_text(timeout=2000)
                if "$" in text:
                    return text
        except PWTimeout:
            continue
        except Exception:
            continue

    # Last resort: grab all text from the search results area and filter for $ lines
    try:
        full = page.locator("#search").inner_text(timeout=3000)
        # Return only lines containing a price
        lines = [l for l in full.splitlines() if "$" in l and re.search(r"\$\d", l)]
        return "\n".join(lines[:20])
    except Exception:
        return ""


def search_store_item(page, store: str, item_display: str, query_prefix: str):
    query = f"{query_prefix} {store}"
    print(f"  Searching: {query!r}")
    try:
        snippet = scrape_google_rich_snippet(page, query)
    except Exception as e:
        print(f"    Error: {e}")
        return []

    if not snippet:
        print(f"    No snippet found")
        return []

    hits = parse_price(snippet)
    hits = [h for h in hits if 0.05 < h["price"] < 100]

    if not hits:
        # Show raw snippet to help debug
        preview = snippet[:200].replace("\n", " | ")
        print(f"    No prices parsed. Snippet: {preview}")
    return hits


def main():
    print("=" * 65)
    print("Playwright Google Price Scraper Test")
    print("=" * 65)

    all_results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            # Mimic a real browser viewport and locale
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for item_display, query_prefix in ITEMS.items():
            print(f"\n{'-'*65}")
            print(f"ITEM: {item_display.upper()}")
            print(f"{'-'*65}")
            all_results[item_display] = {}

            for store in STORES:
                hits = search_store_item(page, store, item_display, query_prefix)
                if hits:
                    all_results[item_display][store] = hits
                    for h in hits[:3]:
                        unit_str = f"  [{h['unit']}]" if h["unit"] else ""
                        print(f"    {store:<14} ${h['price']:.2f}{unit_str}")
                else:
                    print(f"    {store:<14} no prices found")

                time.sleep(random.uniform(2.0, 3.5))

        browser.close()

    # Summary table
    print(f"\n{'='*65}")
    print("PRICE COMPARISON SUMMARY (lowest price found per store)")
    print(f"{'='*65}")
    header = f"{'Item':<16}" + "".join(f"{s:<16}" for s in STORES)
    print(header)
    print("-" * len(header))
    for item, stores in all_results.items():
        row = f"{item:<16}"
        for store in STORES:
            if store in stores and stores[store]:
                best = min(stores[store], key=lambda x: x["price"])
                unit = f"/{best['unit']}" if best["unit"] else ""
                row += f"${best['price']:.2f}{unit:<10}"
            else:
                row += f"{'N/A':<16}"
        print(row)

    print("\nUnits observed:")
    for item, stores in all_results.items():
        for store, hits in stores.items():
            for h in hits[:1]:
                if h["unit"]:
                    print(f"  {item} @ {store}: {h['unit']}")


if __name__ == "__main__":
    main()
