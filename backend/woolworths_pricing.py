"""
Woolworths (Australia) grocery pricing — direct from woolworths.com.au.

Woolworths exposes a REST JSON search API at `POST /apis/ui/Search/products`
(no HTML scraping needed), fronted by classic Akamai Bot Manager (`_abck` /
`bm_sz` / `ak_bmsc` / `bm_sv` / `bm_s` / `bm_so` cookie family — distinct from
Coles' Imperva `reese84`).

Primary path (fast): a CloakBrowser is used ONLY to mint the Akamai cookie
jar (a homepage + search-nav warm clears the challenge); then we replay the
search over plain HTTP with curl_cffi, which impersonates Chrome's JA3.
Validated 2026-07-24: a browser-warmed cookie jar replays cleanly from a
datacenter IP with zero proxy — same recipe as Coles/Walmart/Target.

KNOWN GAP (bigger than Coles'): unlike Coles, the search request body has no
`storeId`/postcode field — Woolworths resolves the effective fulfillment
store from server-side session state (set via whatever the postcode/delivery
address picker calls, not yet captured), not from a per-request param. So
this module currently prices against whatever DEFAULT store a fresh session
lands on, with no override lever. Fixing that needs a separate DevTools
capture of the "set delivery address" flow, same technique as this file.

Entry point:
    store_name, store_id, prices = price_all_woolworths(ingredients)

Self-test:  python woolworths_pricing.py
Env: CLOAK_PROXY, WOOLWORTHS_HTTP_CONCURRENCY, WOOLWORTHS_WARM_TRIES,
     WOOLWORTHS_IMPERSONATE, WOOLWORTHS_MAX_IP_REFRESHES, WOOLWORTHS_SEARCH_TTL
"""
from __future__ import annotations

import json
import os
import pickle
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

WOOLWORTHS_BANNERS: set[str] = {"woolworths"}
_SEARCH_URL = "https://www.woolworths.com.au/apis/ui/Search/products"
_WARM_URL = "https://www.woolworths.com.au/"
_WARM_SEARCH_URL = "https://www.woolworths.com.au/shop/search/products?searchTerm={q}"
# No store-resolved id today (see module docstring) — placeholder for interface parity.
_STORE_ID = "default"

# Static search-relevance flags captured from a live request 2026-07-24 —
# tuning knobs for Woolworths' semantic search, not session-specific.
_SEARCH_FLAGS = {
    "SemanticSearchModel": "primary",
    "EnableExactMatchExecutor": True,
    "EnableNonStatementExecutor": False,
    "EnablePhraseAssociationExecutor": False,
    "EnableAutocorrectExecutor": False,
    "EnablePartialMatchExecutor": False,
    "EnableSemanticOnlyExecutor": True,
    "SemanticExactMatchMinScore": 7,
    "SemanticNonStatementMinScore": 10,
    "SemanticPhraseAssociationMinScore": 10,
    "SemanticAutocorrectMinScore": 10,
    "SemanticPartialMatchMinScore": 10,
    "SemanticOnlyMinScore": 3,
    "MarketplaceSemanticWeight": "0.7",
    "EnableProductBoostExperiment": True,
    "EnableQueryCategorization": True,
    "QueryCategorizationThreshold": 98,
    "VariantId": "elser1",
}

def _parse_proxies(raw: Optional[str]) -> list[str]:
    """Split a proxy env value into a pool (comma/whitespace separated) — same
    convention as target_pricing.py/walmart_pricing.py/coles_pricing.py."""
    import re as _re
    if not raw:
        return []
    return [p.strip() for p in _re.split(r"[,\s]+", raw) if p.strip()]

_PROXIES = _parse_proxies(os.environ.get("CLOAK_PROXY") or os.environ.get("WOOLWORTHS_PROXY"))
_PROXY = _PROXIES[0] if _PROXIES else None  # kept for back-compat truthiness checks
MAX_IP_REFRESHES = int(os.environ.get("WOOLWORTHS_MAX_IP_REFRESHES", "5"))
_SEARCH_TTL = int(os.environ.get("WOOLWORTHS_SEARCH_TTL", str(6 * 3600)))

