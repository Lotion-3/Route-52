"""
Walmart grocery pricing — direct from walmart.com.

Walmart embeds its full product+price list in the Next.js `__NEXT_DATA__` blob
on the search page (price = `priceInfo.linePrice`), so there's no separate API.
walmart.com is fronted by PerimeterX/HUMAN, which checks two things: the caller's
TLS/JA3 fingerprint AND a JS-minted cookie (_px3).

Primary path (fast): a CloakBrowser is used ONLY to mint the _px3 cookie (a
homepage + search-nav warm fully clears the challenge); then we replay the search
over plain HTTP with curl_cffi, which impersonates Chrome's JA3. That lets us
fetch every ingredient in parallel — like the ALDI path — off a single browser
warm. A too-wide burst gets throttled, so concurrency is capped and the cookie is
re-minted on a wave of blocks (up to MAX_IP_REFRESHES).

Fallback path: if the HTTP path yields nothing (e.g. PerimeterX starts blocking
curl_cffi's JA3 while real renders still pass), a pool of CloakBrowser workers
navigates the search pages directly. A residential proxy (CLOAK_PROXY) makes
either path reliable from a datacenter host.

Entry point:
    store_name, store_id, prices = price_all_walmart(ingredients, lat, lon)

Self-test:  python walmart_pricing.py
Env: CLOAK_PROXY, WALMART_HTTP_CONCURRENCY, WALMART_WARM_TRIES,
     WALMART_IMPERSONATE, WALMART_POOL_SIZE, WALMART_MAX_IP_REFRESHES,
     WALMART_SEARCH_TTL
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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

def _parse_proxies(raw: Optional[str]) -> list[str]:
    """Split a proxy env value into a pool (comma/whitespace separated) — same
    convention as target_pricing.py, so CLOAK_PROXY works identically everywhere."""
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]

_PROXIES = _parse_proxies(os.environ.get("CLOAK_PROXY") or os.environ.get("WALMART_PROXY"))
_PROXY = _PROXIES[0] if _PROXIES else None  # kept for back-compat truthiness checks
MAX_IP_REFRESHES = int(os.environ.get("WALMART_MAX_IP_REFRESHES", "5"))
_SEARCH_TTL = int(os.environ.get("WALMART_SEARCH_TTL", str(6 * 3600)))

# --- Fast HTTP path (primary) ----------------------------------------------
# PerimeterX validates the caller's TLS/JA3 fingerprint AND a JS-minted cookie
# (_px3). A real browser is only needed to MINT that cookie; once we have it,
# curl_cffi (which impersonates Chrome's exact JA3) can replay the search over
# plain HTTP — fast and parallel, like the ALDI path. Validated: a search-nav
# warm yields a strong cookie that serves a 90-item basket at concurrency 8.
# A burst that's too wide gets throttled, so we cap concurrency and re-mint the
# cookie (re-warm a browser) on a wave of blocks, up to MAX_IP_REFRESHES.
_HTTP_CONCURRENCY = int(os.environ.get("WALMART_HTTP_CONCURRENCY", "8"))
_WARM_TRIES = int(os.environ.get("WALMART_WARM_TRIES", "3"))
_IMPERSONATE = os.environ.get("WALMART_IMPERSONATE", "chrome")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')

_http_session: Optional[dict] = None       # {"cookies": {...}, "ua": str}
_http_lock = threading.Lock()              # serialize warm/re-mint of the session
# Disk cache so the last cookie survives restarts and can be reused next run
# (validated first). PerimeterX _px3 lives minutes, so a short max-age is safe.
_HTTP_SESSION_CACHE = Path(__file__).parent / ".walmart_http_session.json"
_HTTP_COOKIE_TTL = int(os.environ.get("WALMART_COOKIE_TTL", str(20 * 60)))


class _Blocked(Exception):
    """Raised when PerimeterX blocks the request (no __NEXT_DATA__)."""


def is_walmart_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in WALMART_BANNERS)


# ---------------------------------------------------------------------------
# Bandwidth trim for the warm navigation — same technique as coles_pricing.py
# / woolworths_pricing.py. Measured 2026-07-25: walmart.com's warm (home +
# search) is ~6.6MB unblocked, almost entirely a Next.js JS/CSS bundle on
# i5.walmartimages.com loaded twice (once per nav). Blocks images/fonts/media
# and third-party ad-tech outright; caches i5.walmartimages.com's
# content-hashed `_next/static/` chunks via route.fulfill() so the second nav
# reuses them for free instead of re-fetching. Deliberately does NOT touch
# anything on walmart.com itself (where PerimeterX's challenge lives) or
# PerimeterX's own script (px/PXu6b0qd2S/init.js) — only the site's own
# static-asset CDN is cached, same conservative scoping as Woolworths.
# ---------------------------------------------------------------------------
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_BLOCKED_DOMAIN_SUBSTRINGS = (
    "doubleclick", "googletagmanager", "google-analytics", "googlesyndication",
    "googleadservices", "facebook.com", "fbcdn", "fbevents", "adobedtm",
    "demdex", "everesttech", "tealiumiq", "omtrdc", "adsrvr", "tiktok",
    "bing.com/p", "clarity.ms", "hotjar", "criteo", "outbrain", "taboola",
    "spotxchange", "pinterest", "bat.bing",
)
_CACHEABLE_TYPES = {"script", "stylesheet"}
_CACHEABLE_HOST = "i5.walmartimages.com"
_static_asset_cache: dict[str, dict] = {}


def _block_heavy_resources(ctx) -> None:
    def _handle(route):
        req = route.request
        url = req.url.lower()
        if req.resource_type in _BLOCKED_RESOURCE_TYPES or any(
            d in url for d in _BLOCKED_DOMAIN_SUBSTRINGS
        ):
            route.abort()
            return
        if req.resource_type in _CACHEABLE_TYPES and _CACHEABLE_HOST in req.url and "_next/static/" in req.url:
            cached = _static_asset_cache.get(req.url)
            if cached:
                route.fulfill(status=cached["status"], headers=cached["headers"], body=cached["body"])
                return
        route.continue_()
    ctx.route("**/*", _handle)


def _cache_static_assets(resp) -> None:
    req = resp.request
    if (req.resource_type in _CACHEABLE_TYPES and _CACHEABLE_HOST in req.url
            and "_next/static/" in req.url and req.url not in _static_asset_cache):
        try:
            _static_asset_cache[req.url] = {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": resp.body(),
            }
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CloakBrowser worker pool — one browser per worker thread.
# PerimeterX blocks bare fetch() but permits real navigations, and tolerates a
# handful of concurrent browsers from one IP, so Walmart is parallelized by
# splitting the ingredient list across N browsers (one per thread), each
# navigating serially. Browser state is thread-local, so the sync Playwright
# objects are never shared across threads.
# ---------------------------------------------------------------------------

# Worker count for the browser-pool FALLBACK (used only when the primary
# curl_cffi path yields nothing). Default 1: browser_gate now serializes all
# CloakBrowsers to one-at-a-time process-wide, so a pool >1 just spawns extra
# threads that block on the gate — no parallelism gained, only overhead. Bump
# WALMART_POOL_SIZE only if you disable the gate (LOW_MEMORY_MODE=0) on a
# high-RAM host, where real concurrent browsers help a big basket.
_MAX_POOL = int(os.environ.get("WALMART_POOL_SIZE", "1"))
_ITEMS_PER_WORKER = int(os.environ.get("WALMART_ITEMS_PER_WORKER", "12"))
_run_lock = threading.Lock()       # serialize whole-Walmart runs across requests
_thread_local = threading.local()  # per-worker: browser, ctx, proxy_session


def _rotate_proxy_session() -> None:
    _thread_local.proxy_session = os.urandom(6).hex()
    if _PROXIES:
        # Random (not round-robin) so concurrent worker threads in the browser
        # pool naturally spread across different proxies instead of racing a
        # shared cursor.
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


def _bootstrap_session():
    """(worker thread) Launch this thread's CloakBrowser on its proxy session and
    warm PerimeterX cookies via the homepage. Raises on launch failure → Instacart."""
    from browser_gate import launch  # gated: 1 browser at a time + low-mem flags (was cloakbrowser.launch)

    _teardown_session()
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

    ctx = browser.new_context()
    _block_heavy_resources(ctx)
    page = ctx.new_page()
    page.on("response", _cache_static_assets)
    page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
    time.sleep(2)
    page.close()
    _thread_local.browser = browser
    _thread_local.ctx = ctx
    print(f"[Walmart] CloakBrowser worker warmed{' (proxy)' if proxy else ''}.", flush=True)


def _teardown_session():
    browser = getattr(_thread_local, "browser", None)
    try:
        if browser is not None:
            browser.close()
    except Exception:
        pass
    _thread_local.browser = None
    _thread_local.ctx = None


def _ensure_ctx():
    if getattr(_thread_local, "ctx", None) is None:
        _bootstrap_session()
    return _thread_local.ctx


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
    """Return raw Walmart item dicts for a search term. Dispatches to the fast
    curl_cffi path when this thread holds an HTTP session, else the browser path.
    Raises _Blocked when PerimeterX serves a challenge (no __NEXT_DATA__)."""
    http = getattr(_thread_local, "http", None)
    if http is not None:
        return _fetch_items_http(term, http)
    return _fetch_items_browser(term)


def _fetch_items_http(term: str, session: dict) -> list[dict]:
    """(curl_cffi) Replay the search over plain HTTP with the warmed PerimeterX
    cookie + Chrome JA3 impersonation. Raises _Blocked on a challenge."""
    from curl_cffi import requests as _ccffi
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": _WARM_URL,
        "user-agent": session["ua"],
    }
    try:
        resp = _ccffi.get(_SEARCH_URL.format(q=requests_quote(term)),
                          headers=headers, cookies=session["cookies"],
                          impersonate=_IMPERSONATE, timeout=30)
    except Exception as e:
        raise _Blocked(f"http error: {repr(e)[:80]}")
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        # No data blob → PerimeterX challenge / throttle.
        raise _Blocked("no __NEXT_DATA__")
    try:
        return _find_items(json.loads(m.group(1)))
    except Exception:
        return []  # parseable page, just no usable items


def _fetch_items_browser(term: str) -> list[dict]:
    """(worker thread) Load the search page in CloakBrowser, return raw item dicts.
    Raises _Blocked when PerimeterX serves a challenge (no __NEXT_DATA__)."""
    ctx = _ensure_ctx()
    page = ctx.new_page()
    page.on("response", _cache_static_assets)
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


def _extract_price_number(raw) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(raw or "").replace(",", ""))
    if not m:
        return None
    val = float(m.group(1))
    return val if 0.01 <= val <= 500 else None


def _price_from_lineprice(price_info: dict) -> Optional[float]:
    raw = (price_info.get("linePrice") or price_info.get("linePriceDisplay")
           or price_info.get("itemPrice") or "")
    val = _extract_price_number(raw)
    if val is not None:
        return val
    # Walmart migrated to this structure ~2026-07 — the flat linePrice/itemPrice
    # fields now come back as empty strings for every item; the real price
    # lives in priceDetails.priceLines[lineType=CURRENT_PRICE].values[key=PRICE].
    for line in (price_info.get("priceDetails") or {}).get("priceLines") or []:
        if line.get("lineType") != "CURRENT_PRICE":
            continue
        for v in line.get("values") or []:
            if v.get("key") == "PRICE":
                val = _extract_price_number(v.get("value"))
                if val is not None:
                    return val
    return None


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


# ---------------------------------------------------------------------------
# Fast HTTP session: mint PerimeterX cookies with a browser, replay via curl_cffi
# ---------------------------------------------------------------------------

def _warm_http_session() -> dict:
    """Launch CloakBrowser, warm PerimeterX via the homepage + a real search
    navigation (which fully clears the challenge and mints a strong _px3), then
    harvest the cookie jar and user-agent. Raises _Blocked on a weak warm."""
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
        # The search nav (not just the homepage) is what makes PerimeterX fully
        # clear — the difference between a 0/N and an N/N replay rate.
        page.goto(_SEARCH_URL.format(q="eggs"), wait_until="domcontentloaded", timeout=45000)
        nd = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__');"
            " return e ? e.textContent.length : 0; }"
        )
        ua = page.evaluate("() => navigator.userAgent")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    finally:
        try:
            browser.close()
        except Exception:
            pass
    if not nd or nd < 1000:
        raise _Blocked("weak warm — no __NEXT_DATA__")
    return {"cookies": cookies, "ua": ua}


def _save_http_session(session: dict) -> None:
    """Persist the warmed cookie to disk so it survives restarts and can be reused
    next run (validated first) — see try_cached_http_session."""
    try:
        _HTTP_SESSION_CACHE.write_text(json.dumps({
            "cookies": session["cookies"], "ua": session["ua"], "saved_at": time.time(),
        }))
    except Exception:
        pass


def _load_http_session() -> Optional[dict]:
    """Load the disk-cached cookie if it's within the cookie TTL, else None."""
    try:
        d = json.loads(_HTTP_SESSION_CACHE.read_text())
        if time.time() - float(d.get("saved_at", 0)) <= _HTTP_COOKIE_TTL:
            return {"cookies": d["cookies"], "ua": d["ua"]}
    except Exception:
        pass
    return None


