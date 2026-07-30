"""
Diagnostic: disentangle WHAT actually blocks a Walmart PerimeterX cookie
under load. The existing test_walmart_cookie_replay.py hardcodes
ThreadPoolExecutor(max_workers=20), so its "item_count" and "concurrency"
are conflated -- item_count=31 is NOT a 31-wide burst, it's a 20-wide burst
with 11 items queued behind it. This script makes item count, concurrency
width, and multi-wave pacing independently configurable, so a single cookie
can be tested against a precisely-shaped load instead of an ambiguous one.

Deliberately standalone (no `import walmart_pricing`), same reasoning as
test_walmart_cookie_replay.py -- curl_cffi only.

Usage (as a library, for a scripted multi-trial matrix):
    from test_walmart_concurrency_matrix import run_trial
    result = run_trial(cookies, ua, item_count=30, concurrency=30)
    result = run_trial(cookies, ua, item_count=20, concurrency=20,
                        waves=2, wave_gap=12.0)

Usage (standalone CLI, single trial):
    COOKIE_INDEX=3 ITEM_COUNT=30 CONCURRENCY=30 python test_walmart_concurrency_matrix.py
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
    "carrots", "lettuce", "salmon", "olive oil", "flour", "sugar",
    "pepper", "cucumber", "bell pepper", "tortilla chips", "salsa",
    "shrimp", "tuna", "sour cream", "cream cheese", "mozzarella",
    "cheddar", "ice cream", "frozen vegetables", "almond milk",
]

_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40"
_WARM_URL = "https://www.walmart.com/"
_COOKIE_FILE = Path(__file__).parent / ".minted_walmart_cookies.json"
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')
_EXPLICIT_BLOCK_MARKERS = ("px-captcha",)


def _has_explicit_block_marker(text: str) -> bool:
    return any(m in text.lower() for m in _EXPLICIT_BLOCK_MARKERS)


def _find_items(o) -> list:
    if isinstance(o, dict):
        if isinstance(o.get("itemStacks"), list):
            items: list = []
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


def _hit(term: str, cookies: dict, ua: str) -> dict:
    t0 = time.monotonic()
    url = _SEARCH_URL.format(q=quote_plus(term))
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": _WARM_URL,
        "user-agent": ua,
    }
    try:
        resp = ccffi.get(url, headers=headers, cookies=cookies, impersonate="chrome", timeout=30)
    except Exception as e:
        return {"term": term, "ok": False, "detail": f"transport error: {repr(e)[:100]}",
                "elapsed": time.monotonic() - t0}

    elapsed = time.monotonic() - t0
    if _has_explicit_block_marker(resp.text):
        return {"term": term, "ok": False, "detail": f"BLOCKED (px-captcha) status={resp.status_code}",
                "elapsed": elapsed}
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return {"term": term, "ok": False, "detail": f"BLOCKED (no __NEXT_DATA__) status={resp.status_code}",
                "elapsed": elapsed}
    try:
        items = _find_items(json.loads(m.group(1)))
    except Exception:
        items = []
    if items:
        return {"term": term, "ok": True, "detail": f"{len(items)} products", "elapsed": elapsed}
    return {"term": term, "ok": False, "detail": f"no products (status={resp.status_code})",
            "elapsed": elapsed}


def _run_burst(terms: list[str], cookies: dict, ua: str, concurrency: int) -> list[dict]:
    """Fire `terms` at true `concurrency` width (max_workers == concurrency,
    not capped below it) and tag each result with submission order so the
    caller can see whether failures cluster in a "queued tail"."""
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(_hit, t, cookies, ua): i for i, t in enumerate(terms)}
        for fut in as_completed(futs):
            r = fut.result()
            r["submit_order"] = futs[fut]
            results.append(r)
    results.sort(key=lambda r: r["submit_order"])
    return results


def run_trial(cookies: dict, ua: str, item_count: int, concurrency: int,
              waves: int = 1, wave_gap: float = 0.0, label: str = "") -> dict:
    """Run one trial: `waves` separate bursts of `item_count` items each at
    `concurrency` width, with `wave_gap` seconds between waves. Returns a
    dict with per-wave results and an overall verdict."""
    print(f"\n{'=' * 70}", flush=True)
    print(f"TRIAL{f' [{label}]' if label else ''}: item_count={item_count} "
          f"concurrency={concurrency} waves={waves} wave_gap={wave_gap}s", flush=True)
    print(f"{'=' * 70}", flush=True)

    all_waves = []
    for w in range(waves):
        if w > 0:
            print(f"  ...waiting {wave_gap}s before wave {w + 1}...", flush=True)
            time.sleep(wave_gap)
        terms = [_GROCERY_TERMS[(w * item_count + i) % len(_GROCERY_TERMS)] for i in range(item_count)]
        t0 = time.time()
        results = _run_burst(terms, cookies, ua, concurrency)
        elapsed = time.time() - t0
        ok = sum(1 for r in results if r["ok"])
        fails = [r for r in results if not r["ok"]]
        first_fail_order = min((r["submit_order"] for r in fails), default=None)
        print(f"  Wave {w + 1}/{waves}: {ok}/{len(results)} succeeded in {elapsed:.1f}s"
              f"{f', first failure at submit_order={first_fail_order}' if fails else ''}",
              flush=True)
        for r in fails[:10]:
            print(f"    FAIL [order={r['submit_order']:3d}] {r['term']}: {r['detail']} "
                  f"({r['elapsed']:.2f}s)", flush=True)
        if len(fails) > 10:
            print(f"    ...and {len(fails) - 10} more failures", flush=True)
        all_waves.append({"ok": ok, "total": len(results), "elapsed": elapsed,
                           "first_fail_order": first_fail_order, "results": results})

    return {"item_count": item_count, "concurrency": concurrency, "waves": all_waves}


def _load_cookie(index_1based: int) -> tuple[dict, str, str]:
    sessions = json.loads(_COOKIE_FILE.read_text())
    s = sessions[index_1based - 1]
    return s["cookies"], s.get("ua") or _DEFAULT_UA, s.get("saved_at_iso", "?")


if __name__ == "__main__":
    idx = int(os.environ.get("COOKIE_INDEX") or str(len(json.loads(_COOKIE_FILE.read_text()))))
    item_count = int(os.environ.get("ITEM_COUNT") or "20")
    concurrency = int(os.environ.get("CONCURRENCY") or str(item_count))
    waves = int(os.environ.get("WAVES") or "1")
    wave_gap = float(os.environ.get("WAVE_GAP") or "10.0")

    cookies, ua, saved_at = _load_cookie(idx)
    print(f"Using cookie #{idx} (saved {saved_at}, {len(cookies)} cookies)", flush=True)
    run_trial(cookies, ua, item_count, concurrency, waves, wave_gap)
