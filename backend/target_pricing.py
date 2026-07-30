"""
Target pricing pipeline using Target's RedSky aggregations API, driven through
a stealth CloakBrowser so it bypasses Target's Imperva bot protection.

Why a browser?  redsky.target.com is fronted by Imperva, which validates the
TLS/JA3 fingerprint of the caller AND a JS-minted clearance cookie.  Plain
`requests` (wrong JA3) gets a 403 + captcha.

Primary path (fast): a CloakBrowser is used ONLY to mint the Imperva clearance
cookie — a homepage + a REAL Target search-page nav fully clears the challenge.
Then RedSky is replayed with curl_cffi (impersonating Chrome's JA3), which
passes Imperva *better* than Playwright's own APIRequestContext (the latter
gets 403 here).  RedSky is a lean JSON API, so this fetches a whole basket in
parallel in ~1-2s off a single browser warm.  A too-wide burst throttles the
cookie, so concurrency is capped and the cookie is re-minted on a wave of
blocks (up to MAX_IP_REFRESHES).

Fallback path: the original CloakBrowser request-context flow (`ctx.request.get`)
for when the curl_cffi path yields nothing.

Architecture (in-process singleton):
  * One CloakBrowser + browser context is launched lazily and kept warm.
  * Playwright's sync objects are thread-affine, and the FastAPI pricing path
    runs in a worker-thread pool, so EVERY browser operation is pinned to a
    single dedicated worker thread via `_executor` (max_workers=1).  That keeps
    the singleton both reusable across requests and thread-safe.
  * RedSky JSON is fetched with `context.request.get(url)` (Playwright's
    APIRequestContext) — browser TLS + cookies, no page render per query.

Flow:
  1. Warm the context by visiting target.com (mints Imperva cookies).
  2. Resolve nearest store_id (nearby_stores_v1), TARGET_STORE_ID env, or default.
  3. For each ingredient, walk get_all_terms() through the cdui_orchestrations
     `slp` (search/listing page) endpoint — see _slp_url/_extract_slp_products.
  4. Convert RedSky products to the Kroger shape; reuse find_best_purchase().

Reliability:
  * The HTTP session is sourced from a pool of pre-minted cookies
    (saved_target_cookies.json) FIRST — a dump from 2026-07-28 was confirmed
    to still price live products 27+ hours later. Only once every pool
    cookie is individually confirmed dead does the module fall back to the
    Supabase/disk-cache/CloakBrowser-mint chain below. See
    _next_pool_session/_ensure_http_session and TARGET_COOKIE_POOL_FILE.
  * Search results are cached per (store_id, term) for TARGET_SEARCH_TTL seconds
    (default 6h) — far fewer requests = far less flagging.
  * On a captcha from a fallback (non-pool) session, we tear down, ROTATE to a
    fresh proxy exit IP, back off, and resume pricing the still-pending
    ingredients. After MAX_IP_REFRESHES (default 5) fresh IPs are all blocked
    we give up → caller falls back to Instacart. A captcha from a pool
    session just advances to the next pool cookie — no IP rotation needed.
  * A residential proxy is what makes the fallback path reliable from a
    datacenter host (CloakBrowser handles fingerprint; the proxy handles IP
    reputation).

Entry point:
    store_name, store_id, prices = price_all_target(ingredients, lat, lon)

If CloakBrowser is unavailable or Imperva persistently blocks us, every public
call returns empty and server.py transparently falls back to Instacart pricing
for Target — so this integration is strictly additive and never makes Target worse.

Self-test:  python target_pricing.py
Env overrides:  TARGET_API_KEY, TARGET_STORE_ID, CLOAK_PROXY,
                TARGET_MAX_IP_REFRESHES, TARGET_SEARCH_TTL, TARGET_COOKIE_TTL,
                TARGET_COOKIE_POOL_FILE (path to the pool JSON tried before
                the mint chain; set to "" to disable the pool)
"""
from __future__ import annotations

import json
import math
import os
import pickle
import random
import re
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Optional

import pricing_pool
from kroger_pricing import find_best_purchase, parse_size
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_BANNERS: set[str] = {"target"}

# Public web key shipped by target.com's frontend. Override with TARGET_API_KEY.
_KEY = os.environ.get("TARGET_API_KEY", "9f36aeafbe60771e321a7cc95a78140772ab3e96")

_REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
_STORES_URL = f"{_REDSKY_BASE}/nearby_stores_v1"

# Target retired the old RedSky `plp_search_v2` aggregation for search results —
# a real browser navigating target.com/s?searchTerm=... no longer calls it at
# all, so any call to it now reads as bot traffic and gets 403+captcha
# regardless of cookie validity. Confirmed by capturing the live site's own
# network traffic on 2026-07-27: search results come from this CDUI
# orchestrations service instead. `zip`/`state`/`latitude`/`longitude` were all
# confirmed NOT required (store_id alone scopes location/pricing); dropped to
# keep this call as simple as the old one.
_SEARCH_URL = "https://cdui-orchestrations.target.com/cdui_orchestrations/v1/pages/slp"

# Default store if location lookup fails (Indianapolis-area Target).
_DEFAULT_STORE_ID = os.environ.get("TARGET_STORE_ID", "1771")

# Optional residential proxy. CloakBrowser defeats Imperva's *fingerprint* check
# even from a datacenter IP, but sustained volume degrades datacenter-IP
# reputation and captchas return. A residential proxy is the reliable fix for
# production (see CloakBrowser docs). Format: http://user:pass@host:port or
# socks5://user:pass@host:port.
#
# IP rotation: on a captcha we tear down and re-launch on a FRESH exit IP, up to
# MAX_IP_REFRESHES times, before giving up and falling back to Instacart. There
# are two ways to actually get a fresh IP — you MUST configure one, because there
# is no way to change the machine's egress IP from software alone:
#   1. A POOL of proxies — set CLOAK_PROXY (or TARGET_PROXY) to a comma- or
#      whitespace-separated list of URLs. Each refresh round-robins to the next
#      entry, so even plain static proxies give real IP diversity, e.g.
#        http://u:p@ip1:8000, http://u:p@ip2:8000, http://u:p@ip3:8000
#   2. A rotating-residential endpoint that keys the exit IP off a session token
#      in the username — put a literal "{session}" in the URL and it's replaced
#      with a fresh random token on each refresh, e.g.
#        http://user-session-{session}:pass@gate.provider.com:7000
#      (Providers that rotate per-connection need no placeholder — a new launch
#      already gets a new IP; a one-URL pool works for them.)
# With NO proxy configured, "rotation" reuses the same machine IP every time, so
# Imperva keeps serving the same captcha — _rotate_proxy_session warns about this.