def _validate_http_session(session: dict) -> bool:
    """Cheap liveness check (no browser): one curl_cffi search must return
    __NEXT_DATA__. True ⇒ the cookie is still good and can be reused."""
    try:
        _fetch_items_http("eggs", session)  # raises _Blocked on a PerimeterX challenge
        return True
    except Exception:
        return False


def _ensure_http_session() -> dict:
    """Return the shared HTTP session: reuse the in-memory one, else a still-valid
    disk-cached cookie (no browser), else warm a fresh one and persist it."""
    global _http_session
    if _http_session is not None:
        return _http_session
    with _http_lock:
        if _http_session is None:
            cached = _load_http_session()
            if cached and _validate_http_session(cached):
                _http_session = cached
                print("[Walmart] Reused cached HTTP cookie (no warm).", flush=True)
            else:
                last: Optional[Exception] = None
                for _ in range(_WARM_TRIES):
                    try:
                        _http_session = _warm_http_session()
                        _save_http_session(_http_session)
                        print(f"[Walmart] HTTP session warmed (curl_cffi"
                              f"{', proxy' if _PROXY else ''}).", flush=True)
                        break
                    except Exception as e:
                        last = e
                        _rotate_proxy_session()  # fresh exit IP for the next warm
                if _http_session is None:
                    raise _Blocked(f"warm failed after {_WARM_TRIES} tries: {repr(last)[:80]}")
    return _http_session


