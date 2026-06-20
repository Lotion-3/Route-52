"""
Probe 9 — final Costco feasibility probe.

For each basket ingredient, check:
  1. Does the search API return results?
  2. Do the search result IDs appear in the product summary intercepts?
  3. Are those products priced (onlinePrice > 0)?
  4. What are the actual product names and prices?

Uses the route-interception approach (proved working in probe8).
"""
import json, time
from urllib.parse import quote

SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
CLIENT_IDENTIFIER = "168287ea-1201-45f6-9b45-5bbea49f8ee7"

# Standard basket terms, plus some Costco-likely alternatives
TERMS = [
    "whole milk",
    "organic milk",
    "eggs",
    "chicken breast",
    "white rice",
    "olive oil",
    "bread",
    "almond milk",
    "orange juice",
    "canned tuna",
]

from cloakbrowser import launch
browser = launch(headless=True)
ctx = browser.new_context()

page = ctx.new_page()
print("[probe9] Warming session ...")
try:
    page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(3)
page.close()

SEARCH_HEADERS = {
    "client-identifier": CLIENT_IDENTIFIER,
    "client_id": "USBC",
    "locale": "en-US",
    "searchresultprovider": "GRS",
    "content-type": "application/json",
    "accept": "*/*",
    "origin": "https://www.costco.com",
    "referer": "https://www.costco.com/",
}


def search_and_price(term: str) -> list[dict]:
    """Returns list of priced products for a search term using route interception."""
    products_by_id: dict[str, dict] = {}

    def handle_route(route):
        try:
            resp = route.fetch()
            if resp.status == 200:
                try:
                    data = json.loads(resp.body())
                    for p in data.get("productData", []):
                        products_by_id[p["id"]] = p
                except Exception:
                    pass
            route.fulfill(response=resp)
        except Exception:
            route.continue_()

    ctx.route("**/catalog/product/product-api/v1/products/summary**", handle_route)

    # Do the search directly via ctx.request (we know this works)
    search_body = {
        "visitorId": "83099816520155961790818054284274511765",
        "query": term,
        "pageSize": 24,
        "offset": 0,
        "searchMode": "page",
        "personalizationEnabled": False,
        "warehouseId": "347-wh",
        "shipToPostal": "46032",
        "shipToState": "IN",
        "deliveryLocations": ["347-wh"],
    }
    sr = ctx.request.fetch(
        SEARCH_API,
        method="POST",
        headers=SEARCH_HEADERS,
        data=json.dumps(search_body),
        timeout=30000,
    )
    if sr.status != 200:
        ctx.unroute("**/catalog/product/product-api/v1/products/summary**", handle_route)
        return []

    search_ids = [r["id"] for r in json.loads(sr.text()).get("searchResult",{}).get("results",[])]

    # Now load the search page to trigger product summary calls for these IDs
    p2 = ctx.new_page()
    try:
        p2.goto(f"https://www.costco.com/CatalogSearch?keyword={quote(term)}&pageSize=24",
                wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(4)
    p2.close()
    ctx.unroute("**/catalog/product/product-api/v1/products/summary**", handle_route)

    # Try to also directly call summary for search IDs
    if search_ids:
        sum_url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
                   f"&items={','.join(search_ids[:15])}&whsNumber=347&locales=en-us")
        # Try via ctx.request first (might 403 but worth a shot)
        sr2 = ctx.request.get(sum_url, headers={k:v for k,v in SEARCH_HEADERS.items()
                                                  if k != "content-type"}, timeout=30000)
        if sr2.status == 200:
            for p in json.loads(sr2.text()).get("productData",[]):
                products_by_id[p["id"]] = p

    # Filter to search result IDs only
    result = []
    for sid in search_ids:
        if sid in products_by_id:
            p = products_by_id[sid]
            name = ""
            for d in (p.get("descriptions") or []):
                if d.get("languageKey") == "en-US":
                    name = d.get("object",{}).get("shortDescription","")
                    break
            kids = p.get("childCatalogData") or []
            best_price = None
            for c in kids:
                dp = c.get("displayPrice")
                if dp and dp.get("onlinePrice") and dp["onlinePrice"] > 0:
                    if best_price is None or dp["onlinePrice"] < best_price:
                        best_price = dp["onlinePrice"]
            if name and best_price:
                result.append({"id": sid, "name": name, "price": best_price})

    return result


print("\n=== Costco ingredient feasibility ===")
results_summary = {}
for term in TERMS:
    print(f"\n  Searching: '{term}' ...")
    results = search_and_price(term)
    results_summary[term] = results
    if results:
        for r in results[:3]:
            print(f"    [{r['id']}] ${r['price']:6.2f}  {r['name'][:55]}")
    else:
        print(f"    (no priced results)")
    time.sleep(1)

print("\n=== Summary ===")
for term, results in results_summary.items():
    status = f"{len(results)} priced" if results else "0 priced (SKIP)"
    best = f"  best: ${min(r['price'] for r in results):.2f} — {min(results, key=lambda x: x['price'])['name'][:40]}" if results else ""
    print(f"  {term:20s}: {status}{best}")

with open(".cache/costco_feasibility.json","w") as f:
    json.dump(results_summary, f, indent=2)
print("\nSaved to .cache/costco_feasibility.json")

ctx.close()
browser.close()
print("\n[probe9] Done.")