def _parse_proxies(raw: Optional[str]) -> list[str]:
    """Split a proxy env value into a pool (comma/whitespace separated)."""
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]

_PROXIES = _parse_proxies(os.environ.get("CLOAK_PROXY") or os.environ.get("TARGET_PROXY"))
_PROXY = _PROXIES[0] if _PROXIES else None  # kept for back-compat truthiness checks

# How many fresh exit IPs to try before falling back to Instacart.
MAX_IP_REFRESHES = int(os.environ.get("TARGET_MAX_IP_REFRESHES", "5"))
# A transport-only failure (timeout/DNS/connection reset — see _ImpervaBlocked)
# isn't a WAF signal, so it gets its own small retry budget on the SAME IP
# instead of burning one of the MAX_IP_REFRESHES rotation slots.
_TRANSPORT_RETRIES = int(os.environ.get("TARGET_TRANSPORT_RETRIES", "2"))


def _log_block(category: str, detail: str = "") -> None:
    """Best-effort: publish a block/failure event to Supabase for later
    analysis (see session_store.log_block_event). Never raises, never blocks
    retry logic on Supabase being slow/unavailable beyond the one call."""
    try:
        import session_store
        session_store.log_block_event("target", category, detail)
    except Exception:
        pass

# Cache RedSky search results per (store_id, term) to slash scrape volume — the
# single biggest reliability lever (fewer requests = less flagging). Prices don't
# change intraday, so a multi-hour TTL is safe.
_SEARCH_TTL = int(os.environ.get("TARGET_SEARCH_TTL", str(6 * 3600)))

# --- Fast HTTP path (primary) ----------------------------------------------
# Imperva validates the caller's TLS/JA3 + a JS-minted clearance cookie. We use
# CloakBrowser ONLY to mint that cookie (a homepage + real search-page nav fully
# clears the challenge); then we replay RedSky with curl_cffi, which impersonates
# Chrome's JA3. curl_cffi actually PASSES Imperva where Playwright's
# APIRequestContext gets a 403 — and RedSky is a lean JSON API, so this is both
# faster and more reliable than the browser request context. Burst too wide and
# the cookie throttles, so concurrency is capped and re-minted on a wave of
# blocks (up to MAX_IP_REFRESHES).
_HTTP_CONCURRENCY = int(os.environ.get("TARGET_HTTP_CONCURRENCY", "6"))
_WARM_TRIES = int(os.environ.get("TARGET_WARM_TRIES", "3"))
_IMPERSONATE = os.environ.get("TARGET_IMPERSONATE", "chrome")

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


def _warm_search_url() -> str:
    return f"https://www.target.com/s?searchTerm={requests_quote(_random_search_term())}"

_http_session: Optional[dict] = None       # {"cookies": {...}, "ua": str}
_http_lock = threading.Lock()              # serialize warm/re-mint of the session
_session_source: Optional[str] = None      # "pool" | "fallback" — origin of _http_session
_thread_local = threading.local()          # per-worker: .http routes RedSky → curl_cffi
# Disk cache so the last cookie survives restarts and can be reused next run
# (validated first). Imperva's clearance cookie lives minutes, so a short max-age
# is safe. For a low-traffic app this disk reuse — not the in-memory session — is
# what actually saves the browser warm (requests are too sparse to hit memory).
_HTTP_SESSION_CACHE = Path(__file__).parent / ".target_http_session.json"
_HTTP_COOKIE_TTL = int(os.environ.get("TARGET_COOKIE_TTL", str(60 * 60)))
_STATIC_ASSET_CACHE_PATH = Path(__file__).parent / ".target_asset_cache.pkl"

# Pool of pre-minted cookies (backend/saved_target_cookies.json) tried BEFORE
# the remote/disk/warm chain below — see _next_pool_session(). A cookie dump
# minted 2026-07-28 was empirically confirmed to still price live products
# 27+ hours later, far outliving _HTTP_COOKIE_TTL above, so leaning on this
# pool first means the fragile/slow CloakBrowser mint is only ever reached
# once every pool entry is individually confirmed dead. Set
# TARGET_COOKIE_POOL_FILE="" to disable the pool and restore old behavior.
_env_pool_file = os.environ.get("TARGET_COOKIE_POOL_FILE")
if _env_pool_file is not None:
    _COOKIE_POOL_FILE = Path(_env_pool_file) if _env_pool_file else None
else:
    _COOKIE_POOL_FILE = Path(__file__).parent / "saved_target_cookies.json"
_pool_idx: int = 0             # cursor into _cookie_pool; persists for process lifetime
_pool_exhausted_logged = False # warn-once guard, mirrors _no_proxy_warned below


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
        print(f"[Target] No cookie pool file at {_COOKIE_POOL_FILE} — "
              "skipping straight to remote/disk/warm.", flush=True)
        return []
    except Exception as e:
        print(f"[Target] Cookie pool file unreadable ({repr(e)[:100]}) — "
              "skipping straight to remote/disk/warm.", flush=True)
        return []
    if not isinstance(raw, list):
        print("[Target] Cookie pool file is not a JSON array — ignoring.", flush=True)
        return []
    pool = []
    for i, entry in enumerate(raw):
        if isinstance(entry, dict) and entry.get("cookies") and entry.get("ua"):
            pool.append(entry)
        else:
            print(f"[Target] Cookie pool entry #{i + 1} missing cookies/ua — skipped.", flush=True)
    print(f"[Target] Loaded {len(pool)} pooled cookie(s) from {_COOKIE_POOL_FILE.name}.", flush=True)
    return pool


_cookie_pool: list[dict] = _load_cookie_pool()


class _ImpervaBlocked(Exception):
    """Raised when a request comes back wrong. Named for the vendor this file's
    comments originally assumed — but a live cookie dump from a real warm
    (_px2, _px3, _pxhd, _pxvid, pxcts) shows Target is actually PerimeterX-
    protected, the same as Walmart, not Imperva. Kept this name to avoid
    touching every call site over a label; only the mechanism matters here.

    `category` distinguishes WHY, same three buckets as walmart_pricing._Blocked:

      "explicit"  — an unambiguous block marker: HTTP 403, or a literal
                    "captchaRelativeURL" in the response body. Confirmed via a
                    live curl_cffi replay investigation.
      "soft"      — no explicit marker, but the response is still wrong (a
                    non-200/non-403 status, or no products came back).
      "transport" — no HTTP response was ever received (timeout, DNS,
                    connection reset, TLS failure). NOT a WAF signal.

    Only "explicit"/"soft" should trigger a fresh exit IP; "transport" should
    just retry the same session/IP a couple of times first."""
    def __init__(self, message: str = "", category: str = "soft"):
        super().__init__(message)
        self.category = category

# ---------------------------------------------------------------------------
# Store detection
# ---------------------------------------------------------------------------

