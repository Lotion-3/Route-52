"""Probe 6 — test product summary API with correct auth headers."""
import json, time

HOME_URL = "https://www.costco.com/"
SEARCH_URL = "https://www.costco.com/CatalogSearch?keyword=milk&pageSize=24"
SEARCH_API = "https://gdx-api.costco.com/catalog/search/api/v1/search"
SUMMARY_API = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"

captured_req = {}
resp_ids = []

from cloakbrowser import launch
browser = launch(headless=True)
ctx = browser.new_context()

def on_req(req):
    if "catalog/search/api" in req.url:
        captured_req["headers"] = dict(req.all_headers())
        captured_req["body"] = req.post_data or ""

def on_resp(resp):
    if "catalog/search/api" in resp.url and resp.status == 200:
        try:
            ids = [r["id"] for r in json.loads(resp.text()).get("searchResult",{}).get("results",[])]
            resp_ids.extend(ids)
        except Exception:
            pass

page = ctx.new_page()
page.on("request", on_req)
page.on("response", on_resp)
try:
    page.goto(HOME_URL, wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(3)
try:
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(5)
page.close()

print(f"Product IDs: {resp_ids[:12]}")
print(f"client-identifier: {captured_req.get('headers',{}).get('client-identifier','NOT FOUND')}")

if resp_ids and captured_req.get("headers"):
    hdrs = {k:v for k,v in captured_req["headers"].items() if not k.startswith(":")}
    sum_hdrs = {k:v for k,v in hdrs.items() if k in
                ("client-identifier","client_id","locale","searchresultprovider",
                 "accept","accept-language","user-agent","origin","referer")}
    print(f"Auth headers: {list(sum_hdrs.keys())}")

    url = (f"{SUMMARY_API}?clientId={CLIENT_ID}"
           f"&items={','.join(resp_ids[:15])}&whsNumber=347&locales=en-us")
    r = ctx.request.get(url, headers=sum_hdrs, timeout=30000)
    print(f"Summary status: {r.status}")
    if r.status == 200:
        products = json.loads(r.text()).get("productData",[])
        print(f"Products: {len(products)}")
        for p in products:
            name = ""
            for d in (p.get("descriptions") or []):
                if d.get("languageKey") == "en-US":
                    name = d.get("object",{}).get("shortDescription","")
                    break
            kids = p.get("childCatalogData") or []
            prices = [c["displayPrice"] for c in kids
                      if c.get("displayPrice") and c["displayPrice"].get("onlinePrice")]
            price_str = [f"${x.get('onlinePrice')}(whs{x.get('warehouseNumber')})" for x in prices[:2]]
            print(f"  [{p['id']}] {name[:55]}  prices={price_str or 'NONE'}")
        with open(".cache/costco_milk_fixture.json","w") as f:
            json.dump(products, f, indent=2)
        print("Saved fixture.")
    else:
        print(f"Error: {r.text()[:400]}")

ctx.close()
browser.close()
print("Done.")
