"""
Test whether ALDI prices vary across the country.
Bootstraps once, then hits 5 cities using each city's shopId.
"""
import time, json, uuid, re, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from cloakbrowser import launch
BASE_GQL   = "https://www.aldi.us/graphql"
HASHES = {
    "DefaultShop":             "d389a8d33d63801f1ce5c4929fb181dd10c57b49c3a2dcb6a6baa44212e8e069",
    "SearchResultsPlacements": "387535ff634b5f783192dc1464d1253e514ff092876a1747486d90d83beb4dfd",
    "Items":                   "0362f9eaea7f55c17c95266a64f8c37a10b55d265318f85c761c59c382d96074",
}
BASE_HEADERS = {
    "accept": "*/*", "accept-language": "en-US", "content-type": "application/json",
    "x-client-identifier": "web", "x-ic-view-layer": "true",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "referer": "https://www.aldi.us/store/aldi/s?query=",
}

CITIES = {
    "Houston TX":    ("77003", 29.7515, -95.3615),
    "Chicago IL":    ("60606", 41.8781, -87.6298),
    "Denver CO":     ("80218", 39.7392, -104.9903),
    "Los Angeles CA":("90028", 34.1016, -118.3267),
    "Atlanta GA":    ("30301", 33.7490, -84.3880),
}

# Focused list — items with clear names to minimise bad matches
TEST_ITEMS = [
    "large eggs", "whole milk", "bananas", "chicken breast",
    "ground beef", "butter", "shredded cheddar", "russet potatoes",
    "yellow onions", "white rice",
]


