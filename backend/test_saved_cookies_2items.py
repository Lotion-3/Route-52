"""
Diagnostic: test every cookie in backend/saved_target_cookies.json against
Target's real pricing pipeline (target_pricing._price_one), pricing 2
ingredients per cookie instead of a single raw search.

Usage:
    python test_saved_cookies_2items.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import target_pricing as tp

_FILE = Path(__file__).parent / "saved_target_cookies.json"
_STORE_ID = "1771"
_ITEMS = [
    ("milk", 1, "gallon"),
    ("eggs", 12, "count"),
]


def main() -> int:
    if not _FILE.exists():
        print(f"File not found: {_FILE}", flush=True)
        return 1

    sessions = json.loads(_FILE.read_text())
    if not isinstance(sessions, list):
        print(f"Expected a JSON array, got {type(sessions).__name__}", flush=True)
        return 1

    print(f"Testing {len(sessions)} Target cookies, {len(_ITEMS)} items each "
          f"(store #{_STORE_ID})...\n", flush=True)

    summary = []
    for i, session in enumerate(sessions):
        cookies = session.get("cookies", {})
        ua = session.get("ua", "")
        saved = session.get("saved_at_iso", "unknown")
        n_cookies = len(cookies)
        has_px3 = "_px3" in cookies

        print(f"[Cookie {i + 1}/{len(sessions)}]  {n_cookies} cookies, px3={has_px3}, "
              f"saved={saved}", flush=True)

        # target_pricing caches search results per (store_id, term) regardless
        # of which cookie fetched them — clear it so every cookie actually
        # hits Target live instead of reusing an earlier cookie's response.
        tp._search_cache.clear()

        tp._thread_local.http = {"cookies": cookies, "ua": ua}
        item_results = []
        try:
            for name, qty, unit in _ITEMS:
                t0 = time.time()
                try:
                    result = tp._price_one(name, qty, unit, _STORE_ID)
                    elapsed = time.time() - t0
                    if result:
                        print(f"    {name:16s} OK    ${result.get('total_cost', 0):6.2f}  "
                              f"{result.get('description', '')} ({result.get('size_str', '')})"
                              f"  [{elapsed:.2f}s]", flush=True)
                        item_results.append(True)
                    else:
                        print(f"    {name:16s} FAIL  no match found  [{elapsed:.2f}s]", flush=True)
                        item_results.append(False)
                except tp._ImpervaBlocked as e:
                    elapsed = time.time() - t0
                    print(f"    {name:16s} BLOCKED  category={e.category}  {e}  [{elapsed:.2f}s]",
                          flush=True)
                    item_results.append(False)
        finally:
            tp._thread_local.http = None

        ok_count = sum(item_results)
        summary.append((ok_count, len(_ITEMS)))
        print(f"    -> {ok_count}/{len(_ITEMS)} items priced\n", flush=True)

    print(f"  {'=' * 60}")
    total_ok = sum(ok for ok, _ in summary)
    total_items = sum(total for _, total in summary)
    print(f"  SUMMARY:  {total_ok}/{total_items} item-prices succeeded across "
          f"{len(sessions)} cookies")
    for i, (ok, total) in enumerate(summary):
        status = "OK" if ok == total else ("PARTIAL" if ok else "FAIL")
        print(f"  Cookie #{i + 1}:  {status}  ({ok}/{total} items)")
    print(f"  {'=' * 60}")

    return 0 if total_ok == total_items else 1


if __name__ == "__main__":
    sys.exit(main())
