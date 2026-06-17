"""
Probe 8 — use page.evaluate(fetch(...)) for BOTH search and product summary,
since the page context has gdx-api.costco.com cookies set naturally.
Also try page.route() to intercept product summary responses directly.
"""
import json, time

CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
CLIENT_IDENTIFIER = "168287ea-1201-45f6-9b45-5bbea49f8ee7"
SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"

from cloakbrowser import launch
browser = launch(headless=True)
ctx = browser.new_context()

# Intercept product summary responses via route
intercepted_products: list[dict] = []

def handle_route(route):
    resp = route.fetch()
    if resp.status == 200:
        try:
            body = json.loads(resp.body())
            intercepted_products.extend(body.get("productData", []))
        except Exception:
            pass
    route.fulfill(response=resp)

ctx.route("**/catalog/product/product-api/v1/products/summary**", handle_route)

# Warm session
page = ctx.new_page()
print("[probe8] Loading homepage ...")
try:
    page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(3)

print("[probe8] Loading milk search page (will trigger natural product summary calls) ...")
try:
    page.goto("https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24",
              wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(5)

print(f"[probe8] Intercepted {len(intercepted_products)} products via route()")
for p in intercepted_products[:5]:
    name = ""
    for d in (p.get("descriptions") or []):
        if d.get("languageKey") == "en-US":
            name = d.get("object",{}).get("shortDescription","")
            break
    kids = p.get("childCatalogData") or []
    prices = [c["displayPrice"] for c in kids
              if c.get("displayPrice") and c["displayPrice"].get("onlinePrice")]
    price_strs = [f"${x['onlinePrice']}" for x in prices[:2]] or ["NONE"]
    print(f"  [{p['id']}] {name[:50]}  prices={price_strs}")

# Now try page.evaluate(fetch) for product summary with known IDs
KNOWN_IDS = [
    "4000240044","100533380","100638343","100456512","100567351",
    "100727293","4000239967","100489408","100511905",
]
print(f"\n[probe8] Calling product summary via page.evaluate(fetch(...)) ...")
summary_url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
               f"&items={','.join(KNOWN_IDS[:9])}&whsNumber=347&locales=en-us")
js = f"""
async () => {{
    try {{
        const resp = await fetch({json.dumps(summary_url)}, {{
            method: 'GET',
            headers: {{
                'client-identifier': {json.dumps(CLIENT_IDENTIFIER)},
                'client_id': 'USBC',
                'locale': 'en-US',
                'searchresultprovider': 'GRS',
            }}
        }});
        const text = await resp.text();
        return {{ status: resp.status, body: text.substring(0, 5000) }};
    }} catch(e) {{ return {{ status: 0, body: String(e) }}; }}
}}
"""
try:
    result = page.evaluate(js)
    print(f"  Status: {result['status']}")
    if result['status'] == 200:
        body = json.loads(result['body'])
        products = body.get("productData", [])
        print(f"  Products: {len(products)}")
        for p in products:
            name = ""
            for d in (p.get("descriptions") or []):
                if d.get("languageKey") == "en-US":
                    name = d.get("object",{}).get("shortDescription","")
                    break
            kids = p.get("childCatalogData") or []
            prices = [c["displayPrice"] for c in kids
                      if c.get("displayPrice") and c["displayPrice"].get("onlinePrice")]
            price_strs = [f"${x['onlinePrice']}(whs{x.get('warehouseNumber')})" for x in prices[:2]]
            print(f"  [{p['id']}] {name[:50]}  prices={price_strs or 'NONE'}")
        # Save fixture
        if products:
            with open(".cache/costco_milk_fixture.json","w") as f:
                json.dump(products, f, indent=2)
            print("  Saved fixture.")
    else:
        print(f"  Error body: {result['body'][:400]}")
except Exception as e:
    print(f"  evaluate error: {e}")

page.close()
ctx.close()
browser.close()
print("\n[probe8] Done.")