def try_cached_http_session() -> bool:
    """Validate the last cookie (in-memory or disk) WITHOUT launching a browser and
    activate it if still good. Returns True if a valid session is now ready. Used
    by the early (screen-mount) prewarm: send the last cookie immediately; if it's
    dead, clear it so the address-submit step warms fresh."""
    global _http_session
    with _http_lock:
        candidate = _http_session or _load_http_session()
        if candidate and _validate_http_session(candidate):
            _http_session = candidate
            return True
        _http_session = None  # stale — force a fresh warm next
    return False


def _drop_http_session() -> None:
    """Clear the in-memory session (the disk cache is kept for reuse)."""
    global _http_session
    _http_session = None


def _invalidate_http_session() -> None:
    """Drop the in-memory session AND delete the disk cache — used on a real block
    so the next ensure mints a genuinely fresh cookie (never the bad one)."""
    global _http_session
    _http_session = None
    try:
        _HTTP_SESSION_CACHE.unlink()
    except Exception:
        pass


def _price_via_http(ingredients: dict) -> dict:
    """Primary path: one browser warm, then price every ingredient over parallel
    curl_cffi requests. On a wave of PerimeterX throttles, re-mint the cookie and
    retry just the blocked items, up to MAX_IP_REFRESHES."""
    prices: dict = {}
    pending = dict(ingredients)
    refreshes = 0
    while pending:
        session = _ensure_http_session()

        def _work(item):
            name, data = item
            _thread_local.http = session  # routes _fetch_items → curl_cffi
            try:
                r = _price_one(name, float(data.get("qty", 1) or 1),
                               str(data.get("unit", "whole")))
                return name, r, False
            except _Blocked:
                return name, None, True
            except Exception as e:
                print(f"[Walmart] Error pricing '{name}': {e}", flush=True)
                return name, None, False
            finally:
                _thread_local.http = None

        blocked: dict = {}
        with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(pending)),
                                thread_name_prefix="wm-http") as pool:
            for name, r, was_blocked in pool.map(_work, list(pending.items())):
                if was_blocked:
                    blocked[name] = pending[name]
                elif r:
                    prices[name] = r
        pending = blocked
        if not pending:
            break
        if refreshes >= MAX_IP_REFRESHES:
            print(f"[Walmart] Still throttled after {refreshes} re-mints — "
                  f"{len(pending)} item(s) unpriced.", flush=True)
            break
        refreshes += 1
        print(f"[Walmart] PerimeterX throttle — re-minting session "
              f"(refresh {refreshes}/{MAX_IP_REFRESHES}).", flush=True)
        _invalidate_http_session()  # delete the bad cookie so we warm truly fresh
        _rotate_proxy_session()
        time.sleep(min(1.0 * refreshes, 5.0) + random.uniform(0, 0.75))
    return prices


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