def is_target_store(store_name: str) -> bool:
    lower = store_name.lower()
    # Exclude non-grocery Target sub-brands that show up in map results.
    return "target" in lower and not any(x in lower for x in ("optical", "pharmacy"))


# ---------------------------------------------------------------------------
# Bandwidth trim for the warm navigation — same technique as walmart_pricing.py.
# Measured 2026-07-25: target.com's
# warm (home + search) is ~9.1MB unblocked, dominated by a Next.js JS/CSS bundle
# on assets.targetimg1.com loaded twice. Blocks images/fonts/media and
# third-party ad-tech; caches only assets.targetimg1.com's content-hashed
# `_next/static/` chunks via route.fulfill(). Deliberately excludes
# assets.targetimg1.com/ssx/ssx.mod.js (its `?seed=...` query param looks
# request-specific, same caution as Woolworths' obfuscated paths) and
# anything on px-cloud.net (PerimeterX's own domain) or target.com itself
# (where the Imperva challenge actually lives).
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
_CACHEABLE_HOST = "assets.targetimg1.com"


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


def _pre_seed_asset_cache() -> None:
    """Download static Next.js JS/CSS assets from assets.targetimg1.com outside
    the browser using curl_cffi and populate _static_asset_cache. Prunes stale
    entries from previous deploys and fetches new ones.

    NOT called on Render (see _load_remote_asset_cache below) — this makes a
    handful of live network requests, which is exactly the kind of work the
    512MB host shouldn't be doing at boot. mint_sessions.py calls this on the
    GitHub Actions runner instead and publishes the result to Supabase.
    """
    try:
        from curl_cffi import requests as ccffi
        resp = ccffi.get("https://www.target.com/", impersonate=_IMPERSONATE, timeout=15)
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
        print(f"[Target] Pre-seeded {len(_static_asset_cache)} static assets"
              f" ({'pruned ' + str(len(stale)) + ' stale, ' if stale else ''}"
              f"{len(missing)} new)", flush=True)
    except Exception as e:
        print(f"[Target] Pre-seed failed ({e}) — fallback to browser download", flush=True)


def _load_remote_asset_cache() -> None:
    """Pull the already-pre-fetched asset cache from Supabase (published by
    mint_sessions.py on GitHub Actions) and merge it into _static_asset_cache.
    A single cheap DB read — no CDN calls, no curl_cffi burst, safe to run on
    every Render boot. Falls back to whatever's on disk / gets cached
    organically by _cache_static_assets during a real browser warm if Supabase
    has nothing yet."""
    try:
        import session_store
        remote = session_store.load_assets("target")
        if remote:
            _static_asset_cache.update(remote)
            _save_asset_cache()
            print(f"[Target] Loaded {len(remote)} pre-fetched assets from Supabase.", flush=True)
    except Exception as e:
        print(f"[Target] Remote asset cache load failed ({repr(e)[:80]}).", flush=True)


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
# CloakBrowser singleton — all access pinned to one worker thread
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloak-target")
_browser = None          # cloakbrowser Browser (lives on the worker thread)
_ctx = None              # browser context with warmed Imperva cookies
_session_lock = threading.Lock()

# Hard ceiling on the CloakBrowser fallback path. It holds the process-global
# browser gate the whole time it runs, so it must be bounded well inside the
# server's PRICING_BUDGET_SECONDS rather than running unbounded.
_BROWSER_PATH_BUDGET = float(os.environ.get("TARGET_BROWSER_BUDGET", "50"))
# How long a Target run will wait behind another Target run before giving up.
_RUN_LOCK_TIMEOUT = float(os.environ.get("TARGET_RUN_LOCK_TIMEOUT", "20"))
_proxy_session_id: Optional[str] = None  # current rotating-proxy session token
_proxy_idx: int = 0                      # round-robin cursor into _PROXIES
_no_proxy_warned: bool = False           # warn-once guard for the no-proxy case


def _rotate_proxy_session() -> None:
    """Advance to a fresh exit IP: round-robin the proxy pool AND mint a new
    session token (for "{session}"-style rotating-residential URLs). With no proxy
    configured this cannot change the egress IP — so warn once, otherwise the
    endless captcha loop looks like a mystery when it's just an unset proxy."""
    global _proxy_session_id, _proxy_idx, _no_proxy_warned
    _proxy_session_id = uuid.uuid4().hex[:12]
    if _PROXIES:
        _proxy_idx += 1
    elif not _no_proxy_warned:
        _no_proxy_warned = True
        print("[Target] No CLOAK_PROXY/TARGET_PROXY set — IP 'rotation' reuses the "
              "same machine IP, so Imperva captchas will persist. Set a rotating "
              "residential proxy or a comma-separated proxy pool to fix.", flush=True)


def _current_proxy() -> Optional[str]:
    """The current pool proxy (round-robin) with the session token substituted."""
    if not _PROXIES:
        return None
    base = _PROXIES[_proxy_idx % len(_PROXIES)]
    if "{session}" in base:
        return base.replace("{session}", _proxy_session_id or uuid.uuid4().hex[:12])
    return base


def _rotate_to_unused_proxy(tried_idxs: set[int]) -> bool:
    """Switch to a proxy index NOT already in `tried_idxs` (mutated in place
    with the new pick) — an IP that just failed is never retried in the same
    run. Returns False once min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs
    have already been tried (or MAX_IP_REFRESHES attempts with no pool
    configured at all); the caller should give up rather than call this again,
    since there's nothing new left to try."""
    global _proxy_session_id, _proxy_idx
    _proxy_session_id = uuid.uuid4().hex[:12]
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
    _proxy_idx = idx
    return True


