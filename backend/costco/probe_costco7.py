"""
Probe 7 — directly call the product summary API with known IDs
and the client-identifier header we captured. Also find warehouse lookup.
"""
import json, time

# Known product IDs from earlier probes (milk search results)
KNOWN_IDS = [
    "4000240044","100533380","100638343","100456512","100567351",
    "100727293","100710341","100810650","4000239967","4000346410",
    "4000354349","100489408","100511905",
]

CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
CLIENT_IDENTIFIER = "168287ea-1201-45f6-9b45-5bbea49f8ee7"  # captured from browser
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"

AUTH_HEADERS = {
    "client-identifier": CLIENT_IDENTIFIER,
    "client_id": "USBC",
    "locale": "en-US",
    "searchresultprovider": "GRS",
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://www.costco.com",
    "referer": "https://www.costco.com/",
}

from cloakbrowser import launch
browser = launch(headless=True)
ctx = browser.new_context()

# Warm DataDome session
page = ctx.new_page()
print("[probe7] Warming session ...")
try:
    page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(3)
page.close()

# --- Test 1: Product summary with known IDs ---
for whs in ["347", "3", "13", "0"]:
    url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
           f"&items={','.join(KNOWN_IDS[:8])}&whsNumber={whs}&locales=en-us")
    r = ctx.request.get(url, headers=AUTH_HEADERS, timeout=30000)
    print(f"[probe7] Summary whsNumber={whs}: status={r.status}")
    if r.status == 200:
        body = json.loads(r.text())
        products = body.get("productData", [])
        has_prices = sum(1 for p in products
                         for c in (p.get("childCatalogData") or [])
                         if c.get("displayPrice") and c["displayPrice"].get("onlinePrice"))
        print(f"  products={len(products)} children_with_price={has_prices}")
        if has_prices:
            # Show prices
            for p in products:
                name = ""
                for d in (p.get("descriptions") or []):
                    if d.get("languageKey") == "en-US":
                        name = d.get("object",{}).get("shortDescription","")
                        break
                for c in (p.get("childCatalogData") or []):
                    dp = c.get("displayPrice")
                    if dp and dp.get("onlinePrice"):
                        print(f"  {p['id']}: {name[:45]}  ${dp['onlinePrice']}  whs={dp.get('warehouseNumber')}")
            break
    elif r.status != 401:
        print(f"  body: {r.text()[:200]}")

# --- Test 2: Search API call directly (no browser page) ---
print("\n[probe7] Testing search API directly via ctx.request ...")
search_body = {
    "visitorId": "83099816520155961790818054284274511765",
    "query": "milk",
    "pageSize": 10,
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
    headers={**AUTH_HEADERS, "content-type": "application/json"},
    data=json.dumps(search_body),
    timeout=30000,
)
print(f"Search status: {sr.status}")
if sr.status == 200:
    ids = [r["id"] for r in json.loads(sr.text()).get("searchResult",{}).get("results",[])]
    print(f"IDs ({len(ids)}): {ids[:8]}")
else:
    print(f"Error: {sr.text()[:300]}")

# --- Test 3: Warehouse lookup ---
print("\n[probe7] Testing warehouse lookup ...")
# Costco warehouse search by zip (found in their JS)
for whs_url in [
    "https://www.costco.com/WarehouseFinder?zipcode=90210&maxResults=3&serviceTypes=11",
    "https://www.costco.com/wcs/resources/store/10301/warehousesearch?zipCode=90210&maxResults=3",
    "https://www.costco.com/WebAuthenticationSetupCmd",
]:
    r = ctx.request.get(whs_url, headers=AUTH_HEADERS, timeout=15000)
    print(f"  [{r.status}] {whs_url[:80]}")
    if r.status == 200:
        print(f"       {r.text()[:300]}")

ctx.close()
browser.close()
print("\n[probe7] Done.")
