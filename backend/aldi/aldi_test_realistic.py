"""
Realistic ALDI pricing test — 25 common grocery items, timed.
Also uses ThreadPoolExecutor to test parallel vs sequential speed.
"""
import time
import json
import uuid
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from cloakbrowser import launch
BASE_GQL = "https://www.aldi.us/graphql"
HASHES = {
    "DefaultShop":             "d389a8d33d63801f1ce5c4929fb181dd10c57b49c3a2dcb6a6baa44212e8e069",
    "SearchResultsPlacements": "387535ff634b5f783192dc1464d1253e514ff092876a1747486d90d83beb4dfd",
    "Items":                   "0362f9eaea7f55c17c95266a64f8c37a10b55d265318f85c761c59c382d96074",
}
BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US",
    "content-type": "application/json",
    "x-client-identifier": "web",
    "x-ic-view-layer": "true",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "referer": "https://www.aldi.us/store/aldi/s?query=",
}

# Representative meal-plan grocery list
TEST_ITEMS = [
    "large eggs", "whole milk", "butter", "shredded cheddar", "greek yogurt",
    "chicken breast", "ground beef", "ground turkey", "bacon", "salmon fillet",
    "bananas", "avocado", "spinach", "broccoli", "yellow onions",
    "garlic", "roma tomatoes", "russet potatoes", "carrots", "bell peppers",
    "pasta", "white rice", "olive oil", "chicken broth", "canned black beans",
]


# ── Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap(postal="77003"):
    cookies, qp, zone_id = {}, "", ""
    browser = launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        user_agent=BASE_HEADERS["user-agent"],
    )
    page = ctx.new_page()

        def on_req(req):
            nonlocal qp, zone_id
            if "graphql" not in req.url:
                return
            if not qp:
                v = req.headers.get("x-ic-qp", "")
                if v:
                    qp = v
            if "operationName=Items" in req.url and not zone_id:
                try:
                    import urllib.parse
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
                    vv = json.loads(qs.get("variables", ["{}"])[0])
                    z = vv.get("zoneId") or ""
                    if z:
                        zone_id = str(z)
                except Exception:
                    pass

        page.on("request", on_req)
        page.goto(f"https://www.aldi.us/store/aldi/s?query=eggs", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click(); time.sleep(2); break
            except: pass
        for sel in ["text=Delivery", "a:has-text('Delivery')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2500):
                    el.click(); time.sleep(3); break
            except: pass
        time.sleep(8)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    return cookies, qp, zone_id


# ── API calls ──────────────────────────────────────────────────────────────

def gql(op, variables, session):
    params = {
        "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES[op]}}, separators=(",", ":")),
    }
    headers = {**BASE_HEADERS, "x-page-view-id": str(uuid.uuid4())}
    r = session.get(BASE_GQL, params=params, headers=headers, timeout=12)
    if r.status_code != 200:
        return {}
    d = r.json()
    return {} if "errors" in d else (d.get("data") or {})


def price_one(item, shop_id, zone_id, postal, session):
    # Step 1: search
    d = gql("SearchResultsPlacements", {
        "action": None, "query": item, "pageViewId": str(uuid.uuid4()),
        "elevatedProductId": None, "searchSource": "search", "filters": [],
        "disableReformulation": False, "disableLlm": False, "forceInspiration": False,
        "orderBy": "bestMatch", "clusterId": None, "includeDebugInfo": False,
        "clusteringStrategy": None, "contentManagementSearchParams": {"itemGridColumnCount": 6},
        "shopId": shop_id, "postalCode": postal, "zoneId": zone_id, "first": 20,
    }, session)
    ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', json.dumps(d))))[:20]
    if not ids:
        return item, None

    # Step 2: fetch prices
    d2 = gql("Items", {
        "ids": ids, "shopId": shop_id, "zoneId": zone_id, "postalCode": postal,
    }, session)
    products = d2.get("items") or []

    # Pick best match
    query_words = set(item.lower().split())
    best = None
    for prod in products:
        name = prod.get("name") or ""
        price_sec = ((prod.get("price") or {}).get("viewSection")) or {}
        price_str = price_sec.get("priceValueString")
        if not price_str:
            continue
        try:
            price = float(re.sub(r"[^\d.]", "", str(price_str)))
            if not (0.01 <= price <= 300):
                continue
        except:
            continue
        unit = ""
        try:
            unit = price_sec["itemDetails"]["pricePerUnitString"] or ""
        except:
            pass
        name_words = set(name.lower().split())
        relevance = sum(1 for qw in query_words if any(qw in nw or nw in qw for nw in name_words))
        if best is None or relevance > best["relevance"] or (relevance == best["relevance"] and price < best["price"]):
            best = {"price": price, "unit": unit or prod.get("size", "each"), "name": name, "relevance": relevance}

    if best and best["relevance"] > 0:
        return item, best
    return item, None


# ── Main test ──────────────────────────────────────────────────────────────

print("=" * 60)
print(f"ALDI Realistic Price Test — {len(TEST_ITEMS)} items, Houston 77003")
print("=" * 60)

t0 = time.time()
print("\n[1] Bootstrapping session (Playwright)...")
cookies, qp, zone_id = bootstrap()
t_boot = time.time() - t0
print(f"    Done in {t_boot:.1f}s  |  zoneId={zone_id!r}  |  cookies={len(cookies)}")

session = requests.Session()
session.cookies.update(cookies)
if qp:
    session.headers.update({"x-ic-qp": qp})

# Get shop ID
shop_data = gql("DefaultShop", {
    "postalCode": "77003",
    "coordinates": {"latitude": 29.7515, "longitude": -95.3615},
    "addressId": None,
}, session).get("defaultShop") or {}
shop_id = shop_data.get("id", "1534")
print(f"    shopId={shop_id}")

# ── Sequential test ────────────────────────────────────────────────────────
print(f"\n[2] Sequential pricing ({len(TEST_ITEMS)} items)...")
t1 = time.time()
seq_results = {}
for item in TEST_ITEMS:
    _, result = price_one(item, shop_id, zone_id, "77003", session)
    seq_results[item] = result
t_seq = time.time() - t1
print(f"    Done in {t_seq:.1f}s  ({t_seq/len(TEST_ITEMS):.2f}s/item)")

# ── Parallel test ──────────────────────────────────────────────────────────
print(f"\n[3] Parallel pricing ({len(TEST_ITEMS)} items, 10 workers)...")
t2 = time.time()
par_results = {}
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = {
        pool.submit(price_one, item, shop_id, zone_id, "77003", session): item
        for item in TEST_ITEMS
    }
    for fut in as_completed(futures):
        item, result = fut.result()
        par_results[item] = result
t_par = time.time() - t2
print(f"    Done in {t_par:.1f}s  ({t_par/len(TEST_ITEMS):.2f}s/item effective)")

# ── Results ────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"RESULTS ({sum(1 for v in par_results.values() if v)}/{len(TEST_ITEMS)} matched)")
print(f"{'='*60}")
print(f"{'Item':<25} {'Price':>7}  {'Unit price':<22}  Product")
print("-" * 80)
for item in TEST_ITEMS:
    d = par_results.get(item)
    if d:
        print(f"{item:<25} ${d['price']:>5.2f}  {d['unit']:<22}  {d['name'][:35]}")
    else:
        print(f"{item:<25}   N/A")

print(f"\n{'='*60}")
print(f"TIMING SUMMARY")
print(f"  Bootstrap (once/day):  {t_boot:.1f}s")
print(f"  Sequential ({len(TEST_ITEMS)} items):   {t_seq:.1f}s")
print(f"  Parallel   ({len(TEST_ITEMS)} items):   {t_par:.1f}s")
print(f"  Projected async (aiohttp): ~{t_par*0.4:.1f}s")
print(f"{'='*60}")
