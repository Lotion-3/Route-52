"""
Quick test of Kroger API - auth, location lookup, and product price fetch.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv("config.env")

CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
BASE_URL = "https://api-ce.kroger.com/v1"


def get_token():
    resp = requests.post(
        f"{BASE_URL}/connect/oauth2/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials", "scope": "product.compact"},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print(f"Token: {token[:30]}...")
    return token


def find_stores(token, zip_code="60601", limit=3):
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter.zipCode.near": zip_code, "filter.limit": limit}
    resp = requests.get(f"{BASE_URL}/locations", headers=headers, params=params)
    resp.raise_for_status()
    stores = resp.json().get("data", [])
    print(f"\nStores near {zip_code}:")
    for s in stores:
        print(f"  {s['name']} — {s['address']['addressLine1']}, {s['address']['city']} — ID: {s['locationId']}")
    return stores


def search_product(token, location_id, term):
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "filter.term": term,
        "filter.locationId": location_id,
        "filter.limit": 3,
    }
    resp = requests.get(f"{BASE_URL}/products", headers=headers, params=params)
    resp.raise_for_status()
    products = resp.json().get("data", [])
    print(f"\n  '{term}':")
    for p in products:
        price_info = p.get("items", [{}])[0]
        price = price_info.get("price", {})
        regular = price.get("regular")
        promo = price.get("promo")
        size = price_info.get("size", "")
        print(f"    {p['description'][:50]:<50} ${regular or '?':>6}  promo=${promo or '-'}  {size}")
    return products


if __name__ == "__main__":
    token = get_token()
    stores = find_stores(token, zip_code="60601")

    if stores:
        loc_id = stores[0]["locationId"]
        print(f"\nFetching prices at: {stores[0]['name']} (ID: {loc_id})")
        for item in ["chicken breast", "spinach", "eggs", "whole milk", "bananas", "ground beef"]:
            search_product(token, loc_id, item)
