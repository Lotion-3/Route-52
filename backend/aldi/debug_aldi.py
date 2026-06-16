"""Quick ALDI diagnostic — run from backend/aldi/ to see shopId and sample prices."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from aldi_pricing import _bootstrap, _save_disk_session, _SESSION_CACHE
import requests, uuid, json, re
from pathlib import Path

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
}

# --- Bootstrap ---
print("Bootstrapping session...")
cookies, qp, zone_id, _ = _bootstrap()
print(f"  cookies: {len(cookies)}, qp: {qp[:8]}..., zone_id: {zone_id}")

session = requests.Session()
session.cookies.update(cookies)
session.headers.update({**BASE_HEADERS, "x-ic-qp": qp})

# --- DefaultShop ---
# Use the ALDI store's own coordinates (from Overpass), not the user's home.
# The store at shopId 749517 is near Westfield IN — adjust if testing elsewhere.
LAT, LON = 40.0033, -86.1366
postal = "46074"

print(f"\nCalling DefaultShop with lat={LAT}, lon={LON}, postal={postal}...")
params = {
    "operationName": "DefaultShop",
    "variables": json.dumps({"postalCode": postal, "coordinates": {"latitude": LAT, "longitude": LON}, "addressId": None}, separators=(",",":")),
    "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES["DefaultShop"]}}, separators=(",",":")),
}
r = session.get(BASE_GQL, params=params, headers={**BASE_HEADERS, "x-ic-qp": qp, "x-page-view-id": str(uuid.uuid4())}, timeout=12)
print(f"  HTTP {r.status_code}")
data = r.json()
shop = (data.get("data") or {}).get("defaultShop") or {}
shop_id = shop.get("id", "")
print(f"  DefaultShop.id = {shop_id!r}")
print(f"  DefaultShop.name = {shop.get('name')!r}")
print(f"  DefaultShop.zoneId = {shop.get('zoneId')!r}")
print(f"  DefaultShop.address = {shop.get('address')}")
print(f"\n  >>> Your browser uses shopId '749517'. We got: {shop_id!r} <<<")
if shop_id != "749517":
    print("  !! MISMATCH — this is why prices differ")

# --- Sample search ---
print("\nSearching for 'chicken breast'...")
params2 = {
    "operationName": "SearchResultsPlacements",
    "variables": json.dumps({
        "action": None, "query": "chicken breast", "pageViewId": str(uuid.uuid4()),
        "elevatedProductId": None, "searchSource": "search", "filters": [],
        "disableReformulation": False, "disableLlm": False, "forceInspiration": False,
        "orderBy": "bestMatch", "clusterId": None, "includeDebugInfo": False,
        "clusteringStrategy": None, "contentManagementSearchParams": {"itemGridColumnCount": 6},
        "shopId": shop_id, "postalCode": postal, "zoneId": zone_id, "first": 5,
    }, separators=(",",":")),
    "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES["SearchResultsPlacements"]}}, separators=(",",":")),
}
r2 = session.get(BASE_GQL, params=params2, headers={**BASE_HEADERS, "x-ic-qp": qp, "x-page-view-id": str(uuid.uuid4())}, timeout=12)
print(f"  HTTP {r2.status_code}")
d2 = r2.json()
ids = list(dict.fromkeys(re.findall(r'items_\d+-\d+', json.dumps(d2))))[:5]
print(f"  Product IDs found: {ids}")

if ids:
    params3 = {
        "operationName": "Items",
        "variables": json.dumps({"ids": ids, "shopId": shop_id, "zoneId": zone_id, "postalCode": postal}, separators=(",",":")),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES["Items"]}}, separators=(",",":")),
    }
    r3 = session.get(BASE_GQL, params=params3, headers={**BASE_HEADERS, "x-ic-qp": qp, "x-page-view-id": str(uuid.uuid4())}, timeout=12)
    items = (r3.json().get("data") or {}).get("items") or []
    print(f"\n  Products returned ({len(items)}):")
    for it in items:
        price_sec = ((it.get("price") or {}).get("viewSection")) or {}
        print(f"    {it.get('name')!r:50s}  size={it.get('size')!r}")
        print(f"      priceValueString={price_sec.get('priceValueString')!r}  fullPriceString={price_sec.get('fullPriceString')!r}")
        print(f"      raw price block: {it.get('price')}")