# ── Bootstrap ──────────────────────────────────────────────────────────────
def bootstrap():
    cookies, qp, zone_id = {}, "", ""
    browser = launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768}, locale="en-US",
        user_agent=BASE_HEADERS["user-agent"],
    )
    page = ctx.new_page()

        def on_req(req):
            nonlocal qp, zone_id
            if "graphql" not in req.url: return
            if not qp:
                v = req.headers.get("x-ic-qp", "")
                if v: qp = v
            if "operationName=Items" in req.url and not zone_id:
                try:
                    import urllib.parse
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
                    vv = json.loads(qs.get("variables", ["{}"])[0])
                    z = vv.get("zoneId") or ""
                    if z: zone_id = str(z)
                except: pass

        page.on("request", on_req)
        page.goto("https://www.aldi.us/store/aldi/s?query=eggs", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        for sel in ["button:has-text('Accept All')", "button:has-text('Accept')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000): el.click(); time.sleep(2); break
            except: pass
        for sel in ["text=Delivery", "a:has-text('Delivery')"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2500): el.click(); time.sleep(3); break
            except: pass
        time.sleep(8)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    return cookies, qp, zone_id


# ── API helpers ────────────────────────────────────────────────────────────
def gql(op, variables, session):
    params = {
        "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES[op]}}, separators=(",", ":")),
    }
    r = session.get(BASE_GQL, params={**params}, headers={**BASE_HEADERS, "x-page-view-id": str(uuid.uuid4())}, timeout=12)
    if r.status_code != 200: return {}
    d = r.json()
    return {} if "errors" in d else (d.get("data") or {})


def get_shop_id(postal, lat, lon, session):
    d = gql("DefaultShop", {
        "postalCode": postal,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
    }, session)
    return (d.get("defaultShop") or {}).get("id", "")


def price_item(item, shop_id, zone_id, postal, session):
    d = gql("SearchResultsPlacements", {
        "action": None, "query": item, "pageViewId": str(uuid.uuid4()),
        "elevatedProductId": None, "searchSource": "search", "filters": [],
        "disableReformulation": False, "disableLlm": False, "forceInspiration": False,
        "orderBy": "bestMatch", "clusterId": None, "includeDebugInfo": False,
        "clusteringStrategy": None, "contentManagementSearchParams": {"itemGridColumnCount": 6},
        "shopId": shop_id, "postalCode": postal, "zoneId": zone_id, "first": 20,
    }, session)
    ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', json.dumps(d))))[:20]
    if not ids: return None

    d2 = gql("Items", {"ids": ids, "shopId": shop_id, "zoneId": zone_id, "postalCode": postal}, session)
    products = d2.get("items") or []

    query_words = set(item.lower().split())
    best = None
    for prod in products:
        name = prod.get("name") or ""
        price_sec = ((prod.get("price") or {}).get("viewSection")) or {}
        price_str = price_sec.get("priceValueString")
        if not price_str: continue
        try:
            price = float(re.sub(r"[^\d.]", "", str(price_str)))
            if not (0.01 <= price <= 300): continue
        except: continue
        unit = ""
        try: unit = price_sec["itemDetails"]["pricePerUnitString"] or ""
        except: pass
        unit = unit or prod.get("size", "each")
        name_words = set(name.lower().split())
        rel = sum(1 for qw in query_words if any(qw in nw or nw in qw for nw in name_words))
        if best is None or rel > best[2] or (rel == best[2] and price < best[0]):
            best = (price, unit, rel, name)
    if best and best[2] > 0:
        return {"price": best[0], "unit": best[1], "name": best[3]}
    return None


# ── Main ───────────────────────────────────────────────────────────────────
print("=" * 70)
print(f"ALDI National Price Comparison — {len(TEST_ITEMS)} items × {len(CITIES)} cities")
print("=" * 70)

print("\n[1] Bootstrapping session...")
t0 = time.time()
cookies, qp, zone_id = bootstrap()
print(f"    {time.time()-t0:.1f}s | zoneId={zone_id!r}")

session = requests.Session()
session.cookies.update(cookies)
if qp: session.headers.update({"x-ic-qp": qp})

# Get shopId for each city
print("\n[2] Finding ALDI stores...")
city_shops = {}
for city, (postal, lat, lon) in CITIES.items():
    sid = get_shop_id(postal, lat, lon, session)
    city_shops[city] = (sid, postal)
    print(f"    {city:<18} shopId={sid}")

# Price all items × all cities in parallel
print(f"\n[3] Pricing {len(TEST_ITEMS)} items × {len(CITIES)} cities in parallel...")
t1 = time.time()
results = {city: {} for city in CITIES}

tasks = []
for city, (shop_id, postal) in city_shops.items():
    for item in TEST_ITEMS:
        tasks.append((city, item, shop_id, zone_id, postal))

with ThreadPoolExecutor(max_workers=20) as pool:
    futures = {
        pool.submit(price_item, item, shop_id, zone_id, postal, session): (city, item)
        for city, item, shop_id, zone_id, postal in tasks
    }
    for fut in as_completed(futures):
        city, item = futures[fut]
        results[city][item] = fut.result()

print(f"    Done in {time.time()-t1:.1f}s")

# ── Print comparison table ─────────────────────────────────────────────────
print(f"\n{'='*70}")
print("PRICE COMPARISON TABLE ($ per item)")
print(f"{'='*70}")

city_names = list(CITIES.keys())
col_w = 12
header = f"{'Item':<22}" + "".join(f"{c[:10]:>{col_w}}" for c in city_names) + f"{'Range':>{col_w}}"
print(header)
print("-" * len(header))

for item in TEST_ITEMS:
    prices = {}
    for city in city_names:
        r = results[city].get(item)
        if r:
            prices[city] = r["price"]

    row = f"{item:<22}"
    for city in city_names:
        p = prices.get(city)
        row += f"{'$'+f'{p:.2f}':>{col_w}}" if p else f"{'N/A':>{col_w}}"

    if len(prices) >= 2:
        lo, hi = min(prices.values()), max(prices.values())
        diff = hi - lo
        pct  = (diff / lo * 100) if lo > 0 else 0
        row += f"  {'+'+f'${diff:.2f}':>7} ({pct:.0f}%)"
    print(row)

print()
print("Matched products per city:")
for city in city_names:
    matched = sum(1 for v in results[city].values() if v)
    print(f"  {city:<18} {matched}/{len(TEST_ITEMS)}")
