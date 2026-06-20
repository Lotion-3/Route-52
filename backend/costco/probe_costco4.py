"""
Costco probe 4 — validate the full pricing pipeline:
  1. Warm session on costco.com (DataDome cookies)
  2. Call search API via page.evaluate(fetch(...)) → product IDs
  3. Call product summary API via ctx.request.get() → prices
  4. Find warehouse lookup API (zip → whsNumber)

Run:  python probe_costco4.py
"""
import json
import time
import re

HOME_URL = "https://www.costco.com/"
CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"

SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
WHS_LOOKUP  = "https://www.costco.com/AjaxWarehouseSearchCmd"   # guessed, may 404


def probe():
    from cloakbrowser import launch
    browser = launch(headless=True)
    ctx = browser.new_context()

    # --- Warm DataDome cookies ---
    print("[probe4] Warming DataDome session ...")
    page = ctx.new_page()
    try:
        page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(3)

    # --- Try warehouse lookup API ---
    print("\n[probe4] Trying warehouse lookup APIs ...")
    for whs_url in [
        "https://www.costco.com/AjaxWarehouseSearchCmd?langId=-1&storeId=10301&zipCode=90210&countryCode=US&radius=25&maxCount=5",
        "https://www.costco.com/location/search.html?q=90210&count=5",
        "https://gdx-api.costco.com/catalog/warehouse/api/v1/warehouses/nearest?zipCode=90210&limit=5",
        "https://www.costco.com/whlsearch/warehouse-by-zip?zipCode=90210",
    ]:
        resp = ctx.request.get(whs_url, timeout=15000)
        print(f"  [{resp.status}] {whs_url[:80]}")
        if resp.status == 200:
            print(f"       body: {resp.text()[:300]}")

    # --- Search API via in-page fetch ---
    print("\n[probe4] Calling search API via page.evaluate(fetch(...)) ...")
    search_payload = {
        "visitorId": "probe-visitor-1234",
        "query": "whole milk gallon",
        "pageSize": 10,
        "offset": 0,
        "orderBy": None,
        "searchMode": "page",
        "personalizationEnabled": False,
        "warehouseId": "347-wh",         # default; probe will try multiple
        "shipToPostal": "90210",
        "shipToState": "CA",
        "deliveryLocations": ["347-wh"],
    }
    search_js = f"""
    async () => {{
        const resp = await fetch('{SEARCH_API}', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({json.dumps(search_payload)})
        }});
        const text = await resp.text();
        return {{ status: resp.status, body: text.substring(0, 3000) }};
    }}
    """
    try:
        result = page.evaluate(search_js)
        print(f"  Search API status: {result['status']}")
        body_str = result["body"]
        if result["status"] == 200:
            try:
                body = json.loads(body_str)
                results = body.get("searchResult", {}).get("results", [])
                print(f"  Search results count: {len(results)}")
                ids = [r["id"] for r in results[:10]]
                print(f"  Product IDs: {ids}")

                # --- Fetch prices for those IDs ---
                if ids:
                    print(f"\n[probe4] Fetching product summary for {len(ids)} IDs ...")
                    summary_url = (
                        f"{SUMMARY_API}?clientId={CLIENT_ID}"
                        f"&items={','.join(ids)}&whsNumber=347&locales=en-us"
                    )
                    # Try via ctx.request.get (browser TLS + cookies)
                    sum_resp = ctx.request.get(summary_url, timeout=30000)
                    print(f"  Summary API status: {sum_resp.status}")
                    if sum_resp.status == 200:
                        sum_body = json.loads(sum_resp.text())
                        products = sum_body.get("productData", [])
                        print(f"  Products returned: {len(products)}")
                        for p in products:
                            # Get name
                            name = ""
                            for d in (p.get("descriptions") or []):
                                if d.get("languageKey") == "en-US":
                                    name = d.get("object", {}).get("shortDescription", "")
                                    break
                            # Get price from childCatalogData
                            children = p.get("childCatalogData") or []
                            prices_found = []
                            for c in children:
                                dp = c.get("displayPrice")
                                if dp and dp.get("onlinePrice"):
                                    prices_found.append(dp)
                            print(f"\n  [{p['id']}] dispPriceInCartOnly={p.get('dispPriceInCartOnly')}")
                            print(f"    name: {name[:70]}")
                            if prices_found:
                                for dp in prices_found[:2]:
                                    print(f"    PRICE: onlinePrice=${dp.get('onlinePrice')} "
                                          f"warehouseNumber={dp.get('warehouseNumber')}")
                            else:
                                print(f"    NO PRICE (children={len(children)}, "
                                      f"children_with_dp={sum(1 for c in children if c.get('displayPrice'))})")
                                # Show child structure if no price
                                if children:
                                    c0 = children[0]
                                    print(f"    first child keys: {list(c0.keys())}")
                                    print(f"    first child displayPrice: {c0.get('displayPrice')}")
                    else:
                        print(f"  Summary error body: {sum_resp.text()[:300]}")
            except Exception as e:
                print(f"  Parse error: {e}")
                print(f"  Body: {body_str[:500]}")
        else:
            print(f"  Error body: {body_str[:300]}")
    except Exception as e:
        print(f"  evaluate error: {e}")

    # --- Also try ctx.request directly on search API ---
    print("\n[probe4] Calling search API via ctx.request.post ...")
    try:
        sr = ctx.request.fetch(
            SEARCH_API,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(search_payload),
            timeout=30000,
        )
        print(f"  status: {sr.status}")
        if sr.status == 200:
            sb = json.loads(sr.text())
            r2 = sb.get("searchResult", {}).get("results", [])
            print(f"  results: {len(r2)} ids: {[x['id'] for x in r2[:5]]}")
    except Exception as e:
        print(f"  error: {e}")

    page.close()
    ctx.close()
    browser.close()
    print("\n[probe4] Done.")


if __name__ == "__main__":
    probe()
