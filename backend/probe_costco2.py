"""
Costco deep probe — captures full API response bodies and intercepts
the search API URL with all its parameters.

Run:  python probe_costco2.py
"""
import json
import time
import re

HOME_URL = "https://www.costco.com/"
SEARCH_URL = "https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24"

full_responses: list[dict] = []


def probe():
    from cloakbrowser import launch
    print("[probe2] Launching CloakBrowser ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_response(resp):
        url = resp.url
        if "gdx-api.costco.com" in url or ("costco.com" in url and "search" in url.lower() and "_next" not in url):
            try:
                body = resp.text()
                ct = resp.headers.get("content-type", "")
                full_responses.append({"url": url, "status": resp.status,
                                       "content_type": ct, "body": body})
            except Exception as e:
                full_responses.append({"url": url, "status": resp.status,
                                       "content_type": "", "body": f"ERROR: {e}"})

    page = ctx.new_page()
    page.on("response", on_response)

    print(f"[probe2] Loading homepage ...")
    try:
        page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(3)

    print(f"[probe2] Loading milk search ...")
    try:
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(5)

    print(f"\n[probe2] Captured {len(full_responses)} API responses\n")

    # Find the search endpoint with full params
    search_api = None
    for r in full_responses:
        if "catalog/search/api" in r["url"]:
            search_api = r
            break

    if search_api:
        print(f"=== SEARCH API ===")
        print(f"URL: {search_api['url']}")
        try:
            body = json.loads(search_api["body"])
            print(f"Top-level keys: {list(body.keys())}")
            results = body.get("searchResult", {}).get("results", [])
            print(f"Number of results: {len(results)}")
            if results:
                r0 = results[0]
                print(f"First result keys: {list(r0.keys())}")
                attrs = r0.get("attributes", {})
                print(f"First result attributes keys: {list(attrs.keys())[:20]}")
                print(f"First result id: {r0.get('id')}")
                prod = r0.get("product", {})
                print(f"First result product keys: {list(prod.keys())[:15]}")
                # Look for price in attributes
                for key in attrs:
                    if "price" in key.lower() or "cost" in key.lower():
                        print(f"  PRICE ATTR: {key} = {attrs[key]}")
        except Exception as e:
            print(f"Parse error: {e}")
            print(search_api["body"][:1000])

    # Find product summary responses and show full price fields
    summary_apis = [r for r in full_responses if "products/summary" in r["url"]]
    print(f"\n=== PRODUCT SUMMARY API ({len(summary_apis)} calls) ===")
    price_items_found = 0
    for sa in summary_apis[:2]:
        print(f"\nURL: {sa['url'][:120]}")
        try:
            body = json.loads(sa["body"])
            products = body.get("productData", [])
            print(f"  productData count: {len(products)}")
            for p in products[:3]:
                print(f"\n  --- Product {p.get('id')} ---")
                # Print all keys
                print(f"  Keys: {list(p.keys())}")
                # Look for price fields
                for k, v in p.items():
                    if any(w in k.lower() for w in ("price", "cost", "sale", "amount", "retail")):
                        print(f"  PRICE FIELD: {k} = {v!r}")
                        price_items_found += 1
                print(f"  dispPriceInCartOnly: {p.get('dispPriceInCartOnly')}")
                print(f"  name: {p.get('name', p.get('description', ''))[:80]}")
        except Exception as e:
            print(f"  Parse error: {e}")
            print(sa["body"][:500])

    if price_items_found == 0:
        print("\n  *** NO PRICE FIELDS FOUND in products/summary responses ***")
        print("  This means prices are hidden (dispPriceInCartOnly) or in a different API.")

    # Look for the actual search XHR URL with query params
    print("\n=== ALL COSTCO API CALLS ===")
    for r in full_responses:
        print(f"  [{r['status']}] {r['url'][:120]}")

    # Save full responses for analysis
    with open(".cache/costco_deep.json", "w") as f:
        json.dump(full_responses, f, indent=2)
    print(f"\nSaved {len(full_responses)} full responses to .cache/costco_deep.json")

    page.close()
    ctx.close()
    browser.close()


if __name__ == "__main__":
    import os
    os.makedirs(".cache", exist_ok=True)
    probe()
