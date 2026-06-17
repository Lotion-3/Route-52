"""
Costco probe — run this before building costco_pricing.py.

Checks:
  1. Can CloakBrowser load costco.com without DataDome challenge?
  2. What does the search page HTML / __NEXT_DATA__ look like?
  3. What XHR/fetch calls does a search trigger? (intercept them)
  4. Is there a clean JSON product+price API we can hit directly?
  5. What does the price field structure look like?

Run:  python probe_costco.py
"""
import json
import time

SEARCH_TERM = "milk"
SEARCH_URL = f"https://www.costco.com/CatalogSearch?keyword={SEARCH_TERM}&pageSize=24"
HOME_URL = "https://www.costco.com/"

intercepted: list[dict] = []


def probe():
    from cloakbrowser import launch
    print("[probe] Launching CloakBrowser (headless) ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    # Intercept all XHR/fetch responses to find the product/price API
    def on_response(resp):
        url = resp.url
        if any(kw in url for kw in ("search", "product", "catalog", "price", "item", "graphql")):
            try:
                body = resp.text()
                intercepted.append({"url": url, "status": resp.status,
                                    "content_type": resp.headers.get("content-type", ""),
                                    "body_preview": body[:400]})
            except Exception:
                pass

    page = ctx.new_page()
    page.on("response", on_response)

    # 1. Warm homepage — use networkidle and guard title() against mid-nav context loss
    print(f"[probe] Loading {HOME_URL} ...")
    try:
        page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"[probe] Homepage goto raised (may be a redirect): {e!r}")
    time.sleep(4)
    try:
        title = page.title()
    except Exception:
        title = "(context lost — redirected)"
    try:
        body_preview = page.content()[:500]
    except Exception:
        body_preview = ""
    print(f"[probe] Homepage title: {title!r}")
    print(f"[probe] Current URL: {page.url}")
    datadome = "datadome" in body_preview.lower() or "dd_" in body_preview.lower()
    print(f"[probe] DataDome detected on homepage: {datadome}")

    # 2. Load search page
    print(f"\n[probe] Loading search: {SEARCH_URL} ...")
    try:
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"[probe] Search goto raised: {e!r}")
    time.sleep(4)
    try:
        search_title = page.title()
    except Exception:
        search_title = "(context lost)"
    try:
        search_body = page.content()
    except Exception:
        search_body = ""
    print(f"[probe] Search title: {search_title!r}")
    datadome_search = "datadome" in search_body.lower()
    print(f"[probe] DataDome on search page: {datadome_search}")

    # 3. Check for __NEXT_DATA__
    nd = page.evaluate("() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }")
    if nd:
        print(f"[probe] __NEXT_DATA__ found! Length: {len(nd)}")
        try:
            blob = json.loads(nd)
            print(f"[probe] __NEXT_DATA__ top-level keys: {list(blob.keys())[:10]}")
        except Exception as e:
            print(f"[probe] __NEXT_DATA__ parse error: {e}")
    else:
        print("[probe] No __NEXT_DATA__ (not a Next.js page, or blocked)")

    # 4. Check for inline product JSON patterns
    import re
    prices_found = re.findall(r'[\$\"]price[\$\"]?\s*[:\=]\s*[\$\"]?([\d\.]+)', search_body[:5000])
    print(f"[probe] Price patterns in page source: {prices_found[:10]}")

    # 5. Look for product card text
    product_names = page.evaluate("""() => {
        const els = document.querySelectorAll('[class*="product-name"], [class*="item-name"], .description, [automation-id*="product"]');
        return Array.from(els).slice(0, 8).map(e => e.textContent.trim());
    }""")
    print(f"[probe] Product names visible on page: {product_names[:5]}")

    price_els = page.evaluate("""() => {
        const els = document.querySelectorAll('[class*="price"], [automation-id*="price"], [class*="Price"]');
        return Array.from(els).slice(0, 8).map(e => e.textContent.trim());
    }""")
    print(f"[probe] Price elements visible on page: {price_els[:8]}")

    # 6. Print all intercepted API calls — full URLs and JSON bodies for gdx-api
    print(f"\n[probe] Intercepted {len(intercepted)} relevant XHR/fetch responses:")
    gdx_calls = []
    for r in intercepted:
        is_gdx = "gdx-api.costco.com" in r["url"]
        is_search = "search" in r["url"].lower() and "json" in r.get("content_type","")
        if is_gdx or is_search:
            print(f"\n  [{r['status']}] {r['url']}")
            print(f"       content-type: {r['content_type']}")
            print(f"       body: {r['body_preview'][:500]}")
            if is_gdx:
                gdx_calls.append(r)

    # Save gdx API responses for offline analysis
    if gdx_calls:
        with open(".cache/costco_gdx_responses.json", "w") as f:
            json.dump(gdx_calls, f, indent=2)
        print(f"\n[probe] Saved {len(gdx_calls)} gdx-api responses to .cache/costco_gdx_responses.json")

    # Also look for any search-results-list API (not just per-item summary)
    search_apis = [r for r in intercepted if "search" in r["url"].lower() and "gdx" not in r["url"]]
    if search_apis:
        print(f"\n[probe] Other search APIs:")
        for r in search_apis[:5]:
            print(f"  [{r['status']}] {r['url'][:120]}")
            print(f"       body: {r['body_preview'][:300]}")

    # 7. Save full search page HTML for analysis
    with open(".cache/costco_search.html", "w", encoding="utf-8") as f:
        f.write(search_body)
    print(f"\n[probe] Full search HTML saved to .cache/costco_search.html ({len(search_body)} chars)")

    page.close()
    ctx.close()
    browser.close()
    print("\n[probe] Done.")


if __name__ == "__main__":
    import os
    os.makedirs(".cache", exist_ok=True)
    probe()
