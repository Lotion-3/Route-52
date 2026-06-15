"""
Test direct HTTP calls to ALDI's GraphQL API (no browser needed).
"""
import json
import uuid
import urllib.parse
import requests

BASE = "https://www.aldi.us/graphql"
HASHES = {
    "DefaultShop":             "d389a8d33d63801f1ce5c4929fb181dd10c57b49c3a2dcb6a6baa44212e8e069",
    "ShopCollectionScoped":    "f20693c3c551f0e0fbdcac9b2ca7aa6db50f9224a39967ba5ac767bb2b598f85",
    "SearchResultsPlacements": "387535ff634b5f783192dc1464d1253e514ff092876a1747486d90d83beb4dfd",
    "Items":                   "0362f9eaea7f55c17c95266a64f8c37a10b55d265318f85c761c59c382d96074",
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US",
    "content-type": "application/json",
    "x-client-identifier": "web",
    "x-ic-view-layer": "true",
    "x-page-view-id": str(uuid.uuid4()),
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "referer": "https://www.aldi.us/store/aldi/s?query=bananas",
}


def gql(operation: str, variables: dict) -> dict:
    params = {
        "operationName": operation,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({
            "persistedQuery": {"version": 1, "sha256Hash": HASHES[operation]}
        }, separators=(",", ":")),
    }
    r = requests.get(BASE, params=params, headers=HEADERS, timeout=15)
    print(f"  [{operation}] {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:300]}")
        return {}
    return r.json()


# --- Step 1: Find nearest ALDI shop for Houston TX ---
print("=== Step 1: DefaultShop (Houston 77003) ===")
resp = gql("DefaultShop", {
    "postalCode": "77003",
    "coordinates": {"latitude": 29.7515, "longitude": -95.3615},
    "addressId": None,
})
shop_data = resp.get("data", {}).get("defaultShop") or {}
print(f"  shop_data keys: {list(shop_data.keys())}")
print(f"  raw: {json.dumps(shop_data)[:400]}")

shop_id = shop_data.get("id")
postal = "77003"
zone_id = None

# Get zone info from shop_data
print(f"  shopId={shop_id}")
print(f"  full shop_data: {json.dumps(shop_data, indent=2)[:800]}")

print()
print("=== Step 2: SearchResultsPlacements (Houston, 'bananas') ===")
resp3 = gql("SearchResultsPlacements", {
    "action": None,
    "query": "bananas",
    "pageViewId": str(uuid.uuid4()),
    "elevatedProductId": None,
    "searchSource": "search",
    "filters": [],
    "disableReformulation": False,
    "disableLlm": False,
    "forceInspiration": False,
    "orderBy": "bestMatch",
    "clusterId": None,
    "includeDebugInfo": False,
    "clusteringStrategy": None,
    "contentManagementSearchParams": {"itemGridColumnCount": 6},
    "shopId": shop_id,
    "postalCode": postal,
    "zoneId": zone_id,
    "first": 20,
})
print(f"  data keys: {list((resp3.get('data') or {}).keys())}")
# Try to find item IDs in the response
raw = json.dumps(resp3)
# Look for item ID patterns
import re
item_ids = list(set(re.findall(r'items_\d+-\d+', raw)))
print(f"  Item IDs found: {item_ids[:10]}")
with open("aldi_search_response.json", "w") as f:
    json.dump(resp3, f, indent=2)
print("  Saved to aldi_search_response.json")
