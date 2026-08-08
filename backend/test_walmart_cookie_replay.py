"""
One-off diagnostic: replay an ALREADY-MINTED Walmart PerimeterX cookie from
`.walmart_http_session.json` (or a COOKIE_JSON env var) with no re-mint.
Tests whether a cookie minted on one machine/network still works when replayed
from a different IP (e.g. minted on a home laptop, replayed from GitHub Actions).

Deliberately standalone (no `import walmart_pricing`) so it only needs curl_cffi,
not the full backend dependency set -- keeps CI fast and avoids installing
Playwright/CloakBrowser for a job that never launches a browser.

Cookie source (checked in order):
  1. COOKIE_JSON env var  -- explicit override
  2. backend/.walmart_http_session.json  -- auto-detect (walmart_pricing.py's
     persisted session). The `ua` field is also read from this file if UA env
     var is not set.

Env:
    COOKIE_JSON   optional. The "cookies" dict from a saved Walmart session.
                  If unset, reads from backend/.walmart_http_session.json.
    UA            optional user-agent string -- should match the cookie's own
                  UA if known (a mismatch between the header and curl_cffi's
                  JA3 impersonation profile is a plausible, unconfirmed risk).
                  Defaults to the session file's ua, else a generic Chrome UA.
    TERM          optional search term (default "milk"). Ignored if ITEM_COUNT > 1.
    ITEM_COUNT    optional (default 1). If > 1, fires that many requests
                  cycling the built-in grocery list -- same shape as real
                  basket-pricing volume against this one cookie.
    CONCURRENCY   optional (default: min(ITEM_COUNT, 20), the confirmed-safe
                  concurrency wall -- see test_walmart_concurrency_matrix.py).
                  How many of those ITEM_COUNT requests fire simultaneously.
                  Previously hardcoded to 20 regardless of ITEM_COUNT, which
                  conflated "item count" with "concurrency" -- e.g. an
                  ITEM_COUNT=31 run was never actually a 31-wide burst, just
                  20 concurrent with 11 queued behind it. Set this explicitly
                  (e.g. equal to ITEM_COUNT) if you deliberately want a true
                  N-wide burst, including past the wall.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote_plus

from curl_cffi import requests as ccffi

_GROCERY_TERMS = [
    "milk", "eggs", "bread", "bananas", "chicken breast", "butter",
    "cheese", "rice", "coffee", "apples", "yogurt", "ground beef",
    "spinach", "pasta", "tomatoes", "onions", "potatoes", "garlic",
    "broccoli", "avocado", "strawberries", "sweet potato", "bacon",
    "cereal", "orange juice", "peanut butter", "frozen pizza",
    "tortillas", "black beans", "italian sausage", "grapes",
]

_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40"
_SESSION_FILE = Path(__file__).parent / ".walmart_http_session.json"
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")
_WARM_URL = "https://www.walmart.com/"

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')
_EXPLICIT_BLOCK_MARKERS = ("px-captcha",)


def _has_explicit_block_marker(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _EXPLICIT_BLOCK_MARKERS)


def _find_items(o) -> list[dict]:
    """Walk __NEXT_DATA__ to the search itemStacks[].items[] list."""
    if isinstance(o, dict):
        if isinstance(o.get("itemStacks"), list):
            items: list[dict] = []
            for st in o["itemStacks"]:
                if isinstance(st, dict) and st.get("items"):
                    items.extend(st["items"])
            if items:
                return items
        for v in o.values():
            r = _find_items(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_items(v)
            if r:
                return r
    return []


def _hit(term: str, cookies: dict, ua: str) -> tuple[str, bool, str, float, list[dict]]:
    """Returns (term, ok, detail, elapsed, items). `items` is the raw
    __NEXT_DATA__ itemStacks items on success, [] otherwise — callers that
    only want pass/fail can ignore the 5th element."""
    t0 = time.time()
    url = _SEARCH_URL.format(q=quote_plus(term))
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": _WARM_URL,
        "user-agent": ua,
    }
    try:
        resp = ccffi.get(url, headers=headers, cookies=cookies,
                          impersonate="chrome", timeout=30)
    except Exception as e:
        return term, False, f"transport error: {repr(e)[:100]}", time.time() - t0, []

    if _has_explicit_block_marker(resp.text):
        return term, False, f"BLOCKED (px-captcha) status={resp.status_code}", time.time() - t0, []

    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return term, False, f"BLOCKED (no __NEXT_DATA__) status={resp.status_code}", time.time() - t0, []

    try:
        items = _find_items(json.loads(m.group(1)))
    except Exception:
        items = []

    if items:
        return term, True, f"{len(items)} products", time.time() - t0, items
    return term, False, f"no products (status={resp.status_code})", time.time() - t0, []


def _format_product(item: dict) -> str:
    """One-line display of a raw __NEXT_DATA__ search item:
        "$3.98  Walmart  Great Value Whole Milk, 1 gal  (id=10450112)"
    Field names mirror walmart_pricing.py's _item_to_kroger_format (name,
    brand, priceInfo.linePrice, usItemId). Tolerant of missing fields."""
    name = item.get("name") or item.get("title") or "?"
    brand = item.get("brand") or ""
    pi = item.get("priceInfo") or {}
    price = pi.get("linePrice")
    price_s = f"${price:.2f}" if isinstance(price, (int, float)) else "?"
    item_id = item.get("usItemId") or item.get("id") or ""
    id_s = f"  (id={item_id})" if item_id else ""
    brand_s = f"  {brand}" if brand else ""
    return f"{price_s:>6}{brand_s}  {name}{id_s}"


def _print_products(items: list[dict], max_show: int = 20) -> None:
    """Print up to `max_show` products, then a '... and N more' line."""
    if not items:
        return
    shown = items[:max_show]
    for it in shown:
        print(f"  {_format_product(it)}", flush=True)
    extra = len(items) - len(shown)
    if extra > 0:
        print(f"  ... and {extra} more", flush=True)


def _run_single(cookies: dict, ua: str, term: str) -> int:
    print(f"Replaying saved Walmart cookie ({len(cookies)} entries) from THIS runner's IP "
          f"-- term={term!r}", flush=True)
    _, ok, detail, elapsed, items = _hit(term, cookies, ua)
    if ok:
        print(f"RESULT: SUCCESS -- {detail} ({elapsed:.2f}s)", flush=True)
        _print_products(items)
        return 0
    print(f"RESULT: {detail} ({elapsed:.2f}s)", flush=True)
    return 1


def _run_batch(cookies: dict, ua: str, item_count: int, concurrency: int) -> int:
    terms = [_GROCERY_TERMS[i % len(_GROCERY_TERMS)] for i in range(item_count)]
    print(f"Replaying saved Walmart cookie ({len(cookies)} entries) from THIS runner's IP "
          f"-- {item_count} items @ concurrency={concurrency}\n", flush=True)

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(_hit, t, cookies, ua): t for t in terms}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            if r[1]:
                print(f"  OK   {r[0]:18} {r[2]} ({r[3]:.2f}s)", flush=True)
            else:
                print(f"  FAIL {r[0]:18} {r[2]} ({r[3]:.2f}s)", flush=True)
    elapsed = time.time() - t0

    ok = sum(1 for r in results if r[1])
    half = len(results) // 2
    first_half_ok = sum(1 for r in results[:half] if r[1])
    second_half_ok = sum(1 for r in results[half:] if r[1])

    print(f"\nRESULT: {ok}/{len(results)} succeeded in {elapsed:.1f}s "
          f"(first half completed: {first_half_ok}/{half}, "
          f"second half: {second_half_ok}/{len(results) - half})", flush=True)
    return 0 if ok == len(results) else 1


def _load_cookies_from_file() -> tuple[dict, str] | None:
    """Read cookies + ua from the persisted session file, or None."""
    if not _SESSION_FILE.exists():
        return None
    try:
        data = json.loads(_SESSION_FILE.read_text())
        cookies = data.get("cookies")
        ua = data.get("ua", "")
        if isinstance(cookies, dict) and cookies:
            return cookies, ua
    except Exception:
        pass
    return None


def main() -> int:
    raw = os.environ.get("COOKIE_JSON", "")
    if raw:
        try:
            cookies = json.loads(raw)
        except Exception as e:
            print(f"COOKIE_JSON is not valid JSON: {repr(e)[:150]}", flush=True)
            return 1
        if not isinstance(cookies, dict):
            print("COOKIE_JSON must be a JSON object (key-value pairs).", flush=True)
            return 1
        print(f"Loaded cookie from COOKIE_JSON env var ({len(cookies)} entries).", flush=True)
        file_ua = None
    else:
        loaded = _load_cookies_from_file()
        if loaded is None:
            print("No cookie source found. Set COOKIE_JSON env var or run "
                  "walmart_pricing.py first to create "
                  f"{_SESSION_FILE}.", flush=True)
            return 1
        cookies, file_ua = loaded
        print(f"Loaded cookie from {_SESSION_FILE.name} ({len(cookies)} entries).", flush=True)

    if "_px3" not in cookies:
        print(f"Warning: no '_px3' cookie found — likely not a valid PerimeterX "
              f"session ({len(cookies)} cookie(s) present).", flush=True)

    ua = os.environ.get("UA") or file_ua or _DEFAULT_UA
    term = os.environ.get("TERM") or "milk"
    item_count = int(os.environ.get("ITEM_COUNT") or "1")
    # Default preserves the old (accidentally-safe) behavior -- capped at the
    # confirmed concurrency wall regardless of item_count -- but now it's an
    # explicit, overridable choice instead of a hardcoded conflation.
    concurrency = int(os.environ.get("CONCURRENCY") or str(min(item_count, 20)))

    if item_count > 1:
        return _run_batch(cookies, ua, item_count, concurrency)
    return _run_single(cookies, ua, term)


if __name__ == "__main__":
    sys.exit(main())