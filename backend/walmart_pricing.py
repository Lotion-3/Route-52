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

Session sourcing: a pool of pre-minted cookies (.minted_walmart_cookies.json)
is tried FIRST, before ever launching a browser — see _next_pool_session().
Only once every pool cookie is individually confirmed dead does this module
fall back to the Supabase/disk-cache/CloakBrowser-mint chain. Mirrors
target_pricing.py's pool, same reasoning: minting is the fragile, slow step.

Store scoping: confirmed (2026-07-30) that Walmart pricing has no accessible
store-selection mechanism via this replay method — overriding the
`assortmentStoreId` cookie to different real store IDs produced byte-for-byte
identical product listings. Pricing here is genuinely national, matching
_STORE_ID = "national" below; whatever assortment/pricing Walmart's backend
defaults to for a session is what gets returned, not something this module
can steer per-request.

Entry point:
    store_name, store_id, prices = price_all_walmart(ingredients, lat, lon)

Self-test:  python walmart_pricing.py
Env: CLOAK_PROXY, WALMART_HTTP_CONCURRENCY, WALMART_WARM_TRIES,
     WALMART_IMPERSONATE, WALMART_POOL_SIZE, WALMART_MAX_IP_REFRESHES,
     WALMART_SEARCH_TTL, WALMART_COOKIE_POOL_FILE (path to the pool JSON
     tried before the mint chain; set to "" to disable the pool)
