"""
Diagnostic: does a Walmart cookie have a cumulative "request budget" separate
from the instant 20-concurrency wall (test_walmart_concurrency_matrix.py)?
Fires many sequential/low-concurrency requests against ONE cookie, well
under the confirmed-safe concurrency ceiling, and watches for when (if ever)
failures start appearing purely from accumulated volume.

Usage:
    python test_walmart_sustained_volume.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from test_walmart_concurrency_matrix import _GROCERY_TERMS, _hit

_SESSION_FILE = os.environ.get("SESSION_FILE", ".sustained_test_session.json")
_TOTAL = int(os.environ.get("TOTAL", "200"))
_CONCURRENCY = int(os.environ.get("CONCURRENCY", "10"))  # well under the 20-wall
_PROXY = os.environ.get("PROXY", "")


def _hit_proxied(term, cookies, ua, proxy):
    from curl_cffi import requests as ccffi
    from urllib.parse import quote_plus
    t0 = time.monotonic()
    url = f"https://www.walmart.com/search?q={quote_plus(term)}&affinityOverride=default&ps=10"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://www.walmart.com/",
        "user-agent": ua,
    }
    try:
        kwargs = {"headers": headers, "cookies": cookies, "impersonate": "chrome", "timeout": 30}
        if proxy:
            kwargs["proxy"] = proxy
        resp = ccffi.get(url, **kwargs)
    except Exception as e:
        return {"ok": False, "detail": f"transport: {repr(e)[:80]}", "elapsed": time.monotonic() - t0}
    elapsed = time.monotonic() - t0
    if "px-captcha" in resp.text.lower():
        return {"ok": False, "detail": f"BLOCKED status={resp.status_code}", "elapsed": elapsed}
    if "__NEXT_DATA__" not in resp.text:
        return {"ok": False, "detail": f"no NEXT_DATA status={resp.status_code}", "elapsed": elapsed}
    return {"ok": True, "detail": "OK", "elapsed": elapsed}


def main() -> int:
    s = json.load(open(_SESSION_FILE))
    cookies, ua = s["cookies"], s["ua"]
    print(f"Sustained volume test: {_TOTAL} total requests @ concurrency={_CONCURRENCY} "
          f"(well under the 20-wall), proxy={'yes' if _PROXY else 'no'}\n", flush=True)

    terms = [_GROCERY_TERMS[i % len(_GROCERY_TERMS)] for i in range(_TOTAL)]
    results = []
    t0 = time.time()
    first_fail_at = None
    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        futs = {pool.submit(_hit_proxied, t, cookies, ua, _PROXY): i for i, t in enumerate(terms)}
        done = 0
        for fut in as_completed(futs):
            i = futs[fut]
            r = fut.result()
            r["order"] = i
            results.append(r)
            done += 1
            if not r["ok"] and first_fail_at is None:
                first_fail_at = i
                print(f"  *** FIRST FAILURE at request #{i} (after {done} completed): "
                      f"{r['detail']} ***", flush=True)
            if done % 25 == 0:
                ok_so_far = sum(1 for x in results if x["ok"])
                elapsed = time.time() - t0
                print(f"  ...{done}/{_TOTAL} done, {ok_so_far} ok so far ({elapsed:.1f}s elapsed)",
                      flush=True)

    results.sort(key=lambda r: r["order"])
    ok = sum(1 for r in results if r["ok"])
    fails = [r for r in results if not r["ok"]]
    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"RESULT: {ok}/{_TOTAL} succeeded in {elapsed:.1f}s")
    if fails:
        print(f"First failure at request order #{fails[0]['order']}")
        print(f"Failure orders: {[f['order'] for f in fails][:30]}"
              f"{'...' if len(fails) > 30 else ''}")
    else:
        print("No failures at all -- no cumulative volume limit detected up to this total.")
    print(f"{'=' * 60}")
    return 0 if ok == _TOTAL else 1


if __name__ == "__main__":
    sys.exit(main())
