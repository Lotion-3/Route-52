"""
Debug: try real Chrome channel + Bing to bypass Google's bot detection.
Saves screenshot and dumps price lines.
"""
import time
import os
from playwright.sync_api import sync_playwright

QUERY = "walmart banana price"


def run_search(p, engine: str, use_real_chrome: bool):
    launch_kwargs = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if use_real_chrome:
        launch_kwargs["channel"] = "chrome"

    try:
        browser = p.chromium.launch(**launch_kwargs)
    except Exception as e:
        print(f"  Launch failed ({engine}): {e}")
        return

    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    if engine == "google":
        url = f"https://www.google.com/search?q={QUERY.replace(' ', '+')}&hl=en&gl=us"
    elif engine == "bing":
        url = f"https://www.bing.com/search?q={QUERY.replace(' ', '+')}"
    elif engine == "ddg":
        url = f"https://duckduckgo.com/?q={QUERY.replace(' ', '+')}&kl=us-en"

    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(2.5)

    label = f"{engine}_{'chrome' if use_real_chrome else 'chromium'}"
    page.screenshot(path=f"debug_{label}.png", full_page=False)

    full_text = page.locator("body").inner_text()
    price_lines = [l.strip() for l in full_text.splitlines() if "$" in l and l.strip()]

    print(f"\n[{label.upper()}] URL: {page.url[:80]}")
    print(f"  Price lines found: {len(price_lines)}")
    for l in price_lines[:15]:
        print(f"    {l[:100]}")
    if not price_lines:
        # Show first 500 chars of body to see what we got
        preview = full_text[:500].replace("\n", " | ")
        print(f"  Body preview: {preview}")

    browser.close()


with sync_playwright() as p:
    print("=" * 60)
    print(f"Query: {QUERY!r}")
    print("=" * 60)

    # 1. Bing with bundled Chromium (fastest, no Chrome needed)
    print("\n--- Bing + Chromium ---")
    run_search(p, "bing", use_real_chrome=False)

    # 2. DuckDuckGo with bundled Chromium
    print("\n--- DuckDuckGo + Chromium ---")
    run_search(p, "ddg", use_real_chrome=False)

    # 3. Google with real Chrome (if installed)
    print("\n--- Google + Real Chrome ---")
    run_search(p, "google", use_real_chrome=True)