"""
from __future__ import annotations

import json
import os
import pickle
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

# Every warm/validate search used to hit the literal same term ("eggs"), every
# time, from every session — a real shopper searches varied things, so always
# searching one fixed word is itself a cross-session pattern a WAF can
# correlate even when each individual session's navigation looks clean.
# Picking a random common grocery term each time doesn't change the mechanics
# of the warm at all — it's still a real search-results page — it just removes
# that one repeating fingerprint.
_WARM_SEARCH_TERMS = (
    "eggs", "milk", "bread", "bananas", "chicken breast", "butter",
    "cheese", "rice", "coffee", "apples", "yogurt", "ground beef",
)


def _random_search_term() -> str:
    return random.choice(_WARM_SEARCH_TERMS)

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
# A transport-only failure (timeout/DNS/connection reset — see _Blocked) isn't
# a WAF signal, so it gets its own small retry budget on the SAME IP instead of
# burning one of the MAX_IP_REFRESHES rotation slots.
_TRANSPORT_RETRIES = int(os.environ.get("WALMART_TRANSPORT_RETRIES", "2"))


def _log_block(category: str, detail: str = "") -> None:
    """Best-effort: publish a block/failure event to Supabase for later
    analysis (see session_store.log_block_event). Never raises, never blocks
    retry logic on Supabase being slow/unavailable beyond the one call."""
    try:
        import session_store
        session_store.log_block_event("walmart", category, detail)
    except Exception:
        pass

# --- Fast HTTP path (primary) ----------------------------------------------
# PerimeterX validates the caller's TLS/JA3 fingerprint AND a JS-minted cookie
# (_px3). A real browser is only needed to MINT that cookie; once we have it,
# curl_cffi (which impersonates Chrome's exact JA3) can replay the search over
# plain HTTP — fast and parallel, like the ALDI path.
#
# Concurrency ceiling confirmed empirically (test_walmart_concurrency_matrix.py,
# 8 trials across 8 fresh cookies, 2026-07-30): the limit is a HARD, INSTANT
# cap on simultaneous requests per cookie, not a total-item-count or
# cumulative-volume limit. 20 concurrent always succeeded (including 40 total
# items split across two 20-wide waves, and 30 total items at concurrency 5);
# 21, 22, 23, 25, and 30 concurrent ALL failed completely and immediately —
# every request in the burst blocked, including the very first one submitted.
# The wall is exactly 20. Default here is 18 (a small safety margin below the
# confirmed-clean ceiling, not the wall itself) — repeatedly crossing the wall
# during that testing escalated into a longer-lived IP-level block (confirmed:
# a fresh, never-used cookie still failed from the same IP afterward, but
# worked immediately when replayed through a different exit), so production
# must never intentionally test that edge.
_HTTP_CONCURRENCY = int(os.environ.get("WALMART_HTTP_CONCURRENCY", "18"))
# 2 (was 3): each warm holds the one shared browser gate for ~30-45s on a slow
# host; 3 tries could hog it long enough to time out every other chain waiting
# behind it. Fail to fallback a try sooner.
_WARM_TRIES = int(os.environ.get("WALMART_WARM_TRIES", "2"))
_IMPERSONATE = os.environ.get("WALMART_IMPERSONATE", "chrome")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')

_http_session: Optional[dict] = None       # {"cookies": {...}, "ua": str}
_http_lock = threading.Lock()              # serialize warm/re-mint of the session
_session_source: Optional[str] = None      # "pool" | "fallback" — origin of _http_session
# Disk cache so the last cookie survives restarts and can be reused next run
# (validated first). PerimeterX _px3 lives minutes, so a short max-age is safe.
_HTTP_SESSION_CACHE = Path(__file__).parent / ".walmart_http_session.json"
_HTTP_COOKIE_TTL = int(os.environ.get("WALMART_COOKIE_TTL", str(60 * 60)))
_STATIC_ASSET_CACHE_PATH = Path(__file__).parent / ".walmart_asset_cache.pkl"

# Pool of pre-minted cookies (backend/.minted_walmart_cookies.json) tried
# BEFORE the remote/disk/warm chain below — see _next_pool_session(). Mirrors
# target_pricing.py's pool, added after target_pricing.py's cookies were
# empirically confirmed to survive 27+ hours, far past _HTTP_COOKIE_TTL.
# Set WALMART_COOKIE_POOL_FILE="" to disable the pool and restore old behavior.
_env_pool_file = os.environ.get("WALMART_COOKIE_POOL_FILE")
if _env_pool_file is not None:
    _COOKIE_POOL_FILE = Path(_env_pool_file) if _env_pool_file else None
else:
    _COOKIE_POOL_FILE = Path(__file__).parent / ".minted_walmart_cookies.json"
_pool_idx: int = 0             # cursor into _cookie_pool; persists for process lifetime
_pool_exhausted_logged = False # warn-once guard, mirrors the no-proxy warning pattern


def _load_cookie_pool() -> list[dict]:
    """Load the pool once at import. Missing/malformed file degrades to an
    empty pool — _next_pool_session() then always returns None immediately,
    so _ensure_http_session() falls straight through to the existing
    remote/disk/warm chain, exactly like before this pool existed."""
    if _COOKIE_POOL_FILE is None:
        return []
    try:
        raw = json.loads(_COOKIE_POOL_FILE.read_text())
    except FileNotFoundError:
        print(f"[Walmart] No cookie pool file at {_COOKIE_POOL_FILE} — "
              "skipping straight to remote/disk/warm.", flush=True)
        return []
    except Exception as e:
        print(f"[Walmart] Cookie pool file unreadable ({repr(e)[:100]}) — "
              "skipping straight to remote/disk/warm.", flush=True)
        return []
    if not isinstance(raw, list):
        print("[Walmart] Cookie pool file is not a JSON array — ignoring.", flush=True)
        return []
    pool = []
    for i, entry in enumerate(raw):
        if isinstance(entry, dict) and entry.get("cookies") and entry.get("ua"):
            pool.append(entry)
        else:
            print(f"[Walmart] Cookie pool entry #{i + 1} missing cookies/ua — skipped.", flush=True)
    print(f"[Walmart] Loaded {len(pool)} pooled cookie(s) from {_COOKIE_POOL_FILE.name}.", flush=True)
    return pool


_cookie_pool: list[dict] = _load_cookie_pool()


class _Blocked(Exception):
    """Raised when a request comes back wrong. `category` distinguishes WHY,
    verified empirically (test_direct_search.py + a curl_cffi replay
    investigation against live Walmart, both good and blocked sessions):

      "explicit"  — an unambiguous PerimeterX marker was found in the body
                    (e.g. "px-captcha"). Confirmed via curl_cffi replay: this
                    string is present in every blocked response and absent
                    from every good one — status code is NOT useful for this
                    (blocked responses are still HTTP 200).
      "soft"      — no explicit marker, but the content looks wrong anyway
                    (missing/short __NEXT_DATA__). Weaker evidence than
                    "explicit" — could in principle be something else — but
                    still a real signal.
      "transport" — no HTTP response was ever received at all (timeout, DNS,
                    connection reset, TLS failure). NOT a WAF signal — this
                    can happen on a perfectly good IP/session, so callers
                    should not spend an IP-rotation slot reacting to it.

    Only "explicit"/"soft" should trigger a fresh exit IP; "transport" should
    just retry the same session/IP a couple of times first."""
    def __init__(self, message: str = "", category: str = "soft"):
        super().__init__(message)
        self.category = category


# Confirmed by direct comparison of a good vs. a blocked response body — see
# _Blocked's docstring. Generic words like "captcha"/"human"/"blocked" show up
# in the REAL page too (it legitimately references PerimeterX by name), so
# only this specific, product-named marker is trustworthy on its own.
_EXPLICIT_BLOCK_MARKERS = ("px-captcha",)


def _has_explicit_block_marker(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _EXPLICIT_BLOCK_MARKERS)


def is_walmart_store(store_name: str) -> bool:
    return any(b in store_name.lower() for b in WALMART_BANNERS)


# ---------------------------------------------------------------------------
# Bandwidth trim for the warm navigation. Measured 2026-07-25: walmart.com's warm (home +
# search) is ~6.6MB unblocked, almost entirely a Next.js JS/CSS bundle on
# i5.walmartimages.com loaded twice (once per nav). Blocks images/fonts/media
# and third-party ad-tech outright; caches i5.walmartimages.com's
# content-hashed `_next/static/` chunks via route.fulfill() so the second nav
# reuses them for free instead of re-fetching. Deliberately does NOT touch
# anything on walmart.com itself (where PerimeterX's challenge lives) or
# PerimeterX's own script (px/PXu6b0qd2S/init.js) — only the site's own
# static-asset CDN is cached, same conservative scoping as Woolworths.
# ---------------------------------------------------------------------------
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
_BLOCKED_DOMAIN_SUBSTRINGS = (
    "doubleclick", "googletagmanager", "google-analytics", "googlesyndication",
    "googleadservices", "facebook.com", "fbcdn", "fbevents", "adobedtm",
    "demdex", "everesttech", "tealiumiq", "omtrdc", "adsrvr", "tiktok",
    "bing.com/p", "clarity.ms", "hotjar", "criteo", "outbrain", "taboola",
    "spotxchange", "pinterest", "bat.bing",
)
# CSS is never needed to execute the WAF's JS challenge, only to render a page
# nobody looks at — blocked outright above rather than fetched-then-cached.
_CACHEABLE_TYPES = {"script"}
_CACHEABLE_HOST = "i5.walmartimages.com"


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

_PRE_SEED_CACHE_RE = re.compile(r'(/_next/static/[^"\']+\.(?:js|css))')
_PRE_SEED_URL = _WARM_URL


def _pre_seed_asset_cache() -> None:
    """Download static JS/CSS assets from _CACHEABLE_HOST outside the browser
    using curl_cffi and populate _static_asset_cache. This lets the browser warm
    phase serve cached assets via route.fulfill() without ever hitting the CDN.

    Handles cache freshness by comparing expected URLs (from the current HTML)
    against the cached keys — stale entries from previous deploys are pruned
    and new entries are fetched.

    NOT called on Render (see _load_remote_asset_cache below) — this makes a
    handful of live network requests, which is exactly the kind of work the
    512MB host shouldn't be doing at boot. mint_sessions.py calls this on the
    GitHub Actions runner instead and publishes the result to Supabase.
    """
    try:
        from curl_cffi import requests as ccffi
        resp = ccffi.get(_PRE_SEED_URL, impersonate=_IMPERSONATE, timeout=15)
        if resp.status_code != 200:
            return
        expected = {"https://" + _CACHEABLE_HOST + m.group(1) for m in _PRE_SEED_CACHE_RE.finditer(resp.text)}
        if not expected:
            return
        stale = set(_static_asset_cache) - expected
        if stale:
            for k in stale:
                _static_asset_cache.pop(k, None)
        missing = expected - set(_static_asset_cache)
        if not missing and not stale:
            return
        for url in sorted(missing):
            try:
                asset = ccffi.get(url, impersonate=_IMPERSONATE, timeout=15)
                _static_asset_cache[url] = {
                    "status": asset.status_code,
                    "headers": {"content-type": "text/css" if url.endswith(".css") else "text/javascript"},
                    "body": asset.content,
                }
            except Exception:
                pass
        _save_asset_cache()
        print(f"[Walmart] Pre-seeded {len(_static_asset_cache)} static assets"
              f" ({'pruned ' + str(len(stale)) + ' stale, ' if stale else ''}"
              f"{len(missing)} new)", flush=True)
    except Exception as e:
        print(f"[Walmart] Pre-seed failed ({e}) — fallback to browser download", flush=True)


def _load_remote_asset_cache() -> None:
    """Pull the already-pre-fetched asset cache from Supabase (published by
    mint_sessions.py on GitHub Actions) and merge it into _static_asset_cache.
    A single cheap DB read — no CDN calls, no curl_cffi burst, safe to run on
    every Render boot. Falls back to whatever's on disk / gets cached
    organically by _cache_static_assets during a real browser warm if Supabase
    has nothing yet."""
    try:
        import session_store
        remote = session_store.load_assets("walmart")
        if remote:
            _static_asset_cache.update(remote)
            _save_asset_cache()
            print(f"[Walmart] Loaded {len(remote)} pre-fetched assets from Supabase.", flush=True)
    except Exception as e:
        print(f"[Walmart] Remote asset cache load failed ({repr(e)[:80]}).", flush=True)


_load_remote_asset_cache()


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
            _save_asset_cache()
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


def _rotate_to_unused_proxy(tried_idxs: set[int]) -> bool:
    """Switch to a proxy index NOT already in `tried_idxs` (mutated in place
    with the new pick) — an IP that just failed is never retried in the same
    run. Returns False once min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs
    have already been tried (or MAX_IP_REFRESHES attempts with no pool
    configured at all); the caller should give up rather than call this again,
    since there's nothing new left to try."""
    _thread_local.proxy_session = os.urandom(6).hex()
    cap = min(MAX_IP_REFRESHES, len(_PROXIES)) if _PROXIES else MAX_IP_REFRESHES
    if len(tried_idxs) >= cap:
        return False
    if not _PROXIES:
        tried_idxs.add(len(tried_idxs))  # no real pool to index — just bound the attempt count
        return True
    available = [i for i in range(len(_PROXIES)) if i not in tried_idxs]
    if not available:
        return False
    idx = random.choice(available)
    tried_idxs.add(idx)
    _thread_local.proxy_idx = idx
    return True


