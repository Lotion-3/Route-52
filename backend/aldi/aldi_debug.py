"""Debug what the Items response actually contains."""
import json, uuid, re, requests
from cache_manager import cache

BASE_GQL = "https://www.aldi.us/graphql"
HASHES = {
    "SearchResultsPlacements": "387535ff634b5f783192dc1464d1253e514ff092876a1747486d90d83beb4dfd",
    "Items":                   "0362f9eaea7f55c17c95266a64f8c37a10b55d265318f85c761c59c382d96074",
}

# Load session cookies from cache (set by aldi_direct.py bootstrap)
# We'll reconstruct a session manually using what the previous run captured
from cloakbrowser import launch
import time

cookies_dict = {}
qp_value = ""

browser = launch(headless=False)
ctx = browser.new_context(
    viewport={"width": 1366, "height": 768},
    locale="en-US",
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
page = ctx.new_page()

    def on_request(req):
        global qp_value
        if "graphql" in req.url and not qp_value:
            qp = req.headers.get("x-ic-qp", "")
            if qp:
                qp_value = qp
                print(f"[captured qp]")

    page.on("request", on_request)
    page.goto("https://www.aldi.us/store/aldi/s?query=bananas", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click(); time.sleep(2); print("Cookies accepted"); break
        except: pass

    for sel in ["text=Delivery", "a:has-text('Delivery')"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2500):
                el.click(); time.sleep(3); print("Delivery set"); break
        except: pass

    time.sleep(8)
    cookies_dict = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()

session = requests.Session()
session.cookies.update(cookies_dict)
headers = {
    "accept": "*/*",
    "accept-language": "en-US",
    "content-type": "application/json",
    "x-client-identifier": "web",
    "x-ic-view-layer": "true",
    "x-page-view-id": str(uuid.uuid4()),
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "referer": "https://www.aldi.us/store/aldi/s?query=bananas",
}
if qp_value:
    headers["x-ic-qp"] = qp_value

def gql(op, variables):
    params = {
        "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES[op]}}, separators=(",", ":")),
    }
    r = session.get(BASE_GQL, params=params, headers={**headers, "x-page-view-id": str(uuid.uuid4())}, timeout=15)
    print(f"  [{op}] {r.status_code}")
    data = r.json()
    if "errors" in data:
        print(f"  ERRORS: {data['errors'][:1]}")
    return data.get("data") or {}

# Search for bananas
print("=== SearchResultsPlacements: bananas ===")
d = gql("SearchResultsPlacements", {
    "action": None, "query": "bananas", "pageViewId": str(uuid.uuid4()),
    "elevatedProductId": None, "searchSource": "search", "filters": [],
    "disableReformulation": False, "disableLlm": False, "forceInspiration": False,
    "orderBy": "bestMatch", "clusterId": None, "includeDebugInfo": False,
    "clusteringStrategy": None, "contentManagementSearchParams": {"itemGridColumnCount": 6},
    "shopId": "1534", "postalCode": "77003", "zoneId": None, "first": 20,
})
raw = json.dumps(d)
ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', raw)))
print(f"  IDs found: {len(ids)} — first 5: {ids[:5]}")

# Fetch items
if ids:
    print("\n=== Items fetch (first 6 IDs) ===")
    d2 = gql("Items", {
        "ids": ids[:6],
        "shopId": "1534",
        "zoneId": None,
        "postalCode": "77003",
    })
    items = d2.get("items") or []
    print(f"  Items returned: {len(items)}")
    for item in items[:8]:
        name = item.get("name", "?")
        size = item.get("size", "")
        price_sec = ((item.get("price") or {}).get("viewSection")) or {}
        price_str = price_sec.get("priceValueString")
        try:
            unit = price_sec["itemDetails"]["pricePerUnitString"]
        except:
            unit = ""
        print(f"  {name} ({size}) -> price={price_str!r} unit={unit!r}")
