"""
One-off diagnostic: replay an ALREADY-MINTED Target cookie (passed in via the
COOKIE_JSON env var) from wherever this script runs, with no re-mint. Used to
test whether a cookie minted on one machine/network still works when replayed
from a different one (e.g. minted on a home laptop, replayed from a GitHub
Actions runner's IP).

Deliberately standalone (no `import target_pricing`) so it only needs
curl_cffi, not the full backend dependency set -- this keeps the workflow
fast and avoids installing Playwright/CloakBrowser for a job that never
launches a browser.

Env:
    COOKIE_JSON   required. The "cookies" object from a saved session file
                  (backend/target_pricing.py's _warm_http_session() output),
                  e.g. {"_px3": "...", "pxcts": "...", ...}.
    UA            optional user-agent string (defaults to a recent Chrome UA).
    TERM          optional search term (default "milk"). Ignored if ITEM_COUNT > 1.
    STORE_ID      optional Target store id (default 1771).
    ITEM_COUNT    optional (default 1). If > 1, fires that many CONCURRENT
                  requests (one per grocery term, cycling the built-in list if
                  ITEM_COUNT exceeds it) against this one cookie instead of a
                  single request -- same shape as real basket-pricing volume.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests as ccffi

_GROCERY_TERMS = [
    "milk", "eggs", "bread", "butter", "cheese", "yogurt", "rice", "pasta",
    "tomatoes", "onions", "potatoes", "apples", "coffee", "cereal", "bananas",
    "chicken breast", "ground beef", "spinach", "carrots", "lettuce", "bacon",
    "salmon", "olive oil", "flour", "sugar", "salt", "pepper", "garlic",
    "broccoli", "cucumber", "bell pepper", "avocado", "orange juice",
    "tortillas", "beans", "lentils", "oats", "honey", "peanut butter",
    "jelly", "ketchup", "mustard", "mayonnaise", "soy sauce", "hot sauce",
    "vinegar", "chicken thighs", "pork chops", "ground turkey", "shrimp",
    "tuna", "sour cream", "cream cheese", "cottage cheese", "mozzarella",
    "cheddar", "parmesan", "ice cream", "frozen pizza", "frozen vegetables",
    "frozen fruit", "tofu", "almond milk", "oat milk", "orange", "lemon",
    "lime", "grapes", "strawberries", "blueberries", "watermelon",
    "pineapple", "mango", "celery", "zucchini", "sweet potato", "corn",
    "peas", "mushrooms", "cabbage", "cauliflower", "kale", "asparagus",
    "green beans", "crackers", "chips", "pretzels", "popcorn",
    "granola bars", "trail mix", "almonds", "walnuts", "peanuts", "cashews",
    "raisins", "chocolate chips", "baking soda", "baking powder",
    "vanilla extract", "cinnamon", "paprika", "cumin", "oregano", "basil",
]

_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
_SLP_URL = "https://cdui-orchestrations.target.com/cdui_orchestrations/v1/pages/slp"
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def _slp_url(term: str, store_id: str) -> str:
    from urllib.parse import quote
    q = quote(term)
    page = f"/s/{q}"
    return (f"{_SLP_URL}?key={_KEY}&platform=WEB&sapphire_channel=WEB"
            f"&sapphire_page={page}&channel=WEB&page={page}"
            f"&visitor_id={uuid.uuid4().hex.upper()}"
            f"&store_id={store_id}&store_ids={store_id}"
            f"&scheduled_delivery_store_id={store_id}"
            f"&count=8&offset=0&new_search=true&keyword={q}"
            f"&include_data_source_modules=true&default_purchasability_filter=true"
            f"&spellcheck=true&is_seo_bot=false&device_type=desktop"
            f"&targeted_advertising_opt_out=false&privacy_do_not_sell=false"
            f"&query_string=searchTerm%3D{q}")


def _extract_products(text: str) -> list:
    try:
        data = json.loads(text)
    except Exception:
        return []
    for mod in data.get("data_source_modules") or []:
        products = ((mod.get("module_data") or {}).get("search_response") or {}).get("products")
        if products:
            return products
    return []


def main() -> int:
    raw = os.environ.get("COOKIE_JSON", "")
    if not raw:
        print("COOKIE_JSON env var is required (paste the saved cookie's "
              "'cookies' object).", flush=True)
        return 1
    try:
        cookies = json.loads(raw)
    except Exception as e:
        print(f"COOKIE_JSON is not valid JSON: {repr(e)[:150]}", flush=True)
        return 1

    ua = os.environ.get("UA") or _DEFAULT_UA
    term = os.environ.get("TERM") or "milk"
    store_id = os.environ.get("STORE_ID") or "1771"
    item_count = int(os.environ.get("ITEM_COUNT") or "1")

    if item_count > 1:
        return _run_batch(cookies, ua, store_id, item_count)
    return _run_single(cookies, ua, term, store_id)


def _hit(term: str, store_id: str, cookies: dict, ua: str) -> tuple[str, bool, str, float]:
    t0 = time.time()
    url = _slp_url(term, store_id)
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.target.com",
        "referer": f"https://www.target.com/s?searchTerm={term}",
        "user-agent": ua,
    }
    try:
        resp = ccffi.get(url, headers=headers, cookies=cookies,
                          impersonate="chrome", timeout=30)
    except Exception as e:
        return term, False, f"transport error: {repr(e)[:100]}", time.time() - t0
    if resp.status_code == 403 or '"captchaRelativeURL"' in resp.text:
        return term, False, f"BLOCKED status={resp.status_code}", time.time() - t0
    if resp.status_code != 200:
        return term, False, f"unexpected status {resp.status_code}", time.time() - t0
    products = _extract_products(resp.text)
    if products:
        return term, True, f"{len(products)} products", time.time() - t0
    return term, False, "200 OK but no products", time.time() - t0


def _run_batch(cookies: dict, ua: str, store_id: str, item_count: int) -> int:
    terms = [_GROCERY_TERMS[i % len(_GROCERY_TERMS)] for i in range(item_count)]
    print(f"Replaying saved cookie ({len(cookies)} entries) from THIS runner's IP "
          f"-- {item_count} CONCURRENT requests, store={store_id}\n", flush=True)

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futs = {pool.submit(_hit, t, store_id, cookies, ua): t for t in terms}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            if not r[1]:
                print(f"  FAIL {r[0]}: {r[2]} ({r[3]:.2f}s)", flush=True)
    elapsed = time.time() - t0

    ok = sum(1 for r in results if r[1])
    half = len(results) // 2
    first_half_ok = sum(1 for r in results[:half] if r[1])
    second_half_ok = sum(1 for r in results[half:] if r[1])

    print(f"\nRESULT: {ok}/{len(results)} succeeded in {elapsed:.1f}s "
          f"(first half completed: {first_half_ok}/{half}, "
          f"second half: {second_half_ok}/{len(results) - half})", flush=True)
    return 0 if ok == len(results) else 1


def _run_single(cookies: dict, ua: str, term: str, store_id: str) -> int:
    print(f"Replaying saved cookie ({len(cookies)} entries) from THIS runner's IP "
          f"-- term={term!r}, store={store_id}", flush=True)
    _, ok, detail, elapsed = _hit(term, store_id, cookies, ua)
    if ok:
        print(f"RESULT: SUCCESS -- {detail} ({elapsed:.2f}s)", flush=True)
        return 0
    print(f"RESULT: {detail} ({elapsed:.2f}s)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