def _price_via_browser_pool(items: list, max_workers: Optional[int] = None) -> dict:
    """Fallback path: split the basket across N CloakBrowser workers (one browser
    each) that navigate concurrently. Used only when the HTTP path yields nothing
    (e.g. PerimeterX starts blocking curl_cffi's JA3 but real renders still pass)."""
    if not items:
        return {}
    if max_workers is not None:
        n_workers = max_workers
    else:
        # Adaptive: one browser per ~_ITEMS_PER_WORKER items, capped at _MAX_POOL.
        n_workers = (len(items) + _ITEMS_PER_WORKER - 1) // _ITEMS_PER_WORKER
        n_workers = min(_MAX_POOL, max(2, n_workers))
    n_workers = max(1, min(n_workers, len(items)))

    # Round-robin split keeps the slices balanced in size.
    slices: list[dict] = [{} for _ in range(n_workers)]
    for i, (name, data) in enumerate(items):
        slices[i % n_workers][name] = data

    def _worker(slice_dict: dict) -> dict:
        try:
            return _do_pricing(slice_dict)
        finally:
            _teardown_session()  # free this worker's browser when its slice is done

    prices: dict = {}
    with ThreadPoolExecutor(max_workers=n_workers,
                            thread_name_prefix="cloak-walmart") as pool:
        for fut in [pool.submit(_worker, s) for s in slices if s]:
            try:
                prices.update(fut.result())
            except Exception as e:
                print(f"[Walmart] Worker failed ({repr(e)[:120]}).", flush=True)
    return prices


