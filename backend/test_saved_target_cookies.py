"""
Diagnostic: test every cookie in backend/saved_target_cookies.json against
Target's SLP API and report which ones still work.

Each cookie gets a single search ("milk", store 1771). Results are printed
per-cookie with a summary table at the end.

Usage:
    python test_saved_target_cookies.py
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

from curl_cffi import requests as ccffi

_FILE = Path(__file__).parent / "saved_target_cookies.json"
_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
_SLP_URL = "https://cdui-orchestrations.target.com/cdui_orchestrations/v1/pages/slp"
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
_STORE_ID = "1771"
_TERM = "milk"


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


def _test_cookie(cookies: dict, ua: str) -> dict:
    t0 = time.time()
    url = _slp_url(_TERM, _STORE_ID)
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.target.com",
        "referer": f"https://www.target.com/s?searchTerm={_TERM}",
        "user-agent": ua,
    }
    ok = False
    detail = ""
    try:
        resp = ccffi.get(url, headers=headers, cookies=cookies,
                          impersonate="chrome", timeout=30)
        if resp.status_code == 403 or '"captchaRelativeURL"' in resp.text:
            detail = f"BLOCKED status={resp.status_code}"
        elif resp.status_code != 200:
            detail = f"unexpected status {resp.status_code}"
        else:
            products = _extract_products(resp.text)
            if products:
                ok = True
                detail = f"{len(products)} products"
            else:
                detail = "no products"
    except Exception as e:
        detail = f"transport error: {repr(e)[:100]}"
    elapsed = time.time() - t0
    return {"ok": ok, "detail": detail, "elapsed": elapsed}


def main() -> int:
    if not _FILE.exists():
        print(f"File not found: {_FILE}", flush=True)
        return 1

    sessions = json.loads(_FILE.read_text())
    if not isinstance(sessions, list):
        print(f"Expected a JSON array, got {type(sessions).__name__}", flush=True)
        return 1

    print(f"Testing {len(sessions)} Target cookies from {_FILE.name}...\n", flush=True)

    results = []
    for i, session in enumerate(sessions):
        cookies = session.get("cookies", {})
        ua = session.get("ua", _DEFAULT_UA)
        saved = session.get("saved_at_iso", "unknown")
        n_cookies = len(cookies)
        has_px3 = "_px3" in cookies

        r = _test_cookie(cookies, ua)
        results.append(r)

        status = "OK" if r["ok"] else "FAIL"
        print(f"  [{i + 1}/5]  {status}  {r['detail']:40s}  "
              f"({r['elapsed']:.2f}s, {n_cookies} cookies, px3={has_px3}, "
              f"saved={saved})", flush=True)

    print()
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  {'=' * 60}")
    print(f"  SUMMARY:  {ok_count}/{len(results)} cookies still work")
    for i, r in enumerate(results):
        status = "OK" if r["ok"] else "FAIL"
        print(f"  Cookie #{i + 1}:  {status}  ({r['detail']})  [{r['elapsed']:.2f}s]")
    print(f"  {'=' * 60}")

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())