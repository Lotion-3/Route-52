"""
ALDI recon v5: find fulfillment picker elements by text, then re-navigate to search.

Strategy:
  1. Hit the search URL
  2. Accept cookies
  3. Click a delivery/pickup/in-store option in the fulfillment dialog
  4. If URL changed away from search, navigate back to search URL
  5. Wait for Items GraphQL responses
"""

import json
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

QUERY = "bananas"
SEARCH_URL = f"https://www.aldi.us/store/aldi/s?query={QUERY}"

captured_items = []

def handle_response(response):
    if "graphql" not in response.url or "operationName=Items" not in response.url:
        return
    try:
        body = response.json()
        items = body.get("data", {}).get("items") or []
        captured_items.extend(items)
        print(f"  [intercept] {len(items)} items (total: {len(captured_items)})")
    except Exception:
        pass

def try_click(page, selectors, label):
    """Try each selector in order; click first visible one. Returns True if clicked."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1500):
                print(f"  [{label}] clicking: {sel!r} -> {el.inner_text()[:40].strip()!r}")
                el.click()
                time.sleep(1.5)
                return True
        except Exception:
            continue
    return False

def dump_all_clickables(page, label):
    print(f"\n--- Clickable elements ({label}) ---")
    for tag in ["button", "a[href]", "[role='button']", "[data-testid]"]:
        els = page.locator(tag)
        for i in range(min(els.count(), 8)):
            try:
                el = els.nth(i)
                if not el.is_visible():
                    continue
                text = el.inner_text()[:50].replace("\n", " ").strip()
                testid = el.get_attribute("data-testid") or ""
                href = el.get_attribute("href") or ""
                if text or testid:
                    print(f"  <{tag}> {text!r}  testid={testid!r}  href={href[:40]!r}")
            except Exception:
                pass

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        executable_path=r"C:\Users\laksh\AppData\Local\Programs\Opera\opera.exe",
        args=["--disable-blink-features=AutomationControlled"],
    )
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
    Stealth().apply_stealth_sync(page)
    page.on("response", handle_response)

    print(f"Step 1: Loading {SEARCH_URL}")
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    page.screenshot(path="aldi_s1.png")
    dump_all_clickables(page, "initial")

    # Step 2: accept cookies
    clicked = try_click(page, [
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "[id*='cookie'] button",
    ], "cookies")
    if clicked:
        time.sleep(2)
        page.screenshot(path="aldi_s2_cookies_done.png")

    # Step 3: handle fulfillment picker
    # Try text-based selectors for the three options
    fulfillment_selectors = [
        "text=Delivery",
        "text=In-Store",
        "text=Pickup",
        "[href*='fulfillment']",
        "[data-testid*='fulfillment']",
        "[class*='fulfillment']",
        "a:has-text('Delivery')",
        "a:has-text('In-Store')",
        "div[role='button']:has-text('Delivery')",
        "div[role='button']:has-text('In-Store')",
        "li:has-text('Delivery')",
        "li:has-text('In-Store')",
    ]
    dump_all_clickables(page, "before fulfillment click")
    clicked = try_click(page, fulfillment_selectors, "fulfillment")
    if clicked:
        time.sleep(3)
        page.screenshot(path="aldi_s3_fulfillment_done.png")
        print(f"  URL after fulfillment: {page.url!r}")

        # If we got redirected away from the search, go back
        if QUERY not in page.url:
            print(f"  Redirected — navigating back to search URL")
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=25000)
            time.sleep(3)
    else:
        print("  [fulfillment] No selector matched — dumping all elements for debug")
        dump_all_clickables(page, "fulfillment debug")
        page.screenshot(path="aldi_s3_debug.png")

    # Step 4: wait for search Items responses
    print(f"\nWaiting for Items GraphQL responses...")
    time.sleep(8)

    print(f"\nFinal URL: {page.url!r}")
    print(f"Total items captured: {len(captured_items)}")

    banana_items = [it for it in captured_items if "banana" in (it.get("name") or "").lower()]
    print(f"Banana-specific items: {len(banana_items)}")

    print("\nAll items captured:")
    for it in captured_items:
        name = it.get("name", "?")
        size = it.get("size", "")
        try:
            price = it["price"]["viewSection"]["priceValueString"]
        except (KeyError, TypeError):
            price = "?"
        try:
            unit = it["price"]["viewSection"]["itemDetails"]["pricePerUnitString"] or size
        except (KeyError, TypeError):
            unit = size
        print(f"  {name} ({size}) -> ${price}  {unit}")

    with open("aldi_api_responses.json", "w", encoding="utf-8") as f:
        json.dump(captured_items, f, indent=2)

    print("\nBrowser open 15s for inspection...")
    time.sleep(15)
    browser.close()