def price_all_walmart(
    ingredients: dict,
    lat: float = 0.0,
    lon: float = 0.0,
    max_workers: Optional[int] = None,  # browser-pool fallback override
) -> tuple[Optional[str], Optional[str], dict]:
    """Price all ingredients at Walmart (national online pricing). Primary path is
    fast parallel curl_cffi off a single browser-minted PerimeterX cookie; if that
    yields nothing it falls back to the CloakBrowser pool. Returns
    (display_name, store_id, prices); empty prices → caller uses Instacart."""
    items = list(ingredients.items())
    if not items:
        return "Walmart", _STORE_ID, {}

    with _run_lock:
        # Primary: lightweight curl_cffi path (one browser warm, parallel HTTP).
        try:
            prices = _price_via_http(ingredients)
        except Exception as e:
            print(f"[Walmart] HTTP path unavailable ({repr(e)[:120]}).", flush=True)
            prices = {}
        finally:
            _drop_http_session()

        # Fallback: browser pool, only if HTTP produced nothing at all.
        if prices:
            src = "curl_cffi"
        else:
            print("[Walmart] HTTP path empty — falling back to CloakBrowser pool.", flush=True)
            try:
                prices = _price_via_browser_pool(items, max_workers)
            except Exception as e:
                print(f"[Walmart] Browser pool unavailable ({repr(e)[:120]}) — "
                      "falling back to Instacart.", flush=True)
                prices = {}
            src = "browser pool"

    if not prices:
        return None, None, {}
    print(f"[Walmart] Priced {len(prices)}/{len(ingredients)} ingredients ({src}).", flush=True)
    return "Walmart", _STORE_ID, prices


def shutdown():
    # Each worker tears down its own browser when its slice completes, so there is
    # no persistent session to close between requests.
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