def _wait_for_cookie(ctx, cookie_name: str, cap_seconds: float,
                      poll_interval: float = 0.15, settle_ticks: int = 2) -> bool:
    """Poll ctx.cookies() instead of a fixed sleep, so a warm that clears in
    300ms doesn't still hold the browser gate for the full cap_seconds.

    Requires TWO things, not one: `cookie_name` must be present, AND the total
    cookie count must have stopped growing for `settle_ticks` consecutive polls.
    A single named cookie showing up isn't enough on its own — we proved this
    empirically (test_direct_search.py): _px3 was present in BOTH the working
    warm and the one that came back with an empty page. PerimeterX sets a whole
    family of cookies together as its challenge resolves (_px3, _pxde, _pxhd,
    _pxvid, pxcts, plus trackers) — waiting for that set to stop growing is a
    materially stronger signal that the challenge has actually finished, not
    just started, without hardcoding the exact cookie names (which the vendor
    can change) beyond the one anchor we need present either way.

    Returns True once settled, False if the cap elapses first — the caller
    proceeds anyway exactly as it did with the old fixed sleep. This never
    provides the actual safety guarantee by itself: it only reads the browser's
    already-downloaded cookie jar (no requests, no bandwidth cost), and a warm
    that's still weak despite settling is caught downstream regardless (Walmart
    checks __NEXT_DATA__ length; Target does a live RedSky call) — that
    downstream check, not this wait, is what guarantees a bad warm never
    silently succeeds."""
    deadline = time.monotonic() + cap_seconds
    last_count = -1
    stable_ticks = 0
    while time.monotonic() < deadline:
        names = {c["name"] for c in ctx.cookies()}
        count = len(names)
        stable_ticks = stable_ticks + 1 if count == last_count else 0
        last_count = count
        if cookie_name in names and stable_ticks >= settle_ticks:
            return True
        time.sleep(poll_interval)
    return False