def _wait_for_cookie(ctx, cookie_name: str, cap_seconds: float,
                      poll_interval: float = 0.15, settle_ticks: int = 2) -> bool:
    """Poll ctx.cookies() instead of a fixed sleep, so a warm that clears in
    300ms doesn't still hold the browser gate for the full cap_seconds.

    Requires TWO things, not one: `cookie_name` must be present, AND the total
    cookie count must have stopped growing for `settle_ticks` consecutive polls.
    A single named cookie showing up isn't enough on its own — proved
    empirically against Walmart (test_direct_search.py): _px3 was present in
    BOTH the working warm and the one that came back with an empty page. These
    WAFs set a whole family of cookies together as their challenge resolves —
    waiting for that set to stop growing is a materially stronger signal that
    the challenge has actually finished, not just started, without hardcoding
    exact cookie names beyond the one anchor we need present either way.

    Returns True once settled, False if the cap elapses first — the caller
    proceeds anyway exactly as it did with the old fixed sleep. This never
    provides the actual safety guarantee by itself: it only reads the browser's
    already-downloaded cookie jar (no requests, no bandwidth cost), and a warm
    that's still weak despite settling is caught downstream regardless
    (_validate_http_session's live RedSky call) — that check, not this wait, is
    what guarantees a bad warm never silently succeeds."""
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
    """(worker thread) Launch CloakBrowser on the current proxy session, open a
    context, and warm Imperva cookies. Raises on failure so the caller can fall
    back to Instacart."""
    global _browser, _ctx
    from browser_gate import launch_geoip_optional  # gated: 1 browser at a time + low-mem flags

    # Tear down any half-dead session first.
    _teardown_session()
    if _proxy_session_id is None:
        _rotate_proxy_session()

    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True  # match timezone/locale to the proxy exit IP
    browser = launch_geoip_optional(**kwargs)

    # Only publish to the module globals once the warm succeeded — otherwise a
    # mid-warm failure leaves a browser nobody closes, holding the browser gate.
    try:
        ctx = browser.new_context()
        _block_heavy_resources(ctx)
        page = ctx.new_page()
        page.on("response", _cache_static_assets)
        page.goto("https://www.target.com/", wait_until="domcontentloaded", timeout=45000)
        # Let Imperva's JS challenge run and set its clearance cookie before we hit
        # the API — calling RedSky too eagerly returns a captcha. Poll instead of a
        # fixed sleep so a fast challenge doesn't hold the browser gate any longer
        # than it has to.
        _wait_for_cookie(ctx, "_px3", 3)
        page.close()
    except BaseException:
        try:
            browser.close()
        except Exception:
            pass
        raise

    _browser, _ctx = browser, ctx
    print(f"[Target] CloakBrowser session warmed{' (proxy)' if proxy else ''}.", flush=True)


def _teardown_session():
    """(worker thread) Best-effort close of the current browser/context."""
    global _browser, _ctx
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    _browser, _ctx = None, None


def _release_browser() -> None:
    """Close the CloakBrowser on its owning worker thread, freeing the global
    browser gate. Called at the end of every run that may have started one.

    The browser MUST NOT outlive the request: browser_gate hands out a lease
    that is only released by .close(), so a browser held across requests blocks
    every other browser chain until the max-hold backstop reclaims it. Bounded
    so a hung worker can't turn cleanup into a second stall — the gate's
    max-hold backstop is the safety net if this times out."""
    try:
        _executor.submit(_teardown_session).result(timeout=15)
    except FuturesTimeout:
        print("[Target] Browser teardown didn't finish in 15s — leaving it to the "
              "browser-gate max-hold backstop.", flush=True)
    except Exception as e:
        print(f"[Target] Browser teardown failed ({repr(e)[:100]}).", flush=True)


def _ensure_ctx():
    """(worker thread) Return a live context, bootstrapping if needed."""
    global _ctx
    if _ctx is None:
        _bootstrap_session()
    return _ctx


def _redsky_get(url: str) -> str:
    """GET a RedSky URL. Dispatches to the fast curl_cffi path when this thread
    holds an HTTP session, else the browser request context. Returns the body on
    200, "" on a non-captcha error, raises _ImpervaBlocked on a captcha."""
    http = getattr(_thread_local, "http", None)
    if http is not None:
        return _redsky_get_http(url, http)
    return _redsky_get_browser(url)


def _redsky_get_http(url: str, session: dict) -> str:
    """(curl_cffi) Replay a RedSky call with the warmed Imperva cookie + Chrome
    JA3. Passes Imperva where the browser's APIRequestContext gets 403."""
    from curl_cffi import requests as _ccffi
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.target.com",
        "referer": "https://www.target.com/",
        "user-agent": session["ua"],
    }
    try:
        resp = _ccffi.get(url, headers=headers, cookies=session["cookies"],
                          impersonate=_IMPERSONATE, timeout=30)
    except Exception as e:
        # Never reached the site at all — not a WAF signal (see _ImpervaBlocked).
        raise _ImpervaBlocked(f"http error: {repr(e)[:60]}", category="transport")
    if resp.status_code == 403 or '"captchaRelativeURL"' in resp.text:
        raise _ImpervaBlocked("403/captcha marker", category="explicit")
    if resp.status_code != 200:
        # Used to return "" here silently — a genuine RedSky error (5xx etc.)
        # never got flagged or retried, it just permanently looked like "no
        # products" for that item. Now it's at least visible and retryable.
        raise _ImpervaBlocked(f"http {resp.status_code}", category="soft")
    return resp.text


def _redsky_get_browser(url: str) -> str:
    """(worker thread) GET a RedSky URL through the CloakBrowser request context —
    the fallback when the curl_cffi path is unavailable."""
    ctx = _ensure_ctx()
    try:
        resp = ctx.request.get(url, timeout=30000)
        text = resp.text()
    except Exception as e:
        raise _ImpervaBlocked(f"request failed: {repr(e)[:60]}", category="transport")
    if resp.status == 403 or "captchaRelativeURL" in text:
        raise _ImpervaBlocked("403/captcha marker", category="explicit")
    if resp.status != 200:
        raise _ImpervaBlocked(f"http {resp.status}", category="soft")
    return text


# ---------------------------------------------------------------------------
# Product format conversion (RedSky → Kroger shape)
# ---------------------------------------------------------------------------
#
# Target titles follow "{name} - {size} - {brand}™", with several variants seen
# in real RedSky data:
#   "Vitamin D Whole Milk - 1gal - Good & Gather™"          (size in middle)
#   "Fairlife Lactose-Free Whole Milk - 52 fl oz"           (no trailing brand)
#   "Grade A Large Eggs - 18ct - Good & Gather™ (Packaging May Vary)"
#   "Fresh Parmesan Chicken Breast Cutlets - 20oz/4ct - …"  (compound size)
#   "Fresh Banana - each - Good & Gather™"                  (sold each)
#   "…Boneless & Skinless Chicken Breast - price per lb - …" (WEIGHT: price is $/lb)
# A suffix-only parser misses the common mid-title case, so we split on " - "
# and locate the segment that is itself a size token.

import html as _html

# A whole " - " segment that is a size token (with optional compound "/12ct").
_SIZE_SEG_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*"
    r"(fl\s*oz|oz|lb|lbs|gal|gallon|qt|quart|pt|pint|ml|l|liter|litre|"
    r"ct|count|pk|pack|dozen|doz|g|kg)\b",
    re.IGNORECASE,
)
# A size token appearing anywhere in the title (fallback when there's no
# " - " segment, e.g. comma- or space-delimited).
_SIZE_INLINE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(fl\s*oz|oz|lb|lbs|gal|gallon|qt|quart|pt|pint|ml|ct|count|pk|pack|dozen)\b",
    re.IGNORECASE,
)
# Weight-priced items: current_retail is the per-lb price, not a package price.
_WEIGHT_RE = re.compile(r"price\s*per\s*(lb|pound)", re.IGNORECASE)


