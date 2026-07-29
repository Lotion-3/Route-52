"""
Standalone script: scrape walmart.com for avocado prices in zipcode 46032
using CloakBrowser (stealth Chromium that bypasses PerimeterX bot detection).

Usage:
    pip install cloakbrowser
    python walmart_cloak_scraper.py
"""

import json
import re
import time

from cloakbrowser import launch

ZIP_CODE = "90034"
SEARCH_TERM = "Great value vanilla ice cream"
SEARCH_URL = f"https://www.walmart.com/search?q={SEARCH_TERM.replace(' ', '+')}&ps=40"


def _extract_items_from_html(html: str) -> list[dict]:
    """Pull item list from Walmart's __NEXT_DATA__ JSON blob."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

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


def _parse_price(item: dict) -> float | None:
    """Extract price from a Walmart search result item."""
    price = None

    # Path 1: priceInfo.currentPrice.price (most common)
    price_info = item.get("priceInfo") or {}
    current_price = price_info.get("currentPrice") or {}
    if isinstance(current_price, dict):
        price = current_price.get("price")
    elif isinstance(current_price, (int, float)):
        price = current_price

    # Path 2: item.price may be a float directly or a dict
    if not price:
        raw_price = item.get("price")
        if isinstance(raw_price, dict):
            price = raw_price.get("currentPrice") or raw_price.get("price")
        elif isinstance(raw_price, (int, float)):
            price = raw_price

    # Path 3: salePrice / regularPrice as top-level fields
    if not price:
        price = item.get("salePrice") or item.get("regularPrice")

    if not price:
        return None
    try:
        price = float(price)
        if 0.01 <= price <= 500:
            return price
    except (ValueError, TypeError):
        pass
    return None


def set_location(page, zip_code: str) -> bool:
    """Attempt to set Walmart store location to the given ZIP code."""
    # Strategy 1: Navigate to store finder with the ZIP to warm the session
    try:
        page.goto(
            f"https://www.walmart.com/store/finder?location={zip_code}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(3)
        print(f"  [location] Visited store finder for ZIP {zip_code}")
    except Exception as e:
        print(f"  [location] Store finder visit failed: {e}")
        return False

    # Strategy 2: Try setting the delivery ZIP via localStorage / cookie
    try:
        page.evaluate(f"""
            localStorage.setItem('postal-code', '{zip_code}');
            document.cookie = 'deliveryZip={zip_code}; path=/; max-age=86400';
            document.cookie = 'walmart.location={zip_code}; path=/; max-age=86400';
        """)
        print(f"  [location] Set ZIP {zip_code} via localStorage/cookies")
    except Exception as e:
        print(f"  [location] Could not set cookies: {e}")

    return True


def _extract_aisle_from_product_page(page) -> str | None:
    """Extract aisle/location info from a Walmart product page."""
    html = page.content()

    # Method 1: Check __NEXT_DATA__ blob for productLocation list
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            props = (data.get("props") or {}).get("pageProps") or {}
            # productLocation can be a list like [{"displayValue":"A3"}]
            for key in ("product", "initialData", "productData"):
                product = props.get(key) or {}
                if isinstance(product, dict):
                    pl = product.get("productLocation")
                    if isinstance(pl, list) and pl:
                        dv = pl[0].get("displayValue")
                        if dv:
                            return f"Aisle {dv}"
                    if isinstance(pl, str):
                        return pl
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass

    # Method 2: data-testid="product-aisle-location" element via JS
    try:
        aisle_text = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="product-aisle-location"]');
            if (el) return el.textContent.trim();
            return null;
        }""")
        if aisle_text:
            return aisle_text.strip()
    except Exception:
        pass

    # Method 3: HTML regex for "Aisle A1", "Aisle 3", etc.
    m = re.search(r'Aisle\s+([A-Za-z0-9]+)', html)
    if m:
        return f"Aisle {m.group(1)}"

    return None


def _save_cookies(page, filepath=".walmart_cookies.json"):
    """Extract all cookies from the browser context and save them to disk + print."""
    cookies = page.context.cookies()
    print("\n  [cookies] =============================================")
    print(f"  [cookies] Total: {len(cookies)} cookies")
    for c in cookies:
        print(f"  [cookies]   {c['name']:30s} = {c['value'][:60]}")
    print(f"  [cookies] =============================================")

    cookie_jar = {c["name"]: c["value"] for c in cookies}
    try:
        import pathlib
        pathlib.Path(filepath).write_text(json.dumps(cookie_jar, indent=2))
        print(f"  [cookies] Saved to {filepath}")
    except Exception as e:
        print(f"  [cookies] Failed to save: {e}")

    return cookie_jar


def main():
    print(f"CloakBrowser Walmart scraper")
    print(f"  ZIP: {ZIP_CODE} | Search: '{SEARCH_TERM}'")
    print("=" * 60)

    # Launch stealth browser — headed mode avoids PerimeterX headless detection,
    # humanize=True adds realistic mouse/keyboard behavior
    browser = launch(
        headless=False,
        humanize=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--fingerprint=42069",  # Fixed seed for consistent identity
        ],
    )
    print("[browser] CloakBrowser launched (headed + humanize)")

    page = browser.new_page()

    try:
        # Step 1: Set location
        print("\n[1/3] Setting location to ZIP {}...".format(ZIP_CODE))
        set_location(page, ZIP_CODE)

        # Save cookies after location set
        _save_cookies(page, ".walmart_cookies.json")

        # Step 2: Search
        print(f"\n[2/3] Searching for '{SEARCH_TERM}'...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)  # Let the page fully render (PerimeterX checks, etc.)

        # Save cookies after search (PerimeterX _px3 should be set now)
        _save_cookies(page, ".walmart_cookies.json")

        html = page.content()
        items = _extract_items_from_html(html)

        if not items:
            print("  No items extracted from __NEXT_DATA__. Trying fallback...")
            # Fallback: scroll to trigger lazy loading, wait, retry
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(2)
            html = page.content()
            items = _extract_items_from_html(html)

        # Step 3: Find cheapest from top 5 results
        print(f"\n[3/3] {len(items)} raw items found — scanning top 5 for cheapest...\n")

        priced = []
        for item in items[:5]:
            name = (item.get("name") or "Unknown").strip()
            price = _parse_price(item)
            if price is not None:
                priced.append({"name": name, "price": price, "raw": item})

        if not priced:
            print("  No priced items found among top 5 results.")
        else:
            cheapest = min(priced, key=lambda x: x["price"])
            name = cheapest["name"]
            price = cheapest["price"]
            raw = cheapest["raw"]
            print(f"  Cheapest: {name}")
            print(f"  Price:    ${price:.2f}")

            # Step 4: Navigate to product page to get aisle
            canonical = raw.get("canonicalUrl", "")
            if canonical:
                product_url = f"https://www.walmart.com{canonical.split('?')[0]}"
                print(f"\n[4/4] Navigating to product page...")
                page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)

                aisle = _extract_aisle_from_product_page(page)
                if aisle:
                    print(f"\n  Aisle:  {aisle}")
                else:
                    print(f"\n  Aisle:  Not found on product page")
            else:
                print("  No product URL available")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\nClosing browser...")
        browser.close()
        print("Done.")


if __name__ == "__main__":
    main()