def _bootstrap_session():
    """(worker thread) Launch this thread's CloakBrowser on its proxy session and
    warm PerimeterX cookies via the homepage. Raises on launch failure → Instacart."""
    from browser_gate import launch_geoip_optional  # gated: 1 browser at a time + low-mem flags

    _teardown_session()
    if getattr(_thread_local, "proxy_session", None) is None:
        _rotate_proxy_session()

    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True
    browser = launch_geoip_optional(**kwargs)

    # The browser is only handed to _thread_local once the warm SUCCEEDS, so a
    # failure here must close it explicitly — otherwise nothing ever calls
    # .close() and the browser gate stays held until the max-hold backstop.
    try:
        ctx = browser.new_context()
        _block_heavy_resources(ctx)
        page = ctx.new_page()
        page.on("response", _cache_static_assets)
        page.goto(_WARM_URL, wait_until="domcontentloaded", timeout=45000)
        _wait_for_cookie(ctx, "_px3", 2)
        page.close()
    except BaseException:
        try:
            browser.close()
        except Exception:
            pass
        raise

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
        # Never reached the site at all — not a WAF signal (see _Blocked).
        raise _Blocked(f"http error: {repr(e)[:80]}", category="transport")
    if _has_explicit_block_marker(resp.text):
        raise _Blocked("px-captcha marker", category="explicit")
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        # No data blob and no explicit marker — probably still a challenge,
        # but weaker evidence than finding the marker directly.
        raise _Blocked("no __NEXT_DATA__", category="soft")
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
        html = page.content()  # local DOM read, not a network request — see _wait_for_cookie
        nd = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__');"
            " return e ? e.textContent : null; }"
        )
    except Exception as e:
        # Never got a rendered page at all — not a WAF signal (see _Blocked).
        raise _Blocked(f"page load failed: {repr(e)[:80]}", category="transport")
    finally:
        try:
            page.close()
        except Exception:
            pass

    if _has_explicit_block_marker(html):
        raise _Blocked("px-captcha marker", category="explicit")
    if not nd:
        # No data blob and no explicit marker — probably still a challenge,
        # but weaker evidence than finding the marker directly.
        raise _Blocked("no __NEXT_DATA__", category="soft")
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
        _wait_for_cookie(ctx, "_px3", 2)
        # The search nav (not just the homepage) is what makes PerimeterX fully
        # clear — the difference between a 0/N and an N/N replay rate. The term
        # itself is randomized (see _WARM_SEARCH_TERMS) so it's not always "eggs".
        page.goto(_SEARCH_URL.format(q=_random_search_term()), wait_until="domcontentloaded", timeout=45000)
        html = page.content()  # local DOM read, not a network request — see _wait_for_cookie
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
    if _has_explicit_block_marker(html):
        raise _Blocked("px-captcha marker on warm", category="explicit")
    if not nd or nd < 1000:
        raise _Blocked("weak warm — no __NEXT_DATA__", category="soft")
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
        _fetch_items_http(_random_search_term(), session)  # raises _Blocked on a challenge
        return True
    except Exception:
        return False