def _clean_title(title: str) -> str:
    """Decode HTML entities and drop a trailing parenthetical note."""
    t = _html.unescape(title or "")
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
    return t


def _seg_size(seg: str) -> Optional[str]:
    """Return a normalized size string if `seg` is a size segment, else None.
    Handles compound sizes ("20oz/4ct" → "20oz") and "each" → "1 each"."""
    seg = seg.strip()
    low = seg.lower()
    if low in ("each", "ea"):
        return "1 each"
    first = seg.split("/")[0].strip()  # compound "20oz/4ct" → use the weight part
    if _SIZE_SEG_RE.match(first) and parse_size(first):
        return first
    return None


def _parse_title(title: str) -> tuple[str, str, str]:
    """Parse a Target title into (name, size_str, sold_by)."""
    t = _clean_title(title)

    # Weight-priced (sold by the pound): price is $/lb; size is irrelevant to
    # build_priced_product, which reads soldBy=WEIGHT and treats price as per-lb.
    if _WEIGHT_RE.search(t):
        keep = []
        for seg in t.split(" - "):
            if "price per" in seg.lower():
                break
            keep.append(seg)
        return (" - ".join(keep).strip() or t), "1 lb", "WEIGHT"

    # UNIT: find the " - " segment that is a size token.
    parts = t.split(" - ")
    for i, seg in enumerate(parts):
        sz = _seg_size(seg)
        if sz:
            return (" - ".join(parts[:i]).strip() or t), sz, "UNIT"

    # Fallback: a size token anywhere in the title.
    m = _SIZE_INLINE_RE.search(t)
    if m:
        name = (t[: m.start()] + " " + t[m.end():]).strip(" -,")
        return (name or t), m.group(0).strip(), "UNIT"

    # No size found — treat as a single count unit.
    return t, "1 each", "UNIT"


def _price_value(price: dict) -> Optional[float]:
    """Pull a usable USD price from a RedSky price block. For WEIGHT items this
    is current_retail = the per-lb price (NOT formatted_current_price, which is
    an estimated package total)."""
    for field in ("current_retail", "reg_retail"):
        val = price.get(field)
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if 0.01 <= val <= 500:
            return val
    formatted = price.get("formatted_current_price") or ""
    m = re.search(r"\$?(\d+(?:\.\d{1,2})?)", formatted)
    if m:
        try:
            val = float(m.group(1))
            if 0.01 <= val <= 500:
                return val
        except ValueError:
            pass
    return None


