"""
Coupon/flyer scraper for Flipp API. Can be used as a module or CLI.

Module usage:
    from coupon_scraper import fetch_and_store
    fetch_and_store("46201")

CLI usage:
    python coupon_scraper.py
"""
import os
import sys
import random
import time

import requests

from matcher import extract_keywords

FLYERS = 'https://flyers-ng.flippback.com/api/flipp/data?locale=en&postal_code={}&sid={}'
FLYER_ITEMS = 'https://flyers-ng.flippback.com/api/flipp/flyers/{}/flyer_items?locale=en&sid={}'
GROCERY_STORES = {'Walmart', 'ALDI', 'Costco', 'Target', 'Kroger', 'Fresh Thyme Market', 'Meijer', 'Giant Eagle'}

# Per-request socket timeout. Without this, `requests.get` blocks forever on a
# stalled connection — and this runs synchronously on the plan path, AFTER the
# pricing budget, so one hung Flipp call held the whole request open until the
# client's 3-minute abort.
_HTTP_TIMEOUT = float(os.environ.get("COUPON_HTTP_TIMEOUT", "8"))
# Wall-clock ceiling for a whole fetch_coupons() sweep. A postal code can map to
# many flyers, each needing its own items call; coupons are a nice-to-have
# overlay and must never dominate a plan request.
_FETCH_BUDGET = float(os.environ.get("COUPON_FETCH_BUDGET", "20"))


def generate_sid() -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(16))


def get_flyers_by_postal_code(postal_code: str) -> dict:
    sid = generate_sid()
    resp = requests.get(FLYERS.format(postal_code, sid), timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_grocery_flyer_ids(postal_code: str) -> list[dict]:
    """Return flyer id + merchant for grocery store flyers in the given postal code."""
    data = get_flyers_by_postal_code(postal_code)
    if 'flyers' not in data:
        return []

    results = []
    for flyer in data['flyers']:
        merchant = flyer.get('merchant', '').strip()
        categories = flyer.get('categories', [])
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(',')]
        if merchant in GROCERY_STORES and 'Groceries' in categories:
            results.append({'id': flyer['id'], 'merchant': merchant})
    return results


def get_flyer_items(flyer_id: int) -> list[dict]:
    sid = generate_sid()
    resp = requests.get(FLYER_ITEMS.format(flyer_id, sid), timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_coupons(postal_code: str) -> list[dict]:
    """Fetch all grocery flyer items for a postal code and return as structured
    coupons list.

    Bounded by _FETCH_BUDGET: whatever was collected when the budget runs out is
    returned as a partial result. One slow or broken flyer must not stall the
    plan request that called us.
    """
    deadline = time.monotonic() + _FETCH_BUDGET
    try:
        flyers = get_grocery_flyer_ids(postal_code)
    except Exception as e:
        print(f"[Coupon] Flyer list fetch failed ({repr(e)[:80]}).", flush=True)
        return []
    if not flyers:
        return []

    coupons = []
    for flyer in flyers:
        if time.monotonic() >= deadline:
            print(f"[Coupon] {_FETCH_BUDGET:.0f}s budget elapsed — using "
                  f"{len(coupons)} coupon(s) from the flyers fetched so far.", flush=True)
            break
        try:
            items = get_flyer_items(flyer['id'])
        except Exception as e:
            print(f"[Coupon] Flyer {flyer['id']} items failed ({repr(e)[:60]}).", flush=True)
            continue
        for item in items:
            name = item.get('name', '').strip()
            if not name:
                continue
            price = item.get('price')
            try:
                price = float(price) if price else 0.0
            except (ValueError, TypeError):
                price = 0.0
            keywords = list(extract_keywords(name))
            coupons.append({
                "merchant": flyer['merchant'].lower().strip(),
                "item_name": name,
                "price": price,
                "qty": 1,
                "brand": "",
                "description": item.get('name', ''),
                "image_url": "",
                "valid_from": item.get('valid_from', ''),
                "valid_to": item.get('valid_to', ''),
                "keywords": keywords,
            })
    return coupons


def fetch_and_store(postal_code: str) -> int:
    """Fetch coupons for a postal code and upsert into Supabase.
    Returns count of coupons stored.
    """
    from db import db
    coupons = fetch_coupons(postal_code)
    if not coupons:
        return 0
    return db.batch_upsert_coupons(postal_code, coupons)


def main():
    while True:
        postal_code = input('Enter your US zip code (5 digits): ').strip()
        if len(postal_code) == 5 and postal_code.isdigit():
            break
        print('Invalid zip code.')
    count = fetch_and_store(postal_code)
    print(f'Stored {count} coupons for zip {postal_code}.')


if __name__ == '__main__':
    main()
