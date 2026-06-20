"""
Costco probe 3 — capture:
  1. Full search API POST body / query params (intercepting requests, not responses)
  2. Grocery-item prices from childCatalogData[].displayPrice.onlinePrice
  3. Warehouse resolution API (how does the site resolve whsNumber from location?)

Run:  python probe_costco3.py
"""
import json
import time

HOME_URL = "https://www.costco.com/"
SEARCH_URL = "https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24"

req_log: list[dict] = []
resp_log: list[dict] = []


def probe():
    from cloakbrowser import launch
    print("[probe3] Launching CloakBrowser ...")
    browser = launch(headless=True)
    ctx = browser.new_context()

    def on_request(req):
        url = req.url
        if "gdx-api.costco.com" in url or ("costco.com" in url and "whs" in url.lower()):
            try:
                body = req.post_data or ""
            except Exception:
                body = ""
            req_log.append({
                "method": req.method,
                "url": url,
                "headers": dict(req.headers),
                "body": body,
            })

    def on_response(resp):
        url = resp.url
        if "gdx-api.costco.com" in url:
            try:
                body = resp.text()
                resp_log.append({"url": url, "status": resp.status, "body": body})
            except Exception as e:
                resp_log.append({"url": url, "status": resp.status, "body": f"ERROR: {e}"})

    page = ctx.new_page()
    page.on("request", on_request)
    page.on("response", on_response)

    print("[probe3] Loading homepage ...")
    try:
        page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(3)

    print("[probe3] Loading milk search ...")
    try:
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(5)

    print(f"[probe3] Page title: {page.title()!r}")
    print(f"[probe3] Page URL: {page.url}")

    print(f"\n=== REQUESTS TO gdx-api ({len(req_log)}) ===")
    for r in req_log:
        print(f"\n  {r['method']} {r['url'][:120]}")
        # Key headers
        for h in ("content-type", "authorization", "x-api-key", "cookie", "x-client-id"):
            if h in r["headers"]:
                print(f"    {h}: {r['headers'][h][:80]}")
        if r["body"]:
            print(f"    body: {r['body'][:300]}")

    print(f"\n=== RESPONSES FROM gdx-api ({len(resp_log)}) ===")
    grocery_items = []
    for resp in resp_log:
        if "products/summary" not in resp["url"]:
            continue
        try:
            body = json.loads(resp["body"])
            products = body.get("productData", [])
            for p in products:
                desc_obj = {}
                for d in (p.get("descriptions") or []):
                    if d.get("languageKey") == "en-US":
                        desc_obj = d.get("object", {})
                        break
                name = desc_obj.get("shortDescription", "")
                # Look for grocery items
                if any(kw in name.lower() for kw in
                       ("milk", "egg", "bread", "chicken", "rice", "banana", "oil", "food", "organic")):
                    print(f"\n  GROCERY: {p['id']} dispPriceInCartOnly={p.get('dispPriceInCartOnly')}")
                    print(f"    name: {name[:80]}")
                    # Find prices in childCatalogData
                    for child in (p.get("childCatalogData") or []):
                        dp = child.get("displayPrice")
                        if dp:
                            print(f"    child {child['id']}: displayPrice = {json.dumps(dp)}")
                            grocery_items.append({
                                "id": p["id"],
                                "name": name,
                                "dispPriceInCartOnly": p.get("dispPriceInCartOnly"),
                                "childId": child["id"],
                                "displayPrice": dp,
                            })
        except Exception as e:
            print(f"  Parse error: {e}")

    # Also find the search API response
    for resp in resp_log:
        if "catalog/search/api" in resp["url"] or "search" in resp["url"].lower():
            print(f"\n=== SEARCH API ===")
            print(f"URL: {resp['url'][:150]}")
            try:
                body = json.loads(resp["body"])
                results = body.get("searchResult", {}).get("results", [])
                print(f"Result count: {len(results)}")
                if results:
                    r0 = results[0]
                    print(f"First result keys: {list(r0.keys())}")
                    print(f"First result id: {r0.get('id')}")
                    attrs = r0.get("attributes", {})
                    print(f"First result attributes: {json.dumps(attrs)[:500]}")
            except Exception as e:
                print(f"Parse error: {e}")
                print(resp["body"][:300])

    # Save grocery items
    if grocery_items:
        with open(".cache/costco_grocery_prices.json", "w") as f:
            json.dump(grocery_items, f, indent=2)
        print(f"\n[probe3] Saved {len(grocery_items)} grocery items to .cache/costco_grocery_prices.json")
    else:
        print("\n[probe3] No grocery items found — milk search may not have returned grocery products.")
        print("[probe3] Saving all product names for inspection ...")
        all_names = []
        for resp in resp_log:
            if "products/summary" not in resp["url"]:
                continue
            try:
                body = json.loads(resp["body"])
                for p in body.get("productData", []):
                    for d in (p.get("descriptions") or []):
                        if d.get("languageKey") == "en-US":
                            name = d.get("object", {}).get("shortDescription", "")
                            if name:
                                all_names.append({"id": p["id"], "name": name[:80],
                                                  "dispPrice": p.get("dispPriceInCartOnly")})
            except Exception:
                pass
        for n in all_names:
            print(f"  {n['id']} [{n['dispPrice']}] {n['name']}")

        # Also show childCatalogData prices for the first few items regardless
        print("\n[probe3] First 3 products with childCatalogData prices:")
        count = 0
        for resp in resp_log:
            if "products/summary" not in resp["url"] or count >= 3:
                continue
            try:
                body = json.loads(resp["body"])
                for p in body.get("productData", []):
                    if count >= 3:
                        break
                    children_with_price = [
                        c for c in (p.get("childCatalogData") or [])
                        if c.get("displayPrice")
                    ]
                    if children_with_price:
                        name = ""
                        for d in (p.get("descriptions") or []):
                            if d.get("languageKey") == "en-US":
                                name = d.get("object", {}).get("shortDescription", "")
                                break
                        print(f"  {p['id']}: {name[:60]}")
                        for c in children_with_price[:2]:
                            print(f"    child {c['id']}: {json.dumps(c['displayPrice'])}")
                        count += 1
            except Exception:
                pass

    page.close()
    ctx.close()
    browser.close()
    print("\n[probe3] Done.")


if __name__ == "__main__":
    import os
    os.makedirs(".cache", exist_ok=True)
    probe()