def _to_kroger_format(product: dict) -> Optional[dict]:
    """Convert an slp search-result product into the Kroger product shape."""
    item = product.get("item") or {}
    raw_title = (item.get("product_description") or {}).get("title") or ""
    if not raw_title:
        return None
    price = _price_value(product.get("price") or {})
    if price is None:
        return None

    brand = (item.get("primary_brand") or {}).get("name") or ""
    name, size, sold_by = _parse_title(raw_title)

    return {
        "description": name,
        "brand": brand,
        "items": [{
            "itemId": str(product.get("tcin") or item.get("tcin") or ""),
            "soldBy": sold_by,
            "size": size,
            "price": {"regular": price, "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Store discovery (worker thread)
# ---------------------------------------------------------------------------

# Local {store_id, slug, lat, lon} directory built offline by
# build_target_store_directory.py from Target's public store sitemap +
# Nominatim geocoding — see that script's docstring. Used to resolve
# "nearest store" WITHOUT ever calling RedSky (nearby_stores_v1 is confirmed
# dead via curl_cffi regardless of cookie). Heuristic, not exact-address
# precision, but zero WAF exposure and instant.
_STORE_DIRECTORY_FILE = Path(__file__).parent / "target_store_directory.json"


def _load_store_directory() -> list[dict]:
    try:
        raw = json.loads(_STORE_DIRECTORY_FILE.read_text())
    except FileNotFoundError:
        print(f"[Target] No store directory at {_STORE_DIRECTORY_FILE} — "
              "nearest-store resolution will use the legacy nearby_stores_v1 "
              "fallback (confirmed dead) then the default store. Run "
              "build_target_store_directory.py to generate it.", flush=True)
        return []
    except Exception as e:
        print(f"[Target] Store directory unreadable ({repr(e)[:100]}).", flush=True)
        return []
    if not isinstance(raw, list) or not raw:
        return []
    print(f"[Target] Loaded {len(raw)}-store directory for nearest-store resolution.", flush=True)
    return raw


_store_directory: list[dict] = _load_store_directory()


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8  # Earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest_store_from_directory(lat: float, lon: float) -> Optional[str]:
    """O(n) nearest-neighbor over the local store directory (~2000 rows,
    sub-millisecond) — no network call, no WAF exposure. None if the
    directory hasn't been built yet, so the caller can fall back."""
    if not _store_directory:
        return None
    best_id, best_dist = None, float("inf")
    for entry in _store_directory:
        d = _haversine_miles(lat, lon, entry["lat"], entry["lon"])
        if d < best_dist:
            best_id, best_dist = entry["store_id"], d
    return str(best_id) if best_id is not None else None


def _resolve_store_id(lat: float, lon: float) -> str:
    nearest = _nearest_store_from_directory(lat, lon)
    if nearest is not None:
        return nearest

    # Legacy fallback: nearby_stores_v1 is confirmed dead via curl_cffi (403 +
    # captcha for ANY cookie, including zero cookies, for ANY postal code) —
    # kept only in case Target ever un-blocks it. Reached only when the local
    # store directory is empty/unavailable.
    try:
        from instacart_pricing import _get_postal
        postal = _get_postal(lat, lon)
    except Exception:
        postal = ""
    if not postal:
        return _DEFAULT_STORE_ID
    url = (f"{_STORES_URL}?key={_KEY}&limit=5&within=100&place={postal}"
           f"&visitor_id={uuid.uuid4().hex.upper()}&channel=WEB&page=/c/nearby-stores")
    # Best-effort: a block/error here shouldn't abort the call — the search loop
    # is the real signal. Fall back to the default store.
    try:
        text = _redsky_get(url)
        import json
        stores = (json.loads(text).get("data", {})
                  .get("nearby_stores", {}).get("stores", []))
        if stores:
            return str(stores[0].get("store_id") or _DEFAULT_STORE_ID)
    except Exception:
        pass
    return _DEFAULT_STORE_ID


# ---------------------------------------------------------------------------
# Search + per-ingredient pricing (worker thread)
# ---------------------------------------------------------------------------

# (store_id, query) → (expiry_ts, products). In-memory, per-process.
# Bounded + LRU: the key includes store_id, so a long-lived server serving many
# markets accumulated an entry per (store, term) pair forever. Entries are also
# evicted on expiry rather than lingering as dead weight.
_SEARCH_CACHE_MAX = int(os.environ.get("TARGET_SEARCH_CACHE_MAX", "2000"))
_search_cache: "OrderedDict[tuple[str, str], tuple[float, list[dict]]]" = OrderedDict()
_search_cache_lock = threading.Lock()


def _search_cache_get(key: tuple[str, str]) -> Optional[list[dict]]:
    with _search_cache_lock:
        hit = _search_cache.get(key)
        if hit is None:
            return None
        if hit[0] <= time.time():
            _search_cache.pop(key, None)   # expired — drop it
            return None
        _search_cache.move_to_end(key)     # LRU touch
        return hit[1]


def _search_cache_put(key: tuple[str, str], products: list[dict]) -> None:
    with _search_cache_lock:
        _search_cache[key] = (time.time() + _SEARCH_TTL, products)
        _search_cache.move_to_end(key)
        while len(_search_cache) > _SEARCH_CACHE_MAX:
            _search_cache.popitem(last=False)


def _slp_url(query: str, store_id: str, num_results: int) -> str:
    """Build a cdui_orchestrations `slp` (search/listing page) URL — the
    replacement for the retired `plp_search_v2` aggregation. Mirrors the
    param set a real browser sends, minus zip/state/lat/lon/timezone
    (confirmed NOT required — store_id alone scopes location/pricing)."""
    q = requests_quote(query)
    page = f"/s/{q}"
    return (f"{_SEARCH_URL}?key={_KEY}&platform=WEB&sapphire_channel=WEB"
            f"&sapphire_page={page}&channel=WEB&page={page}"
            f"&visitor_id={uuid.uuid4().hex.upper()}"
            f"&store_id={store_id}&store_ids={store_id}"
            f"&scheduled_delivery_store_id={store_id}"
            f"&count={num_results}&offset=0&new_search=true&keyword={q}"
            f"&include_data_source_modules=true&default_purchasability_filter=true"
            f"&spellcheck=true&is_seo_bot=false&device_type=desktop"
            f"&targeted_advertising_opt_out=false&privacy_do_not_sell=false"
            f"&query_string=searchTerm%3D{q}")


def _extract_slp_products(text: str) -> list[dict]:
    """Pull the product list out of an slp response: it's a page-orchestration
    payload (`data_source_modules[]`), not a flat `data.search.products` like
    the old plp_search_v2 shape — find the module that actually carries
    search results."""
    import json
    try:
        data = json.loads(text)
    except Exception:
        return []
    for mod in data.get("data_source_modules") or []:
        products = ((mod.get("module_data") or {}).get("search_response") or {}).get("products")
        if products:
            return products
    return []


def _search(query: str, store_id: str, num_results: int = 24) -> list[dict]:
    # 24 (vs the page's default of ~28) gives find_best_purchase enough
    # candidates to reliably surface the cheapest matching size/variant; with
    # only ~10 the cheapest option is sometimes outside the result window.
    cache_key = (store_id, query.lower())
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return cached

    url = _slp_url(query, store_id, num_results)
    text = _redsky_get(url)  # may raise _ImpervaBlocked → handled in _do_pricing
    if not text:
        return []
    products = _extract_slp_products(text)
    if not products:
        return []

    query_words = set(query.lower().split())

    def title_of(p: dict) -> str:
        return ((p.get("item") or {}).get("product_description") or {}).get("title", "").lower()

    out = []
    for p in products:
        if all(qw in title_of(p) for qw in query_words):
            fmt = _to_kroger_format(p)
            if fmt:
                out.append(fmt)
    if not out:
        for p in products:
            if any(qw in title_of(p) for qw in query_words):
                fmt = _to_kroger_format(p)
                if fmt:
                    out.append(fmt)
    _search_cache_put(cache_key, out)
    return out


def requests_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def _price_one(ingredient: str, qty: float, unit: str, store_id: str) -> Optional[dict]:
    for term in get_all_terms(ingredient):
        products = _search(term, store_id)
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
# Fast HTTP session: mint Imperva cookies with a browser, replay via curl_cffi
# ---------------------------------------------------------------------------

def _warm_http_session() -> dict:
    """Mint Imperva clearance with CloakBrowser (homepage + a real Target search
    navigation), harvest the cookie jar + user-agent, and verify a curl_cffi
    RedSky call returns products. Raises _ImpervaBlocked on a weak/blocked warm."""
    from browser_gate import launch_geoip_optional  # gated: 1 browser at a time + low-mem flags
    if _proxy_session_id is None:
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
        page.goto("https://www.target.com/", wait_until="domcontentloaded", timeout=45000)
        _wait_for_cookie(ctx, "_px3", 2)
        # A real search nav (not just the homepage) is what fully clears Imperva
        # and mints a clearance cookie RedSky will accept. The term itself is
        # randomized (see _WARM_SEARCH_TERMS) so it's not always "eggs".
        page.goto(_warm_search_url(), wait_until="domcontentloaded", timeout=45000)
        _wait_for_cookie(ctx, "_px3", 3)
        ua = page.evaluate("() => navigator.userAgent")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    finally:
        try:
            browser.close()
        except Exception:
            pass
    session = {"cookies": cookies, "ua": ua}
    # Validate the warm: a real RedSky call must come back with products.
    if not _validate_http_session(session):
        raise _ImpervaBlocked("weak warm — no products")
    return session


def _validate_http_session(session: dict) -> bool:
    """Cheap liveness check (no browser): one curl_cffi RedSky search must return
    products. True ⇒ the cookie is still good and can be reused."""
    term = _random_search_term()
    url = _slp_url(term, _DEFAULT_STORE_ID, 8)
    try:
        text = _redsky_get_http(url, session)  # raises _ImpervaBlocked on captcha
        return bool(_extract_slp_products(text)) if text else False
    except Exception:
        return False


def _save_http_session(session: dict) -> None:
    """Persist the warmed cookie to disk so it survives restarts and can be reused
    next run (validated first) — see _ensure_http_session."""
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


def _load_remote_session() -> Optional[dict]:
    """Off-box cookie from Supabase (published by mint_sessions.py on GitHub
    Actions). None if unavailable/stale — caller falls back to disk/warm."""
    try:
        import session_store
        return session_store.load("target")
    except Exception:
        return None


def _next_pool_session() -> Optional[dict]:
    """(caller holds _http_lock) Return the first pool cookie at/after
    _pool_idx that passes a live validate, advancing _pool_idx past any dead
    ones along the way. None once the whole pool has been exhausted this
    process — caller falls through to the remote/disk/warm chain. Cheap to
    call repeatedly once exhausted: the loop is then a 0-iteration no-op,
    and the "exhausted" log fires only once."""
    global _pool_idx, _pool_exhausted_logged
    n = len(_cookie_pool)
    while _pool_idx < n:
        candidate = _cookie_pool[_pool_idx]
        if _validate_http_session(candidate):
            print(f"[Target] Using pool cookie #{_pool_idx + 1}/{n} "
                  f"(saved {candidate.get('saved_at_iso', '?')}).", flush=True)
            return candidate
        print(f"[Target] Pool cookie #{_pool_idx + 1}/{n} is dead — advancing.", flush=True)
        _pool_idx += 1
    if n and not _pool_exhausted_logged:
        _pool_exhausted_logged = True
        print(f"[Target] Cookie pool exhausted ({n}/{n} dead) — "
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

            # Off-box cookie (GitHub Actions -> Supabase) first, then disk, then warm.
            cached = _load_remote_session()
            if cached and _validate_http_session(cached):
                _http_session = cached
                _session_source = "fallback"
                print("[Target] Reused off-box cookie (Supabase, no warm).", flush=True)
            elif (cached := _load_http_session()) and _validate_http_session(cached):
                _http_session = cached
                _session_source = "fallback"
                print("[Target] Reused cached HTTP cookie (no warm).", flush=True)
            else:
                last: Optional[Exception] = None
                for _ in range(_WARM_TRIES):
                    try:
                        _http_session = _warm_http_session()
                        _session_source = "fallback"
                        _save_http_session(_http_session)
                        print(f"[Target] HTTP session warmed (curl_cffi"
                              f"{', proxy' if _PROXY else ''}).", flush=True)
                        break
                    except Exception as e:
                        last = e
                        _rotate_proxy_session()  # fresh exit IP for the next warm
                if _http_session is None:
                    raise _ImpervaBlocked(f"warm failed after {_WARM_TRIES} tries: {repr(last)[:80]}")
    return _http_session


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
    the next ensure mints a genuinely fresh cookie (never the throttled one)."""
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


def _price_via_http(ingredients: dict, lat: float, lon: float) -> tuple[Optional[str], dict]:
    """Primary path: one browser warm, then resolve the store + price every
    ingredient over parallel curl_cffi RedSky calls. A round where anything
    came back with a WAF-category block (explicit marker/403 or soft signal —
    see _ImpervaBlocked) switches to a fresh exit IP that hasn't been tried yet
    this run, capped at min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs. A
    round where every failure was transport-only (timeout/DNS/connection — not
    a WAF signal) retries the SAME IP/session instead, up to
    _TRANSPORT_RETRIES. Returns (store_id, prices)."""
    prices: dict = {}
    pending = dict(ingredients)
    store_id: Optional[str] = None
    tried_idxs: set[int] = set()
    transport_retries = 0
    while pending:
        session = _ensure_http_session()
        if store_id is None:
            _thread_local.http = session
            try:
                store_id = _resolve_store_id(lat, lon)
            finally:
                _thread_local.http = None
            print(f"[Target] Pricing at store #{store_id} (curl_cffi)", flush=True)

        def _work(item):
            name, data = item
            _thread_local.http = session  # routes _redsky_get → curl_cffi
            try:
                r = _price_one(name, float(data.get("qty", 1) or 1),
                               str(data.get("unit", "whole")), store_id)
                return name, r, None
            except _ImpervaBlocked as e:
                return name, None, e.category
            except Exception as e:
                print(f"[Target] Error pricing '{name}': {e}", flush=True)
                return name, None, None
            finally:
                _thread_local.http = None

        blocked: dict = {}
        categories: set[str] = set()
        with ThreadPoolExecutor(max_workers=min(_HTTP_CONCURRENCY, len(pending)),
                                thread_name_prefix="tg-http") as pool:
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
            waf_category = "explicit" if "explicit" in categories else "soft"
            if _session_source == "pool":
                pool_num = _pool_idx + 1  # log before invalidate advances it
                print(f"[Target] Pool cookie #{pool_num}/{len(_cookie_pool)} blocked "
                      f"({waf_category}) — advancing (no IP rotation needed).", flush=True)
                _log_block(waf_category, f"pool cookie #{pool_num} blocked")
                _invalidate_http_session()
                transport_retries = 0
                time.sleep(random.uniform(0, 0.25))  # trivial jitter — pool swap is free
            else:
                tried_idxs.add(_proxy_idx)
                if not _rotate_to_unused_proxy(tried_idxs):
                    print(f"[Target] Still throttled after {len(tried_idxs)} distinct IP(s) — "
                          f"{len(pending)} item(s) unpriced.", flush=True)
                    _log_block(waf_category, f"exhausted {len(tried_idxs)} IPs, {len(pending)} unpriced")
                    break
                print(f"[Target] Imperva throttle ({waf_category}) — switching to a fresh IP "
                      f"({len(tried_idxs)} tried so far).", flush=True)
                _log_block(waf_category, f"rotating, {len(tried_idxs)} tried")
                _invalidate_http_session()  # delete the bad cookie so we warm truly fresh
                transport_retries = 0
                time.sleep(min(1.0 * len(tried_idxs), 5.0) + random.uniform(0, 0.75))
        else:
            transport_retries += 1
            if transport_retries > _TRANSPORT_RETRIES:
                print(f"[Target] Persistent transport errors after {transport_retries} "
                      f"tries (same IP) — {len(pending)} item(s) unpriced.", flush=True)
                _log_block("transport", f"gave up after {transport_retries} tries, {len(pending)} unpriced")
                break
            print(f"[Target] Transport error (not Imperva) — retrying same session "
                  f"({transport_retries}/{_TRANSPORT_RETRIES}).", flush=True)
            time.sleep(min(1.0 * transport_retries, 3.0) + random.uniform(0, 0.5))
    return store_id, prices


def _do_pricing(ingredients: dict, lat: float, lon: float) -> tuple[Optional[str], dict]:
    """(worker thread) Resolve store + price all ingredients, healing through
    blocks by switching to a fresh exit IP.

    A WAF-category block (explicit marker/403, or a soft signal) tears down,
    switches to a proxy that hasn't been tried yet this run, backs off, and
    resumes pricing only the ingredients still pending — so intermittent
    blocks progressively complete the basket. After
    min(MAX_IP_REFRESHES, len(_PROXIES)) distinct IPs are all blocked we give
    up and return ({}) so the caller falls back to Instacart for the whole
    store. A transport-only failure (not a WAF signal) retries the same
    IP/session instead, up to _TRANSPORT_RETRIES.

    Pricing is sequential because the sync browser context is single-threaded;
    cached terms make repeat baskets nearly free."""
    prices: dict = {}
    pending = dict(ingredients)
    store_id: Optional[str] = None
    tried_idxs: set[int] = set()
    transport_retries = 0

    while pending:
        try:
            _ensure_ctx()  # bootstrap (raises only on launch failure → Instacart)
            if store_id is None:
                store_id = _resolve_store_id(lat, lon)
                print(f"[Target] Pricing at store #{store_id}", flush=True)

            for name in list(pending):
                # The request that started us may already have given up (the
                # server's pricing budget elapsed). Stop rather than grind
                # through the rest of the basket for a response nobody reads.
                if pricing_pool.expired():
                    print(f"[Target] Pricing budget elapsed — stopping with "
                          f"{len(prices)}/{len(ingredients)} priced.", flush=True)
                    return store_id, prices
                data = pending[name]
                try:
                    result = _price_one(
                        name,
                        float(data.get("qty", 1) or 1),
                        str(data.get("unit", "whole")),
                        store_id,
                    )
                    if result:
                        prices[name] = result
                except _ImpervaBlocked:
                    raise  # leave `name` pending; handled by the refresh below
                except Exception as e:
                    print(f"[Target] Error pricing '{name}': {e}", flush=True)
                del pending[name]  # priced or genuinely not found — don't retry
            break  # all ingredients attempted

        except _ImpervaBlocked as e:
            if e.category == "transport":
                transport_retries += 1
                if transport_retries > _TRANSPORT_RETRIES:
                    print(f"[Target] Persistent transport errors after {transport_retries} "
                          f"tries — falling back to Instacart for this store.", flush=True)
                    _log_block("transport", f"gave up after {transport_retries} tries, pool path")
                    return store_id, {}
                print(f"[Target] Transport error (not Imperva, pool path) — retrying "
                      f"same IP ({transport_retries}/{_TRANSPORT_RETRIES}).", flush=True)
                time.sleep(min(1.0 * transport_retries, 3.0) + random.uniform(0, 0.5))
                continue
            tried_idxs.add(_proxy_idx)
            _teardown_session()
            if not _rotate_to_unused_proxy(tried_idxs):
                print(f"[Target] Still blocked after {len(tried_idxs)} distinct IP(s) — "
                      f"falling back to Instacart for this store.", flush=True)
                _log_block(e.category, f"exhausted {len(tried_idxs)} IPs, pool path")
                return store_id, {}
            print(f"[Target] Captcha ({e.category}) — switching to a fresh exit IP "
                  f"({len(tried_idxs)} tried so far).", flush=True)
            _log_block(e.category, f"rotating, pool path, {len(tried_idxs)} tried")
            transport_retries = 0
            time.sleep(min(1.0 * len(tried_idxs), 5.0) + random.uniform(0, 0.75))  # backoff + jitter

    return store_id, prices


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price_all_target(
    ingredients: dict,
    lat: float,
    lon: float,
    max_workers: int = 10,  # accepted for signature parity; pricing is serialized
) -> tuple[Optional[str], Optional[str], dict]:
    """
    Price all ingredients at the nearest Target store via RedSky (CloakBrowser).

    Returns (display_name, store_id, prices). `prices` is empty if Imperva blocks
    us, in which case the caller falls back to Instacart. Primary path is fast
    parallel curl_cffi off a single browser-minted Imperva cookie; the original
    CloakBrowser request-context path is kept as a fallback.
    """
    store_id: Optional[str] = None
    prices: dict = {}
    # Serialize whole-Target runs across requests, but never wait forever for a
    # hung predecessor — a stuck run must degrade to Instacart, not stall the
    # caller's pricing budget.
    if not _session_lock.acquire(timeout=_RUN_LOCK_TIMEOUT):
        print(f"[Target] Another Target run held the lock > {_RUN_LOCK_TIMEOUT:.0f}s "
              "— falling back to Instacart.", flush=True)
        return None, None, {}
    try:
        # Primary: curl_cffi (browser warm → RedSky over HTTP).
        try:
            store_id, prices = _price_via_http(ingredients, lat, lon)
        except Exception as e:
            print(f"[Target] HTTP path unavailable ({repr(e)[:120]}).", flush=True)
            store_id, prices = None, {}
        finally:
            # A working pool session is proven to survive 27+ hours (far past
            # _HTTP_COOKIE_TTL), so it's kept alive across requests instead of
            # being dropped every time — avoids a redundant live validate-call
            # on every single pricing call. Fallback sessions keep the old
            # unconditional-drop behavior (that path already assumes a short
            # TTL and re-validates via disk cache next time regardless).
            if _session_source != "pool":
                _drop_http_session()

        # Fallback: original CloakBrowser request-context path.
        if not prices:
            print("[Target] HTTP path empty — falling back to CloakBrowser request context.", flush=True)
            try:
                store_id, prices = _executor.submit(
                    _do_pricing, ingredients, lat, lon
                ).result(timeout=_BROWSER_PATH_BUDGET)
            except FuturesTimeout:
                print(f"[Target] CloakBrowser path exceeded {_BROWSER_PATH_BUDGET:.0f}s "
                      "— falling back to Instacart.", flush=True)
                return None, None, {}
            except Exception as e:
                print(f"[Target] Direct pricing unavailable ({repr(e)[:140]}) — "
                      "falling back to Instacart.", flush=True)
                return None, None, {}
            finally:
                # The CloakBrowser path leaves `_browser` alive, and browser_gate
                # only frees the gate on .close(). Keeping it across requests
                # starved every other browser chain (ALDI/Walmart/Coles/IC) until
                # process exit, so the browser is strictly request-scoped now.
                _release_browser()
    finally:
        _session_lock.release()

    if not prices:
        return None, None, {}
    display_name = f"Target (store #{store_id})"
    print(f"[Target] Priced {len(prices)}/{len(ingredients)} ingredients "
          f"at {display_name}.", flush=True)
    return display_name, store_id, prices


def shutdown():
    """Close the browser. Call on server shutdown to free ~250MB."""
    try:
        _executor.submit(_teardown_session).result(timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Self-test:  python target_pricing.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = {
        "milk":     {"qty": 1, "unit": "gallon"},
        "eggs":     {"qty": 12, "unit": "count"},
        "bananas":  {"qty": 2, "unit": "pound"},
        "bread":    {"qty": 1, "unit": "loaf"},
        "chicken breast": {"qty": 3, "unit": "pound"},
    }
    name, sid, out = price_all_target(sample, 40.0033, -86.1366)
    print(f"\n=== {name} ===")
    if not out:
        print("No prices — CloakBrowser unavailable or blocked. "
              "Install with: pip install cloakbrowser")
    for ing, res in out.items():
        print(f"  {ing:18s} ${res.get('total_cost', 0):6.2f}  "
              f"{res.get('description', '')} ({res.get('size_str', '')})")
    shutdown()
