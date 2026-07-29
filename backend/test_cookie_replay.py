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
    TERM          optional search term (default "milk").
    STORE_ID      optional Target store id (default 1771).
"""
from __future__ import annotations

import json
import os
import sys
import uuid

from curl_cffi import requests as ccffi

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

    print(f"Replaying saved cookie ({len(cookies)} entries) from THIS runner's IP "
          f"-- term={term!r}, store={store_id}", flush=True)

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
        print(f"RESULT: TRANSPORT ERROR -- {repr(e)[:200]}", flush=True)
        return 1

    if resp.status_code == 403 or '"captchaRelativeURL"' in resp.text:
        print(f"RESULT: BLOCKED (403/captcha) -- status={resp.status_code}", flush=True)
        print(resp.text[:300], flush=True)
        return 1
    if resp.status_code != 200:
        print(f"RESULT: UNEXPECTED STATUS {resp.status_code}", flush=True)
        print(resp.text[:300], flush=True)
        return 1

    products = _extract_products(resp.text)
    if products:
        print(f"RESULT: SUCCESS -- {len(products)} products returned", flush=True)
        for p in products[:3]:
            title = ((p.get("item") or {}).get("product_description") or {}).get("title", "?")
            price = (p.get("price") or {}).get("formatted_current_price", "?")
            print(f"  - {title} ({price})", flush=True)
        return 0
    else:
        print("RESULT: 200 OK but no products found (weak/expired cookie?)", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
