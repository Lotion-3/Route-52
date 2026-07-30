"""
Diagnostic: are the saved Target cookies (minted while browsing from an
Indianapolis-area IP/location -- GuestLocation/UserLocation/fiatsCookie/
sddStore all say 46033|Carmel, IN) usable to price REAL stores in other,
far-away cities?

nearby_stores_v1 (dynamic store lookup by lat/lon) turned out to be
unconditionally blocked -- confirmed separately with zero cookies, same
403/captcha -- so it can't be used to resolve store ids. Instead this pulls
real, verified store ids straight from Target's public sitemap
(target.com/sl/<slug>/<id>) and prices 2 items at each one directly via the
SLP endpoint, using the saved cookies.

Usage:
    python test_cookies_cross_location.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import target_pricing as tp

_FILE = Path(__file__).parent / "saved_target_cookies.json"
_ITEMS = [
    ("milk", 1, "gallon"),
    ("eggs", 12, "count"),
]
# Real store ids pulled from target.com/sl/sitemap_0001.xml.gz -- verified to
# exist, far from the cookies' baked-in Carmel, IN (46033) location.
_STORES = [
    ("Los Angeles, CA",  "1306"),
    ("Chicago, IL",      "942"),
    ("Miami, FL",        "2188"),
    ("Seattle, WA",      "637"),
    ("Manhattan, NY",    "1821"),
]


def main() -> int:
    sessions = json.loads(_FILE.read_text())
    print(f"Cross-location test: {len(sessions)} cookies (round-robin) x "
          f"{len(_STORES)} real out-of-state stores x {len(_ITEMS)} items\n", flush=True)
    print("Each cookie's cookie jar was minted at Carmel, IN (46033). Testing "
          "whether it can price real stores far from that location.\n", flush=True)

    all_ok = True
    for i, (city, store_id) in enumerate(_STORES):
        session = sessions[i % len(sessions)]
        cookies = session["cookies"]
        ua = session["ua"]
        tp._search_cache.clear()
        tp._thread_local.http = {"cookies": cookies, "ua": ua}
        print(f"[{city}]  store_id={store_id}  (cookie #{i % len(sessions) + 1})", flush=True)
        try:
            for name, qty, unit in _ITEMS:
                t0 = time.time()
                try:
                    result = tp._price_one(name, qty, unit, store_id)
                    elapsed = time.time() - t0
                    if result:
                        print(f"    {name:16s} OK    ${result.get('total_cost', 0):6.2f}  "
                              f"{result.get('description', '')} ({result.get('size_str', '')})"
                              f"  [{elapsed:.2f}s]", flush=True)
                    else:
                        print(f"    {name:16s} FAIL  no match found  [{elapsed:.2f}s]", flush=True)
                        all_ok = False
                except tp._ImpervaBlocked as e:
                    elapsed = time.time() - t0
                    print(f"    {name:16s} BLOCKED  category={e.category}  {e}  [{elapsed:.2f}s]",
                          flush=True)
                    all_ok = False
        finally:
            tp._thread_local.http = None
        print(flush=True)

    print(f"  {'=' * 60}")
    print(f"  {'All out-of-state stores priced successfully -- cookies are NOT location-pinned.' if all_ok else 'Some stores failed -- see above.'}")
    print(f"  {'=' * 60}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