_HTTP_CONCURRENCY = int(os.environ.get("WOOLWORTHS_HTTP_CONCURRENCY", "8"))
_WARM_TRIES = int(os.environ.get("WOOLWORTHS_WARM_TRIES", "3"))
_IMPERSONATE = os.environ.get("WOOLWORTHS_IMPERSONATE", "chrome")

_http_session: Optional[dict] = None
_http_lock = threading.Lock()
_HTTP_SESSION_CACHE = Path(__file__).parent / ".woolworths_http_session.json"
_HTTP_COOKIE_TTL = int(os.environ.get("WOOLWORTHS_COOKIE_TTL", str(60 * 60)))
_STATIC_ASSET_CACHE_PATH = Path(__file__).parent / ".woolworths_asset_cache.pkl"


class _Blocked(Exception):
    """Raised when Akamai blocks/challenges the request."""


def is_woolworths_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in WOOLWORTHS_BANNERS)


# ---------------------------------------------------------------------------
# Bandwidth trim for the warm navigation — see coles_pricing.py for the same
# helper and the measured rationale (~30.6MB -> a few MB per warm pair).
# ---------------------------------------------------------------------------
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_BLOCKED_DOMAIN_SUBSTRINGS = (
    "doubleclick", "googletagmanager", "google-analytics", "googlesyndication",
    "googleadservices", "facebook.com", "fbcdn", "fbevents", "adobedtm",
    "demdex", "everesttech", "tealiumiq", "omtrdc", "adsrvr", "tiktok",
    "bing.com/p", "clarity.ms", "hotjar", "criteo", "outbrain", "taboola",
    "spotxchange", "pinterest", "bat.bing",
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
        if req.resource_type in _CACHEABLE_TYPES and _CACHEABLE_HOST in req.url:
            cached = _static_asset_cache.get(req.url)
            if cached:
                route.fulfill(status=cached["status"], headers=cached["headers"], body=cached["body"])
                return
        route.continue_()
    ctx.route("**/*", _handle)


# Static JS/CSS assets are hosted on a separate CDN (cdn1.woolworths.media),
# content-hashed and safe to cache indefinitely — see coles_pricing.py for the
# same technique. Deliberately scoped to ONLY that CDN host: the main
# www.woolworths.com.au origin (Akamai-fronted) serves oddly-obfuscated script
# paths that look session-specific, and reusing cached bytes from a different
# session there risks interfering with the Akamai challenge rather than just
# being ineffective — not worth the risk for a much smaller payoff anyway.
_CACHEABLE_TYPES = {"script", "stylesheet"}
_CACHEABLE_HOST = "cdn1.woolworths.media"
def _load_asset_cache() -> dict:
    try:
        with open(_STATIC_ASSET_CACHE_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _save_asset_cache() -> None:
    try:
        with open(_STATIC_ASSET_CACHE_PATH, "wb") as f:
            pickle.dump(_static_asset_cache, f)
    except Exception:
        pass


_static_asset_cache = _load_asset_cache()


def _cache_static_assets(resp) -> None:
    req = resp.request
    if req.resource_type in _CACHEABLE_TYPES and _CACHEABLE_HOST in req.url and req.url not in _static_asset_cache:
        try:
            _static_asset_cache[req.url] = {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": resp.body(),
            }
            _save_asset_cache()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CloakBrowser warm — mint the Akamai cookie jar (_abck, bm_sz, ak_bmsc, ...)
# ---------------------------------------------------------------------------

_run_lock = threading.Lock()
_thread_local = threading.local()


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
    """Launch CloakBrowser, warm Akamai via the homepage + a real search
    navigation, then harvest the full cookie jar and user-agent."""
    from browser_gate import launch_geoip_optional  # gated: 1 browser at a time + low-mem flags
    if getattr(_thread_local, "proxy_session", None) is None:
        _rotate_proxy_session()
    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True
    browser = launch_geoip_optional(**kwargs)
    try:
        ctx = browser.new_context()
        _block_heavy_resources(ctx)
        page = ctx.new_page()
        page.on("response", _cache_static_assets)
        page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        page.goto(_WARM_SEARCH_URL.format(q="milk"), wait_until="domcontentloaded", timeout=45000)
        time.sleep(1)
        ua = page.evaluate("() => navigator.userAgent")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    finally:
        try:
            browser.close()
        except Exception:
            pass
    if "_abck" not in cookies or "bm_sz" not in cookies:
        raise _Blocked("weak warm — Akamai cookies not minted")
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


def _validate_http_session(session: dict) -> bool:
    try:
        _fetch_products_http("eggs", session)
        return True
    except Exception:
        return False


def _load_remote_session() -> Optional[dict]:
    """Off-box cookie from Supabase (published by mint_sessions.py on GitHub
    Actions). None if unavailable/stale — caller falls back to disk/warm."""
    try:
        import session_store
        return session_store.load("woolworths")
    except Exception:
        return None


def _ensure_http_session() -> dict:
    global _http_session
    if _http_session is not None:
        return _http_session
    with _http_lock:
        if _http_session is None:
            # Off-box cookie (GitHub Actions -> Supabase) first, then disk, then warm.
            cached = _load_remote_session()
            if cached and _validate_http_session(cached):
                _http_session = cached
                print("[Woolworths] Reused off-box cookie (Supabase, no warm).", flush=True)
            elif (cached := _load_http_session()) and _validate_http_session(cached):
                _http_session = cached
                print("[Woolworths] Reused cached HTTP cookie (no warm).", flush=True)
            else:
                last: Optional[Exception] = None
                for _ in range(_WARM_TRIES):
                    try:
                        _http_session = _warm_http_session()
                        _save_http_session(_http_session)
                        print(f"[Woolworths] HTTP session warmed (curl_cffi"
                              f"{', proxy' if _PROXIES else ''}).", flush=True)
                        break
                    except Exception as e:
                        last = e
                        _rotate_proxy_session()
                if _http_session is None:
                    raise _Blocked(f"warm failed after {_WARM_TRIES} tries: {repr(last)[:80]}")
    return _http_session


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

def _fetch_products_http(term: str, session: dict) -> list[dict]:
    """Replay the search over plain HTTP with the warmed Akamai cookie jar +
    Chrome JA3 impersonation. Raises _Blocked on a challenge/block."""
    from curl_cffi import requests as _ccffi
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": "https://www.woolworths.com.au",
        "referer": _WARM_SEARCH_URL.format(q=term),
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": session["ua"],
    }
    body = {
        "EnableAdReRanking": False,
        "ExcludeSearchTypes": ["UntraceableVendors"],
        "Filters": [],
        "GpBoost": 0,
        "IsHideEverydayMarketProducts": False,
        "IsHideUnavailableProducts": False,
        "IsRegisteredRewardCardPromotion": False,
        "IsSpecial": False,
        "Location": f"/shop/search/products?searchTerm={term}",
        "PageNumber": 1,
        "PageSize": 24,
        "SearchTerm": term,
        "SortType": "TraderRelevance",
        "flags": _SEARCH_FLAGS,
    }
    try:
        resp = _ccffi.post(_SEARCH_URL, headers=headers, cookies=session["cookies"],
                            json=body, impersonate=_IMPERSONATE, timeout=30)
    except Exception as e:
        raise _Blocked(f"http error: {repr(e)[:80]}")

    if resp.status_code in (401, 403, 429):
        raise _Blocked(f"status {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        raise _Blocked("non-JSON response")  # Akamai challenge/captcha page

    if resp.status_code != 200:
        print(f"[Woolworths] '{term}' request error: status {resp.status_code}", flush=True)
        return []

    # Response groups products (variants of the same item) — flatten to a
    # single item list.
    items: list[dict] = []
    for group in data.get("Products") or []:
        items.extend(group.get("Products") or [])
    return items


# ---------------------------------------------------------------------------
# Item → shared "Kroger format" (consumed by find_best_purchase)
# ---------------------------------------------------------------------------

def _item_to_kroger_format(item: dict) -> Optional[dict]:
    name = item.get("Name") or ""
    if not name or not item.get("IsAvailable", True):
        return None
    price = item.get("Price")
    if price is None or not (0.01 <= price <= 500):
        return None

    unit = (item.get("Unit") or "").lower()
    is_weighted = "kg" in unit or "100g" in unit
    size = item.get("PackageSize") or ("1 kg" if is_weighted else "1 each")

    return {
        "description": name,
        "brand": item.get("Brand") or "",
        "items": [{
            "itemId": str(item.get("Stockcode") or ""),
            "soldBy": "WEIGHT" if is_weighted else "UNIT",
            "size": size,
            "price": {"regular": float(price), "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Search (cached) + per-ingredient pricing
# ---------------------------------------------------------------------------

_search_cache: dict[str, tuple[float, list[dict]]] = {}


def _search(term: str) -> list[dict]:
    cached = _search_cache.get(term.lower())
    if cached and cached[0] > time.time():
        return cached[1]

    session = _ensure_http_session()
    raw = _fetch_products_http(term, session)
    query_words = set(term.lower().split())
    out = []
    for it in raw:
        fmt = _item_to_kroger_format(it)
        if fmt and any(w in fmt["description"].lower() for w in query_words):
            out.append(fmt)
    if not out:
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


def _price_via_http(ingredients: dict) -> dict:
    """One browser warm, then price every ingredient over parallel curl_cffi
    requests. On a wave of Akamai throttles, re-mint the cookie and retry
    just the blocked items, up to MAX_IP_REFRESHES."""
    prices: dict = {}
    pending = dict(ingredients)
    refreshes = 0
    while pending:
        _ensure_http_session()

        def _work(item):
            name, data = item
            try:
                r = _price_one(name, float(data.get("qty", 1) or 1),
                                str(data.get("unit", "whole")))
                return name, r, False
            except _Blocked:
                return name, None, True
            except Exception as e:
                print(f"[Woolworths] Error pricing '{name}': {e}", flush=True)
                return name, None, False

        blocked: dict = {}
        with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(pending)),
                                thread_name_prefix="wow-http") as pool:
            for name, r, was_blocked in pool.map(_work, list(pending.items())):
                if was_blocked:
                    blocked[name] = pending[name]
                elif r:
                    prices[name] = r
        pending = blocked
        if not pending:
            break
        if refreshes >= MAX_IP_REFRESHES:
            print(f"[Woolworths] Still throttled after {refreshes} re-mints — "
                  f"{len(pending)} item(s) unpriced.", flush=True)
            break
        refreshes += 1
        print(f"[Woolworths] Akamai throttle — re-minting session "
              f"(refresh {refreshes}/{MAX_IP_REFRESHES}).", flush=True)
        _invalidate_http_session()
        _rotate_proxy_session()
        time.sleep(min(1.0 * refreshes, 5.0) + random.uniform(0, 0.75))
    return prices


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_woolworths(
    ingredients: dict,
    lat: float = 0.0,
    lon: float = 0.0,
) -> tuple[Optional[str], Optional[str], dict]:
    """Price all ingredients at Woolworths' default session store (see module
    docstring — there is no store override lever yet)."""
    items = list(ingredients.items())
    if not items:
        return "Woolworths", _STORE_ID, {}

    with _run_lock:
        try:
            prices = _price_via_http(ingredients)
        except Exception as e:
            print(f"[Woolworths] HTTP path unavailable ({repr(e)[:120]}).", flush=True)
            prices = {}
        finally:
            _drop_http_session()

    if not prices:
        return None, None, {}
    print(f"[Woolworths] Priced {len(prices)}/{len(ingredients)} ingredients.", flush=True)
    return "Woolworths", _STORE_ID, prices


def shutdown() -> None:
    pass


# ---------------------------------------------------------------------------
# Self-test:  python woolworths_pricing.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample = {
        "milk":           {"qty": 2, "unit": "litre"},
        "eggs":           {"qty": 12, "unit": "count"},
        "bananas":        {"qty": 1, "unit": "kg"},
        "chicken breast": {"qty": 1, "unit": "kg"},
        "white rice":     {"qty": 1, "unit": "kg"},
    }
    name, sid, out = price_all_woolworths(sample)
    print(f"\n=== {name} ({sid}) ===")
    if not out:
        print("No prices — CloakBrowser unavailable or Akamai-blocked.")
    for ing, res in out.items():
        print(f"  {ing:16s} ${res.get('total_cost', 0):7.2f}  "
              f"{res.get('description', '')[:40]} ({res.get('size_str', '')})")
    shutdown()
