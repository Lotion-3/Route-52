"""
Walmart grocery pricing — direct from walmart.com via a stealth CloakBrowser.

Walmart embeds its full product+price list in the Next.js `__NEXT_DATA__` blob
on the search page, so we don't need a separate API call — we load the search
page in a real (stealth) browser and read the blob. walmart.com is fronted by
PerimeterX/HUMAN; plain `requests` gets a 412/captcha, but CloakBrowser (a
Chromium with C++ fingerprint patches) renders the page and the blob with real
prices, even from a datacenter IP (verified).

Pricing is national/default (no store resolution); the blob price is
`priceInfo.linePrice`.

Reliability mirrors target_pricing: one warm browser pinned to a worker thread,
per-term cache, and on a PerimeterX block we rotate to a fresh proxy exit IP and
retry up to MAX_IP_REFRESHES times before returning empty → server falls back to
Instacart for Walmart. A residential proxy (CLOAK_PROXY) makes it reliable from
a datacenter host.

Entry point:
    store_name, store_id, prices = price_all_walmart(ingredients, lat, lon)

Self-test:  python walmart_pricing.py
Env: CLOAK_PROXY, WALMART_MAX_IP_REFRESHES, WALMART_SEARCH_TTL

NOTE: shares the CloakBrowser session pattern with target_pricing; once a third
chain lands, extract the common engine into a shared module (rule of three).
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from kroger_pricing import find_best_purchase, parse_size
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WALMART_BANNERS: set[str] = {"walmart"}
_SEARCH_URL = "https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40"
_WARM_URL = "https://www.walmart.com/"
_STORE_ID = "national"  # Walmart online pricing isn't store-resolved here

_PROXY = os.environ.get("CLOAK_PROXY") or os.environ.get("WALMART_PROXY") or None
MAX_IP_REFRESHES = int(os.environ.get("WALMART_MAX_IP_REFRESHES", "5"))
_SEARCH_TTL = int(os.environ.get("WALMART_SEARCH_TTL", str(6 * 3600)))


class _Blocked(Exception):
    """Raised when PerimeterX blocks the page (no __NEXT_DATA__)."""


def is_walmart_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in WALMART_BANNERS)


# ---------------------------------------------------------------------------
# CloakBrowser singleton — all access pinned to one worker thread
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloak-walmart")
_browser = None
_ctx = None
_session_lock = threading.Lock()
_proxy_session_id: Optional[str] = None


def _rotate_proxy_session() -> None:
    global _proxy_session_id
    _proxy_session_id = os.urandom(6).hex()


def _current_proxy() -> Optional[str]:
    if not _PROXY:
        return None
    if "{session}" in _PROXY:
        return _PROXY.replace("{session}", _proxy_session_id or os.urandom(6).hex())
    return _PROXY


def _bootstrap_session():
    """(worker thread) Launch CloakBrowser on the current proxy session and warm
    PerimeterX cookies via the homepage. Raises on launch failure → Instacart."""
    global _browser, _ctx
    from cloakbrowser import launch

    _teardown_session()
    if _proxy_session_id is None:
        _rotate_proxy_session()

    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True
    try:
        _browser = launch(**kwargs)
    except Exception:
        kwargs.pop("geoip", None)
        _browser = launch(**kwargs)

    _ctx = _browser.new_context()
    page = _ctx.new_page()
    page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
    time.sleep(2)
    page.close()
    print(f"[Walmart] CloakBrowser session warmed{' (proxy)' if proxy else ''}.", flush=True)


def _teardown_session():
    global _browser, _ctx
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    _browser, _ctx = None, None


def _ensure_ctx():
    global _ctx
    if _ctx is None:
        _bootstrap_session()
    return _ctx


# ---------------------------------------------------------------------------
# Search page → items  (worker thread)
# ---------------------------------------------------------------------------

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


def _fetch_items(term: str) -> list[dict]:
    """(worker thread) Load the search page, return raw Walmart item dicts.
    Raises _Blocked when PerimeterX serves a challenge (no __NEXT_DATA__)."""
    ctx = _ensure_ctx()
    page = ctx.new_page()
    try:
        page.goto(_SEARCH_URL.format(q=requests_quote(term)),
                  wait_until="domcontentloaded", timeout=45000)
        nd = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__');"
            " return e ? e.textContent : null; }"
        )
    except Exception as e:
        raise _Blocked(f"page load failed: {repr(e)[:80]}")
    finally:
        try:
            page.close()
        except Exception:
            pass

    if not nd:
        # No data blob → PerimeterX challenge / block.
        raise _Blocked("no __NEXT_DATA__")
    try:
        return _find_items(json.loads(nd))
    except Exception:
        return []  # parseable page, just no usable items


# ---------------------------------------------------------------------------
# Item → Kroger product shape
# ---------------------------------------------------------------------------

_NUM_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(fl\.?\s*oz|fluid\s*ounce|oz|ounce|lb|lbs|pound|gal|gallon|qt|quart|"
    r"pt|pint|count|ct|pk|pack|liter|litre|ml|kg|g)\b",
    re.IGNORECASE,
)
# Bare unit words with no number (Walmart names like "…, Gallon").
_BARE_SIZE = {
    "half gallon": "0.5 gal", "gallon": "1 gal", "quart": "1 qt",
    "pint": "1 pt", "dozen": "12 ct",
}


def _extract_size(name: str) -> str:
    low = name.lower()
    m = _NUM_SIZE_RE.search(name)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    for word, size in _BARE_SIZE.items():  # "half gallon" before "gallon"
        if word in low:
            return size
    return "1 each"


def _price_from_lineprice(price_info: dict) -> Optional[float]:
    raw = (price_info.get("linePrice") or price_info.get("linePriceDisplay")
           or price_info.get("itemPrice") or "")
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(raw).replace(",", ""))
    if not m:
        return None
    val = float(m.group(1))
    return val if 0.01 <= val <= 500 else None


def _item_to_kroger_format(item: dict) -> Optional[dict]:
    name = item.get("name") or ""
    if not name:
        return None
    # Skip third-party marketplace sellers (shipping/markup, not in-store price).
    if item.get("hasSellerBadge"):
        return None
    pi = item.get("priceInfo") or {}
    price = _price_from_lineprice(pi)
    if price is None:
        return None

    by_weight = bool(pi.get("finalCostByWeight"))
    return {
        "description": name,
        "brand": item.get("brand") or "",
        "items": [{
            "itemId": str(item.get("usItemId") or item.get("id") or ""),
            "soldBy": "WEIGHT" if by_weight else "UNIT",
            "size": "1 lb" if by_weight else _extract_size(name),
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Search (cached) + per-ingredient pricing
# ---------------------------------------------------------------------------

def requests_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


_search_cache: dict[str, tuple[float, list[dict]]] = {}


def _search(term: str) -> list[dict]:
    """Return Kroger-format products for `term` (cached). May raise _Blocked."""
    cached = _search_cache.get(term.lower())
    if cached and cached[0] > time.time():
        return cached[1]

    raw = _fetch_items(term)  # raises _Blocked on PX challenge
    query_words = set(term.lower().split())
    out = []
    for it in raw:
        fmt = _item_to_kroger_format(it)
        if fmt and any(w in fmt["description"].lower() for w in query_words):
            out.append(fmt)
    if not out:  # relax keyword filter if nothing matched
        out = [f for f in (_item_to_kroger_format(it) for it in raw) if f]
    _search_cache[term.lower()] = (time.time() + _SEARCH_TTL, out)
    return out


def _price_one(ingredient: str, qty: float, unit: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search(term)  # may raise _Blocked
        if not products:
            continue
        result = find_best_purchase(ingredient, qty, unit, products)
        if result:
            return result
        if term.lower() != ingredient.lower():
            result = find_best_purchase(term, qty, unit, products)
            if result:
                return result
    return None


def _do_pricing(ingredients: dict) -> dict:
    """(worker thread) Price all ingredients, rotating exit IP on PerimeterX
    blocks (up to MAX_IP_REFRESHES) before giving up → Instacart fallback."""
    prices: dict = {}
    pending = dict(ingredients)
    refreshes = 0
    while pending:
        try:
            _ensure_ctx()
            for name in list(pending):
                data = pending[name]
                try:
                    r = _price_one(name, float(data.get("qty", 1) or 1),
                                   str(data.get("unit", "whole")))
                    if r:
                        prices[name] = r
                except _Blocked:
                    raise
                except Exception as e:
                    print(f"[Walmart] Error pricing '{name}': {e}", flush=True)
                del pending[name]
            break
        except _Blocked:
            if refreshes >= MAX_IP_REFRESHES:
                print(f"[Walmart] Still blocked after {refreshes} IP refreshes — "
                      f"falling back to Instacart.", flush=True)
                return {}
            refreshes += 1
            print(f"[Walmart] PerimeterX block — rotating exit IP "
                  f"(refresh {refreshes}/{MAX_IP_REFRESHES}).", flush=True)
            _teardown_session()
            _rotate_proxy_session()
            time.sleep(min(1.0 * refreshes, 5.0) + random.uniform(0, 0.75))
    return prices


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_walmart(
    ingredients: dict,
    lat: float = 0.0,
    lon: float = 0.0,
    max_workers: int = 10,  # signature parity; pricing is serialized
) -> tuple[Optional[str], Optional[str], dict]:
    """Price all ingredients at Walmart (national online pricing) via CloakBrowser.
    Returns (display_name, store_id, prices); empty prices → caller uses Instacart."""
    with _session_lock:
        try:
            prices = _executor.submit(_do_pricing, ingredients).result()
        except Exception as e:
            print(f"[Walmart] Direct pricing unavailable ({repr(e)[:140]}) — "
                  "falling back to Instacart.", flush=True)
            return None, None, {}
    print(f"[Walmart] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "Walmart", _STORE_ID, prices


def shutdown():
    try:
        _executor.submit(_teardown_session).result(timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Self-test:  python walmart_pricing.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample = {
        "milk":           {"qty": 1, "unit": "gallon"},
        "eggs":           {"qty": 12, "unit": "count"},
        "bananas":        {"qty": 3, "unit": "pound"},
        "chicken breast": {"qty": 3, "unit": "pound"},
        "white rice":     {"qty": 5, "unit": "pound"},
    }
    name, sid, out = price_all_walmart(sample)
    print(f"\n=== {name} ({sid}) ===")
    if not out:
        print("No prices — CloakBrowser unavailable or PerimeterX-blocked.")
    for ing, res in out.items():
        print(f"  {ing:16s} ${res.get('total_cost', 0):7.2f}  "
              f"{res.get('description', '')[:40]} ({res.get('size_str', '')})")
    shutdown()