def _load_remote_session() -> Optional[dict]:
    """Off-box cookie from Supabase (published by mint_sessions.py on GitHub
    Actions). None if unavailable/stale — caller falls back to disk/warm, so
    this is a pure speedup, never a hard dependency."""
    try:
        import session_store
        return session_store.load("walmart")
    except Exception:
        return None


def _next_pool_session() -> Optional[dict]:
    """(caller holds _http_lock) Return the first pool cookie at/after
    _pool_idx that passes a live validate, advancing _pool_idx past any dead
    ones along the way. None once the whole pool has been exhausted this
    process — caller falls through to the remote/disk/warm chain."""
    global _pool_idx, _pool_exhausted_logged
    n = len(_cookie_pool)
    while _pool_idx < n:
        candidate = _cookie_pool[_pool_idx]
        if _validate_http_session(candidate):
            print(f"[Walmart] Using pool cookie #{_pool_idx + 1}/{n} "
                  f"(saved {candidate.get('saved_at_iso', '?')}).", flush=True)
            return candidate
        print(f"[Walmart] Pool cookie #{_pool_idx + 1}/{n} is dead — advancing.", flush=True)
        _pool_idx += 1
    if n and not _pool_exhausted_logged:
        _pool_exhausted_logged = True
        print(f"[Walmart] Cookie pool exhausted ({n}/{n} dead) — "
              "falling back to remote/disk/warm from now on.", flush=True)
    return None


