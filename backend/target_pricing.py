"""
Target pricing pipeline using Target's RedSky aggregations API, driven through
a stealth CloakBrowser so it bypasses Target's Imperva bot protection.

Why a browser?  redsky.target.com is fronted by Imperva, which validates the
TLS/JA3 fingerprint of the caller — not just cookies.  Plain `requests` (even
with valid cookies minted by a real browser) gets a 403 + captcha.  Requests
issued from inside a live Chrome context (real-Chrome TLS) pass.  CloakBrowser
is a Chromium with C++-level fingerprint patches that defeats Imperva's
automation/fingerprint checks even from a datacenter IP (verified: headless,
no proxy → RedSky 200 with live prices).

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
  3. For each ingredient, walk get_all_terms() through plp_search_v2.
  4. Convert RedSky products to the Kroger shape; reuse find_best_purchase().

Reliability:
  * Search results are cached per (store_id, term) for TARGET_SEARCH_TTL seconds
    (default 6h) — far fewer requests = far less flagging.
  * On a captcha we tear down, ROTATE to a fresh proxy exit IP, back off, and
    resume pricing the still-pending ingredients. After MAX_IP_REFRESHES (default
    5) fresh IPs are all blocked we give up → caller falls back to Instacart.
  * A residential proxy is what makes this reliable from a datacenter host
    (CloakBrowser handles fingerprint; the proxy handles IP reputation).

Entry point:
    store_name, store_id, prices = price_all_target(ingredients, lat, lon)

If CloakBrowser is unavailable or Imperva persistently blocks us, every public
call returns empty and server.py transparently falls back to Instacart pricing
for Target — so this integration is strictly additive and never makes Target worse.

Self-test:  python target_pricing.py
Env overrides:  TARGET_API_KEY, TARGET_STORE_ID, CLOAK_PROXY,
                TARGET_MAX_IP_REFRESHES, TARGET_SEARCH_TTL
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from kroger_pricing import find_best_purchase, parse_size
from kroger_search_map import get_all_terms

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_BANNERS: set[str] = {"target"}

# Public web key shipped by target.com's frontend. Override with TARGET_API_KEY.
_KEY = os.environ.get("TARGET_API_KEY", "9f36aeafbe60771e321a7cc95a78140772ab3e96")

_REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
_SEARCH_URL = f"{_REDSKY_BASE}/plp_search_v2"
_STORES_URL = f"{_REDSKY_BASE}/nearby_stores_v1"

# Default store if location lookup fails (Indianapolis-area Target).
_DEFAULT_STORE_ID = os.environ.get("TARGET_STORE_ID", "1771")

# Optional residential proxy. CloakBrowser defeats Imperva's *fingerprint* check
# even from a datacenter IP, but sustained volume degrades datacenter-IP
# reputation and captchas return. A residential proxy is the reliable fix for
# production (see CloakBrowser docs). Format: http://user:pass@host:port or
# socks5://user:pass@host:port.
#
# IP rotation: on a captcha we tear down and re-launch on a FRESH exit IP, up to
# MAX_IP_REFRESHES times, before giving up and falling back to Instacart. For
# rotating-residential providers that key the exit IP off a session token in the
# username, put a literal "{session}" in the proxy URL and it's replaced with a
# new random token on each refresh, e.g.
#   http://user-session-{session}:pass@gate.provider.com:7000
# Providers that rotate per-connection need no placeholder — a new launch already
# gets a new IP.
_PROXY = os.environ.get("CLOAK_PROXY") or os.environ.get("TARGET_PROXY") or None

# How many fresh exit IPs to try before falling back to Instacart.
MAX_IP_REFRESHES = int(os.environ.get("TARGET_MAX_IP_REFRESHES", "5"))

# Cache RedSky search results per (store_id, term) to slash scrape volume — the
# single biggest reliability lever (fewer requests = less flagging). Prices don't
# change intraday, so a multi-hour TTL is safe.
_SEARCH_TTL = int(os.environ.get("TARGET_SEARCH_TTL", str(6 * 3600)))


class _ImpervaBlocked(Exception):
    """Raised when RedSky answers with a captcha challenge."""

# ---------------------------------------------------------------------------
# Store detection
# ---------------------------------------------------------------------------

def is_target_store(store_name: str) -> bool:
    lower = store_name.lower()
    # Exclude non-grocery Target sub-brands that show up in map results.
    return "target" in lower and not any(x in lower for x in ("optical", "pharmacy"))


# ---------------------------------------------------------------------------
# CloakBrowser singleton — all access pinned to one worker thread
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloak-target")
_browser = None          # cloakbrowser Browser (lives on the worker thread)
_ctx = None              # browser context with warmed Imperva cookies
_session_lock = threading.Lock()
_proxy_session_id: Optional[str] = None  # current rotating-proxy session token


def _rotate_proxy_session() -> None:
    """Pick a new rotating-proxy session token → next launch gets a fresh exit IP."""
    global _proxy_session_id
    _proxy_session_id = uuid.uuid4().hex[:12]


def _current_proxy() -> Optional[str]:
    """The proxy URL with the current session token substituted (if any)."""
    if not _PROXY:
        return None
    if "{session}" in _PROXY:
        return _PROXY.replace("{session}", _proxy_session_id or uuid.uuid4().hex[:12])
    return _PROXY


def _bootstrap_session():
    """(worker thread) Launch CloakBrowser on the current proxy session, open a
    context, and warm Imperva cookies. Raises on failure so the caller can fall
    back to Instacart."""
    global _browser, _ctx
    from cloakbrowser import launch  # imported here so a missing dep degrades gracefully

    # Tear down any half-dead session first.
    _teardown_session()
    if _proxy_session_id is None:
        _rotate_proxy_session()

    proxy = _current_proxy()
    kwargs: dict = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["geoip"] = True  # match timezone/locale to the proxy exit IP
    try:
        _browser = launch(**kwargs)
    except Exception:
        # geoip extra may be missing; retry without it.
        kwargs.pop("geoip", None)
        _browser = launch(**kwargs)

    _ctx = _browser.new_context()
    page = _ctx.new_page()
    page.goto("https://www.target.com/", wait_until="domcontentloaded", timeout=45000)
    # Let Imperva's JS challenge run and set its clearance cookie before we hit
    # the API — calling RedSky too eagerly returns a captcha.
    time.sleep(3)
    page.close()
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


def _ensure_ctx():
    """(worker thread) Return a live context, bootstrapping if needed."""
    global _ctx
    if _ctx is None:
        _bootstrap_session()
    return _ctx


def _redsky_get(url: str) -> str:
    """(worker thread) GET a RedSky URL through the browser context. Returns the
    response body on 200, "" on a non-captcha error, and raises _ImpervaBlocked
    on a captcha challenge. Re-bootstrapping is handled one level up (in
    _do_pricing) to avoid launch storms that worsen IP reputation."""
    ctx = _ensure_ctx()
    resp = ctx.request.get(url, timeout=30000)
    text = resp.text()
    if resp.status == 403 and "captcha" in text.lower():
        raise _ImpervaBlocked()
    if resp.status != 200:
        return ""
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
    """Convert a RedSky plp_search_v2 product into the Kroger product shape."""
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

def _resolve_store_id(lat: float, lon: float) -> str:
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
_search_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def _search(query: str, store_id: str, num_results: int = 24) -> list[dict]:
    # 24 (vs RedSky's default page of ~28) gives find_best_purchase enough
    # candidates to reliably surface the cheapest matching size/variant; with
    # only ~10 the cheapest option is sometimes outside the result window.
    cache_key = (store_id, query.lower())
    cached = _search_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]

    url = (f"{_SEARCH_URL}?key={_KEY}&keyword={requests_quote(query)}&channel=WEB"
           f"&count={num_results}&offset=0&page=/s/{requests_quote(query)}"
           f"&platform=desktop&pricing_store_id={store_id}&store_ids={store_id}"
           f"&scheduled_delivery_store_id={store_id}&visitor_id={uuid.uuid4().hex.upper()}")
    text = _redsky_get(url)  # may raise _ImpervaBlocked → handled in _do_pricing
    if not text:
        return []
    try:
        import json
        products = (json.loads(text).get("data", {})
                    .get("search", {}).get("products", []))
    except Exception:
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
    _search_cache[cache_key] = (time.time() + _SEARCH_TTL, out)
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


def _do_pricing(ingredients: dict, lat: float, lon: float) -> tuple[Optional[str], dict]:
    """(worker thread) Resolve store + price all ingredients, healing through
    captchas by rotating to a fresh exit IP.

    On a block we tear down, rotate the proxy session (new IP), back off, and
    resume pricing only the ingredients still pending — so intermittent blocks
    progressively complete the basket. After MAX_IP_REFRESHES fresh IPs are all
    blocked we give up and return ({}) so the caller falls back to Instacart for
    the whole store.

    Pricing is sequential because the sync browser context is single-threaded;
    cached terms make repeat baskets nearly free."""
    prices: dict = {}
    pending = dict(ingredients)
    store_id: Optional[str] = None
    refreshes = 0

    while pending:
        try:
            _ensure_ctx()  # bootstrap (raises only on launch failure → Instacart)
            if store_id is None:
                store_id = _resolve_store_id(lat, lon)
                print(f"[Target] Pricing at store #{store_id}", flush=True)

            for name in list(pending):
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

        except _ImpervaBlocked:
            if refreshes >= MAX_IP_REFRESHES:
                print(f"[Target] Still blocked after {refreshes} IP refreshes — "
                      f"falling back to Instacart for this store.", flush=True)
                return store_id, {}
            refreshes += 1
            print(f"[Target] Captcha — rotating exit IP "
                  f"(refresh {refreshes}/{MAX_IP_REFRESHES}).", flush=True)
            _teardown_session()
            _rotate_proxy_session()
            time.sleep(min(1.0 * refreshes, 5.0) + random.uniform(0, 0.75))  # backoff + jitter

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

    Returns (display_name, store_id, prices). `prices` is empty if CloakBrowser
    is unavailable or Imperva blocks us, in which case the caller falls back to
    Instacart.
    """
    with _session_lock:  # serialize concurrent pricing requests onto one browser
        try:
            store_id, prices = _executor.submit(_do_pricing, ingredients, lat, lon).result()
        except Exception as e:
            print(f"[Target] Direct pricing unavailable ({repr(e)[:140]}) — "
                  "falling back to Instacart.", flush=True)
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
              "Install with: pip install cloakbrowser playwright")
    for ing, res in out.items():
        print(f"  {ing:18s} ${res.get('total_cost', 0):6.2f}  "
              f"{res.get('description', '')} ({res.get('size_str', '')})")
    shutdown()
