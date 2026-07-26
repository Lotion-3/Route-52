"""
Coles (Australia) grocery pricing — direct from coles.com.au.

Coles exposes a clean REST JSON search API at `/api/bff/products/search`
(no HTML scraping needed), but it's fronted by Imperva, which checks the
caller's TLS/JA3 fingerprint AND a JS-minted `reese84` challenge cookie
(plus the usual `incap_ses_*` / `visid_incap_*` / `nlbi_*` session cookies).

Primary path (fast): a CloakBrowser is used ONLY to mint the Imperva cookie
jar (a homepage + search-nav warm clears the challenge); then we replay the
search over plain HTTP with curl_cffi, which impersonates Chrome's JA3.
Validated 2026-07-23: a browser-warmed cookie jar replays cleanly from a
datacenter IP with zero proxy — same recipe as Walmart/Target.

The request also needs a static `ocp-apim-subscription-key` header (an Azure
APIM key baked into Coles' frontend JS bundle — not session-specific, but
brittle if Coles rotates it; if requests start 401ing, recapture it from
DevTools the same way the whole endpoint was found).

Store resolution: `find_nearest_coles_store(lat, lon)` calls Coles' own
store-locator API (`/api/bff/stores/search`, same session/headers as
pricing), sorted by distance — no separate credentials needed. Filters to
"Coles Supermarkets" to skip Coles Express (petrol) results.

Entry point:
    store_id = find_nearest_coles_store(lat, lon) or "7674"
    store_name, store_id, prices = price_all_coles(ingredients, store_id=store_id)

Self-test:  python coles_pricing.py
Env: CLOAK_PROXY, COLES_HTTP_CONCURRENCY, COLES_WARM_TRIES,
     COLES_IMPERSONATE, COLES_MAX_IP_REFRESHES, COLES_SEARCH_TTL
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLES_BANNERS: set[str] = {"coles"}
_SEARCH_URL = "https://www.coles.com.au/api/bff/products/search"
_WARM_URL = "https://www.coles.com.au/"
_WARM_SEARCH_URL = "https://www.coles.com.au/search?q={q}"

# Static Azure APIM key shipped in Coles' frontend JS bundle — captured via
# DevTools 2026-07-23. Not tied to any session, but may rotate; if pricing
# starts failing with 401s, recapture from a fresh Network-tab request.
_SUBSCRIPTION_KEY = os.environ.get("COLES_SUBSCRIPTION_KEY", "eae83861d1cd4de6bb9cd8a2cd6f041e")

def _parse_proxies(raw: Optional[str]) -> list[str]:
    """Split a proxy env value into a pool (comma/whitespace separated) — same
    convention as target_pricing.py/walmart_pricing.py, so CLOAK_PROXY works
    identically everywhere: a single URL, a single URL with a {session}
    placeholder, or a comma-separated pool of fixed proxies."""
    import re as _re
    if not raw:
        return []
    return [p.strip() for p in _re.split(r"[,\s]+", raw) if p.strip()]

_PROXIES = _parse_proxies(os.environ.get("CLOAK_PROXY") or os.environ.get("COLES_PROXY"))
_PROXY = _PROXIES[0] if _PROXIES else None  # kept for back-compat truthiness checks
MAX_IP_REFRESHES = int(os.environ.get("COLES_MAX_IP_REFRESHES", "5"))
_SEARCH_TTL = int(os.environ.get("COLES_SEARCH_TTL", str(6 * 3600)))

_HTTP_CONCURRENCY = int(os.environ.get("COLES_HTTP_CONCURRENCY", "8"))
_WARM_TRIES = int(os.environ.get("COLES_WARM_TRIES", "3"))
_IMPERSONATE = os.environ.get("COLES_IMPERSONATE", "chrome")

_http_session: Optional[dict] = None       # {"cookies": {...}, "ua": str}
_http_lock = threading.Lock()              # serialize warm/re-mint of the session
# Disk cache so the last cookie survives restarts. Imperva's reese84/incap_ses
# cookies are longer-lived than PerimeterX's _px3 but still session-scoped, so
# keep the TTL conservative.
_HTTP_SESSION_CACHE = Path(__file__).parent / ".coles_http_session.json"
_HTTP_COOKIE_TTL = int(os.environ.get("COLES_COOKIE_TTL", str(20 * 60)))


class _Blocked(Exception):
    """Raised when Imperva blocks/challenges the request."""


def is_coles_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in COLES_BANNERS)


# ---------------------------------------------------------------------------
# Bandwidth trim for the warm navigation — the WAF challenge only needs its
# own JS to execute; it doesn't need images/fonts/video or third-party
# ad-tech to load. Measured 2026-07-25: cuts a Coles+Woolworths warm pair
# from ~30.6MB to a few MB. Leaves stylesheets alone (some bot-challenge
# scripts read computed styles as a fingerprint signal).
# ---------------------------------------------------------------------------
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_BLOCKED_DOMAIN_SUBSTRINGS = (
    "doubleclick", "googletagmanager", "google-analytics", "googlesyndication",
    "googleadservices", "facebook.com", "fbcdn", "fbevents", "adobedtm",
    "demdex", "everesttech", "tealiumiq", "omtrdc", "adsrvr", "tiktok",
    "bing.com/p", "clarity.ms", "hotjar", "criteo", "outbrain", "taboola",
    "spotxchange", "pinterest",
)


def _block_heavy_resources(ctx) -> None:
    def _handle(route):
        req = route.request
        url = req.url.lower()
        if req.resource_type in _BLOCKED_RESOURCE_TYPES or any(
            d in url for d in _BLOCKED_DOMAIN_SUBSTRINGS
        ):
            route.abort()
            return
        if req.resource_type in _CACHEABLE_TYPES and "_next/static/" in req.url:
            cached = _static_asset_cache.get(req.url)
            if cached:
                route.fulfill(status=cached["status"], headers=cached["headers"], body=cached["body"])
                return
        route.continue_()
    ctx.route("**/*", _handle)


# Coles serves its JS/CSS chunks under content-hashed filenames (Cache-Control:
# max-age=3600, valid ETag) — safe to cache indefinitely, since a redeploy
# changes the hash rather than the content at the same URL. Measured
# 2026-07-25: the headless context wasn't reusing this across the required
# homepage+search warm navigations (~9.5MB re-downloaded per warm for no
# reason) — route.fulfill() serves the second hit from memory, which also
# means it never touches the network/proxy at all for the repeat.
_CACHEABLE_TYPES = {"script", "stylesheet"}
_static_asset_cache: dict[str, dict] = {}


def _cache_static_assets(resp) -> None:
    req = resp.request
    if req.resource_type in _CACHEABLE_TYPES and "_next/static/" in req.url and req.url not in _static_asset_cache:
        try:
            _static_asset_cache[req.url] = {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": resp.body(),
            }
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CloakBrowser warm — mint the Imperva cookie jar (reese84 + incap_ses_* etc.)
# ---------------------------------------------------------------------------

_run_lock = threading.Lock()       # serialize whole-Coles runs across requests
_thread_local = threading.local()  # per-worker: proxy_session


def _rotate_proxy_session() -> None:
    _thread_local.proxy_session = os.urandom(6).hex()
    if _PROXIES:
        _thread_local.proxy_idx = random.randrange(len(_PROXIES))


def _current_proxy() -> Optional[str]:
    if not _PROXIES:
        return None
    idx = getattr(_thread_local, "proxy_idx", None)
    if idx is None:
        idx = random.randrange(len(_PROXIES))
        _thread_local.proxy_idx = idx
    base = _PROXIES[idx % len(_PROXIES)]
    if "{session}" in base:
        sid = getattr(_thread_local, "proxy_session", None)
        return base.replace("{session}", sid or os.urandom(6).hex())
    return base


def _warm_http_session() -> dict:
    """Launch CloakBrowser, warm Imperva via the homepage + a real search
    navigation, then harvest the full cookie jar (reese84, incap_ses_*,
    visid_incap_*, nlbi_*, ...) and user-agent. Raises _Blocked on a weak warm."""
    from browser_gate import launch  # gated: 1 browser at a time + low-mem flags (was cloakbrowser.launch)
    if getattr(_thread_local, "proxy_session", None) is None:
        _rotate_proxy_session()
    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True
    try:
        browser = launch(**kwargs)
    except Exception:
        kwargs.pop("geoip", None)
        browser = launch(**kwargs)
    try:
        ctx = browser.new_context()
        _block_heavy_resources(ctx)
        page = ctx.new_page()
        page.on("response", _cache_static_assets)
        page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        # The search nav (not just the homepage) is what reliably mints a
        # reese84 token the API will accept — mirrors the Walmart recipe.
        page.goto(_WARM_SEARCH_URL.format(q="milk"), wait_until="domcontentloaded", timeout=45000)
        time.sleep(1)
        ua = page.evaluate("() => navigator.userAgent")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    finally:
        try:
            browser.close()
        except Exception:
            pass
    if "reese84" not in cookies:
        raise _Blocked("weak warm — no reese84 cookie minted")
    return {"cookies": cookies, "ua": ua}


def _save_http_session(session: dict) -> None:
    try:
        _HTTP_SESSION_CACHE.write_text(json.dumps({
            "cookies": session["cookies"], "ua": session["ua"], "saved_at": time.time(),
        }))
    except Exception:
        pass


def _load_http_session() -> Optional[dict]:
    try:
        d = json.loads(_HTTP_SESSION_CACHE.read_text())
        if time.time() - float(d.get("saved_at", 0)) <= _HTTP_COOKIE_TTL:
            return {"cookies": d["cookies"], "ua": d["ua"]}
    except Exception:
        pass
    return None


def _validate_http_session(session: dict, store_id: str) -> bool:
    """Cheap liveness check (no browser): one curl_cffi search must succeed."""
    try:
        _fetch_products_http("eggs", store_id, session)
        return True
    except Exception:
        return False


def _ensure_http_session(store_id: str) -> dict:
    global _http_session
    if _http_session is not None:
        return _http_session
    with _http_lock:
        if _http_session is None:
            # Prefer an off-box cookie (minted by GitHub Actions -> Supabase) so
            # the 512MB server can skip launching a browser; then local disk;
            # then, only if both miss, warm a browser here.
            cached = _load_remote_session()
            if cached and _validate_http_session(cached, store_id):
                _http_session = cached
                print("[Coles] Reused off-box cookie (Supabase, no warm).", flush=True)
            else:
                cached = _load_http_session()
                if cached and _validate_http_session(cached, store_id):
                    _http_session = cached
                    print("[Coles] Reused cached HTTP cookie (no warm).", flush=True)
            if _http_session is None:
                last: Optional[Exception] = None
                for _ in range(_WARM_TRIES):
                    try:
                        _http_session = _warm_http_session()
                        _save_http_session(_http_session)
                        print(f"[Coles] HTTP session warmed (curl_cffi"
                              f"{', proxy' if _PROXIES else ''}).", flush=True)
                        break
                    except Exception as e:
                        last = e
                        _rotate_proxy_session()
                if _http_session is None:
                    raise _Blocked(f"warm failed after {_WARM_TRIES} tries: {repr(last)[:80]}")
    return _http_session


def _load_remote_session() -> Optional[dict]:
    """Off-box cookie from Supabase (published by mint_sessions.py on GitHub
    Actions). Returns None if unavailable/stale — the caller then falls back to
    disk cache / a local browser warm, so this is a pure speedup, never a
    dependency."""
    try:
        import session_store
        return session_store.load("coles")
    except Exception:
        return None


def _drop_http_session() -> None:
    global _http_session
    _http_session = None


def _invalidate_http_session() -> None:
    global _http_session
    _http_session = None
    try:
        _HTTP_SESSION_CACHE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Search API → items  (curl_cffi replay)
# ---------------------------------------------------------------------------

def _fetch_products_http(term: str, store_id: str, session: dict) -> list[dict]:
    """Replay the search over plain HTTP with the warmed Imperva cookie jar +
    Chrome JA3 impersonation. Raises _Blocked on a challenge/block."""
    from curl_cffi import requests as _ccffi
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": _WARM_URL,
        "dsch-channel": "coles.online.1site.desktop",
        "ocp-apim-subscription-key": _SUBSCRIPTION_KEY,
        "x-api-version": "2",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": session["ua"],
    }
    params = {"searchTerm": term, "storeId": store_id, "start": "0"}
    try:
        resp = _ccffi.get(_SEARCH_URL, params=params, headers=headers,
                           cookies=session["cookies"], impersonate=_IMPERSONATE, timeout=30)
    except Exception as e:
        raise _Blocked(f"http error: {repr(e)[:80]}")

    if resp.status_code in (401, 403, 429):
        raise _Blocked(f"status {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        # Non-JSON body → Imperva challenge/captcha page, not the API.
        raise _Blocked("non-JSON response")

    if resp.status_code != 200:
        # A real app-level error (e.g. bad params), not a block — treat as no results.
        errs = data.get("errors") if isinstance(data, dict) else None
        print(f"[Coles] '{term}' request error: {errs}", flush=True)
        return []
    return data.get("results") or []


# ---------------------------------------------------------------------------
# Store locator — lat/lon -> nearest real Coles storeId
# ---------------------------------------------------------------------------

_STORE_SEARCH_URL = "https://www.coles.com.au/api/bff/stores/search"
_BOOTSTRAP_STORE_ID = "7674"  # any valid id — only used to warm/validate a session
_store_locator_cache: dict[tuple[float, float], tuple[float, str]] = {}
_STORE_LOCATOR_TTL = int(os.environ.get("COLES_STORE_LOCATOR_TTL", str(24 * 3600)))


def find_nearest_coles_store(lat: float, lon: float) -> Optional[str]:
    """Resolve coordinates to the nearest real Coles Supermarkets store id via
    Coles' own store-locator API (same session/headers as pricing — sorted by
    distance, closest first). Returns None on any failure; caller should fall
    back to a default store id."""
    key = (round(lat, 3), round(lon, 3))
    cached = _store_locator_cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]

    try:
        session = _ensure_http_session(_BOOTSTRAP_STORE_ID)
        from curl_cffi import requests as _ccffi
        headers = {
            "accept": "*/*",
            "referer": _WARM_URL,
            "dsch-channel": "coles.online.1site.desktop",
            "ocp-apim-subscription-key": _SUBSCRIPTION_KEY,
            "x-api-version": "2",
            "user-agent": session["ua"],
        }
        params = {"latitude": lat, "longitude": lon, "distance": 50, "numberOfStores": 5}
        resp = _ccffi.get(_STORE_SEARCH_URL, params=params, headers=headers,
                           cookies=session["cookies"], impersonate=_IMPERSONATE, timeout=20)
        if resp.status_code != 200:
            return None
        stores = resp.json().get("stores") or []
        # Results are pre-sorted by distance — skip Coles Express (petrol)
        # and other non-supermarket banners, take the closest match.
        supermarkets = [s for s in stores if "supermarket" in (s.get("brandName") or "").lower()]
        chosen = (supermarkets or stores or [None])[0]
        if not chosen:
            return None
        store_id = str(chosen["storeId"])
        _store_locator_cache[key] = (time.time() + _STORE_LOCATOR_TTL, store_id)
        print(f"[Coles] Nearest store: {chosen.get('storeName')} "
              f"({chosen.get('distance', {}).get('description', '?')}) — id {store_id}", flush=True)
        return store_id
    except Exception as e:
        print(f"[Coles] Store lookup failed ({repr(e)[:100]}).", flush=True)
        return None


# ---------------------------------------------------------------------------
# Item → shared "Kroger format" (consumed by find_best_purchase)
# ---------------------------------------------------------------------------

def _item_to_kroger_format(item: dict) -> Optional[dict]:
    name = item.get("name") or ""
    if not name or item.get("_type") != "PRODUCT":
        return None
    pricing = item.get("pricing") or {}
    price = pricing.get("now")
    if price is None or not (0.01 <= price <= 500):
        return None

    unit = pricing.get("unit") or {}
    is_weighted = bool(unit.get("isWeighted"))
    size = item.get("size") or "1 each"
    if is_weighted:
        # Weighted items (deli/produce) are priced per kg — reuse Kroger's
        # WEIGHT convention, normalized to lb the way parse_size expects.
        size = "1 kg"

    return {
        "description": name,
        "brand": item.get("brand") or "",
        "items": [{
            "itemId": str(item.get("id") or ""),
            "soldBy": "WEIGHT" if is_weighted else "UNIT",
            "size": size,
            "price": {"regular": float(price), "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Search (cached) + per-ingredient pricing
# ---------------------------------------------------------------------------

_search_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def _search(term: str, store_id: str) -> list[dict]:
    """Return Kroger-format products for `term` at `store_id` (cached). May raise _Blocked."""
    key = (term.lower(), store_id)
    cached = _search_cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]

    session = _ensure_http_session(store_id)
    raw = _fetch_products_http(term, store_id, session)
    query_words = set(term.lower().split())
    out = []
    for it in raw:
        fmt = _item_to_kroger_format(it)
        if fmt and any(w in fmt["description"].lower() for w in query_words):
            out.append(fmt)
    if not out:  # relax keyword filter if nothing matched
        out = [f for f in (_item_to_kroger_format(it) for it in raw) if f]
    _search_cache[key] = (time.time() + _SEARCH_TTL, out)
    return out


def _price_one(ingredient: str, qty: float, unit: str, store_id: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search(term, store_id)  # may raise _Blocked
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


def _price_via_http(ingredients: dict, store_id: str) -> dict:
    """One browser warm, then price every ingredient over parallel curl_cffi
    requests. On a wave of Imperva throttles, re-mint the cookie and retry
    just the blocked items, up to MAX_IP_REFRESHES."""
    prices: dict = {}
    pending = dict(ingredients)
    refreshes = 0
    while pending:
        _ensure_http_session(store_id)

        def _work(item):
            name, data = item
            try:
                r = _price_one(name, float(data.get("qty", 1) or 1),
                                str(data.get("unit", "whole")), store_id)
                return name, r, False
            except _Blocked:
                return name, None, True
            except Exception as e:
                print(f"[Coles] Error pricing '{name}': {e}", flush=True)
                return name, None, False

        blocked: dict = {}
        with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(pending)),
                                thread_name_prefix="coles-http") as pool:
            for name, r, was_blocked in pool.map(_work, list(pending.items())):
                if was_blocked:
                    blocked[name] = pending[name]
                elif r:
                    prices[name] = r
        pending = blocked
        if not pending:
            break
        if refreshes >= MAX_IP_REFRESHES:
            print(f"[Coles] Still throttled after {refreshes} re-mints — "
                  f"{len(pending)} item(s) unpriced.", flush=True)
            break
        refreshes += 1
        print(f"[Coles] Imperva throttle — re-minting session "
              f"(refresh {refreshes}/{MAX_IP_REFRESHES}).", flush=True)
        _invalidate_http_session()
        _rotate_proxy_session()
        time.sleep(min(1.0 * refreshes, 5.0) + random.uniform(0, 0.75))
    return prices


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_coles(
    ingredients: dict,
    store_id: str,
    lat: float = 0.0,
    lon: float = 0.0,
) -> tuple[Optional[str], Optional[str], dict]:
    """Price all ingredients at a specific Coles store.

    NOTE: lat/lon are accepted for interface parity with the other
    price_all_* modules but are NOT currently used to resolve a store —
    store_id must be supplied by the caller until store-lookup-by-location
    is built (see module docstring)."""
    items = list(ingredients.items())
    if not items or not store_id:
        return None, None, {}

    with _run_lock:
        try:
            prices = _price_via_http(ingredients, store_id)
        except Exception as e:
            print(f"[Coles] HTTP path unavailable ({repr(e)[:120]}).", flush=True)
            prices = {}
        finally:
            _drop_http_session()

    if not prices:
        return None, None, {}
    print(f"[Coles] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "Coles", store_id, prices


def shutdown() -> None:
    pass


# ---------------------------------------------------------------------------
# Self-test:  python coles_pricing.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 7674 = the store captured during DevTools discovery (2026-07-23). Swap
    # for a real store id once store-lookup-by-location exists.
    TEST_STORE_ID = os.environ.get("COLES_TEST_STORE_ID", "7674")
    sample = {
        "milk":           {"qty": 2, "unit": "litre"},
        "eggs":           {"qty": 12, "unit": "count"},
        "bananas":        {"qty": 1, "unit": "kg"},
        "chicken breast": {"qty": 1, "unit": "kg"},
        "white rice":     {"qty": 1, "unit": "kg"},
    }
    name, sid, out = price_all_coles(sample, store_id=TEST_STORE_ID)
    print(f"\n=== {name} ({sid}) ===")
    if not out:
        print("No prices — CloakBrowser unavailable or Imperva-blocked.")
    for ing, res in out.items():
        print(f"  {ing:16s} ${res.get('total_cost', 0):7.2f}  "
              f"{res.get('description', '')[:40]} ({res.get('size_str', '')})")
    shutdown()