def _ensure_http_session() -> dict:
    """Return the shared HTTP session: reuse the in-memory one, else the next
    live cookie from the saved pool (see _next_pool_session), else a
    still-valid disk-cached cookie (no browser), else warm a fresh one and
    persist it. Minting is reached ONLY once every pool cookie has been
    individually confirmed dead."""
    global _http_session, _session_source
    if _http_session is not None:
        return _http_session
    with _http_lock:
        if _http_session is None:
            pool_session = _next_pool_session()
            if pool_session is not None:
                _http_session = pool_session
                _session_source = "pool"
                return _http_session

            # Off-box cookie (GitHub Actions -> Supabase) first, so the 512MB
            # server skips launching a browser; then disk; then warm here.
            cached = _load_remote_session()
            if cached and _validate_http_session(cached):
                _http_session = cached
                _session_source = "fallback"
                print("[Walmart] Reused off-box cookie (Supabase, no warm).", flush=True)
            elif (cached := _load_http_session()) and _validate_http_session(cached):
                _http_session = cached
                _session_source = "fallback"
                print("[Walmart] Reused cached HTTP cookie (no warm).", flush=True)
            else:
                last: Optional[Exception] = None
                for _ in range(_WARM_TRIES):
                    try:
                        _http_session = _warm_http_session()
                        _session_source = "fallback"
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
    global _http_session, _session_source
    with _http_lock:
        candidate = _http_session or _load_http_session()
        if candidate and _validate_http_session(candidate):
            _http_session = candidate
            if _session_source is None:
                _session_source = "fallback"
            return True
        _http_session = None  # stale — force a fresh warm next
        _session_source = None
    return False


def _drop_http_session() -> None:
    """Clear the in-memory session (the disk cache is kept for reuse)."""
    global _http_session, _session_source
    _http_session = None
    _session_source = None


def _invalidate_http_session() -> None:
    """Drop the in-memory session. Pool-sourced: just advance the pool cursor
    past the dead entry — disk cache is untouched (pool cookies are never
    written there) and no proxy rotation is triggered (switching pool cookies
    involves no browser re-warm, so there's no future warm's IP to prep by
    rotating). Fallback-sourced: unchanged — delete the disk cache too, so
    the next ensure mints a genuinely fresh cookie (never the bad one)."""
    global _http_session, _session_source, _pool_idx
    with _http_lock:
        if _session_source == "pool":
            _pool_idx += 1
        else:
            try:
                _HTTP_SESSION_CACHE.unlink()
            except Exception:
                pass
        _http_session = None
        _session_source = None


def _price_via_http(ingredients: dict) -> dict:
    """Primary path: one browser warm, then price every ingredient over parallel
    curl_cffi requests. A round where anything came back with a WAF-category
    block (explicit marker or soft signal — see _Blocked) switches to a fresh
    exit IP that hasn't been tried yet this run, capped at
    min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs. A round where every
    failure was transport-only (timeout/DNS/connection — not a WAF signal)
    retries the SAME IP/session instead, up to _TRANSPORT_RETRIES, since
    rotating away from a perfectly good IP over a network blip wastes the
    budget on nothing."""
    prices: dict = {}
    pending = dict(ingredients)
    tried_idxs: set[int] = set()
    transport_retries = 0
    while pending:
        session = _ensure_http_session()

        def _work(item):
            name, data = item
            _thread_local.http = session  # routes _fetch_items → curl_cffi
            try:
                r = _price_one(name, float(data.get("qty", 1) or 1),
                               str(data.get("unit", "whole")))
                return name, r, None
            except _Blocked as e:
                return name, None, e.category
            except Exception as e:
                print(f"[Walmart] Error pricing '{name}': {e}", flush=True)
                return name, None, None
            finally:
                _thread_local.http = None

        blocked: dict = {}
        categories: set[str] = set()
        with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(pending)),
                                thread_name_prefix="wm-http") as pool:
            for name, r, category in pool.map(_work, list(pending.items())):
                if category is not None:
                    blocked[name] = pending[name]
                    categories.add(category)
                elif r:
                    prices[name] = r
        pending = blocked
        if not pending:
            break

        if categories - {"transport"}:
            # At least one item showed a real WAF signal this round.
            waf_category = "explicit" if "explicit" in categories else "soft"
            if _session_source == "pool":
                pool_num = _pool_idx + 1  # log before invalidate advances it
                print(f"[Walmart] Pool cookie #{pool_num}/{len(_cookie_pool)} blocked "
                      f"({waf_category}) — advancing (no IP rotation needed).", flush=True)
                _log_block(waf_category, f"pool cookie #{pool_num} blocked")
                _invalidate_http_session()
                transport_retries = 0
                time.sleep(random.uniform(0, 0.25))  # trivial jitter — pool swap is free
            else:
                cur_idx = getattr(_thread_local, "proxy_idx", None)
                if cur_idx is not None:
                    tried_idxs.add(cur_idx)
                if not _rotate_to_unused_proxy(tried_idxs):
                    print(f"[Walmart] Still throttled after {len(tried_idxs)} distinct IP(s) — "
                          f"{len(pending)} item(s) unpriced.", flush=True)
                    _log_block(waf_category, f"exhausted {len(tried_idxs)} IPs, {len(pending)} unpriced")
                    break
                print(f"[Walmart] PerimeterX throttle ({waf_category}) — switching to a "
                      f"fresh IP ({len(tried_idxs)} tried so far).", flush=True)
                _log_block(waf_category, f"rotating, {len(tried_idxs)} tried")
                _invalidate_http_session()  # delete the bad cookie so we warm truly fresh
                transport_retries = 0
                time.sleep(min(1.0 * len(tried_idxs), 5.0) + random.uniform(0, 0.75))
        else:
            # Every failure this round was transport-only — not a WAF signal.
            transport_retries += 1
            if transport_retries > _TRANSPORT_RETRIES:
                print(f"[Walmart] Persistent transport errors after {transport_retries} "
                      f"tries (same IP) — {len(pending)} item(s) unpriced.", flush=True)
                _log_block("transport", f"gave up after {transport_retries} tries, {len(pending)} unpriced")
                break
            print(f"[Walmart] Transport error (not PerimeterX) — retrying same session "
                  f"({transport_retries}/{_TRANSPORT_RETRIES}).", flush=True)
            time.sleep(min(1.0 * transport_retries, 3.0) + random.uniform(0, 0.5))
    return prices


def _do_pricing(ingredients: dict) -> dict:
    """(worker thread) Price all ingredients. A WAF-category block (explicit
    marker or soft signal) switches to a fresh exit IP that hasn't been tried
    yet this run, capped at min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs,
    before giving up → Instacart fallback. A transport-only failure (not a WAF
    signal) retries the same IP/session instead, up to _TRANSPORT_RETRIES."""
    prices: dict = {}
    pending = dict(ingredients)
    tried_idxs: set[int] = set()
    transport_retries = 0
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
        except _Blocked as e:
            if e.category == "transport":
                transport_retries += 1
                if transport_retries > _TRANSPORT_RETRIES:
                    print(f"[Walmart] Persistent transport errors after {transport_retries} "
                          f"tries — falling back to Instacart.", flush=True)
                    _log_block("transport", f"gave up after {transport_retries} tries, pool path")
                    return {}
                print(f"[Walmart] Transport error (not PerimeterX, pool path) — retrying "
                      f"same IP ({transport_retries}/{_TRANSPORT_RETRIES}).", flush=True)
                time.sleep(min(1.0 * transport_retries, 3.0) + random.uniform(0, 0.5))
                continue
            cur_idx = getattr(_thread_local, "proxy_idx", None)
            if cur_idx is not None:
                tried_idxs.add(cur_idx)
            _teardown_session()
            if not _rotate_to_unused_proxy(tried_idxs):
                print(f"[Walmart] Still blocked after {len(tried_idxs)} distinct IP(s) — "
                      f"falling back to Instacart.", flush=True)
                _log_block(e.category, f"exhausted {len(tried_idxs)} IPs, pool path")
                return {}
            print(f"[Walmart] PerimeterX block ({e.category}) — switching to a fresh "
                  f"exit IP ({len(tried_idxs)} tried so far).", flush=True)
            _log_block(e.category, f"rotating, pool path, {len(tried_idxs)} tried")
            transport_retries = 0
            time.sleep(min(1.0 * len(tried_idxs), 5.0) + random.uniform(0, 0.75))
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
            # A working pool session is kept alive across requests instead of
            # being dropped every time (fallback sessions keep the old
            # unconditional-drop behavior — that path already assumes a short
            # TTL and re-validates via disk cache next time regardless).
            if _session_source != "pool":
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
