import asyncio
import hmac
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import uvicorn
from fastapi import FastAPI, HTTPException, APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import os
import uuid
import config
import meal_planner
import fridge_manager
import geo_utils
import optimizer
import pricing_pool
import kroger_async
from kroger_async import is_kroger_banner
from aldi.aldi_pricing import price_all_aldi, is_aldi_store
import kingsoopers_pricing
from kingsoopers_pricing import is_king_soopers_store
import instacart_pricing
from instacart_pricing import get_instacart_slug
import walmart_pricing
from walmart_pricing import is_walmart_store
import trader_joes_pricing
from trader_joes_pricing import is_trader_joes_store
import meijer_pricing
from meijer_pricing import is_meijer_store
import target_pricing
from target_pricing import is_target_store
import iga_pricing
from iga_pricing import is_iga_store
import matcher
import coupon_scraper
from kroger_pricing import aggregate_ingredients
from geopy.geocoders import Nominatim

import logging
import traceback

# Setup logging
logging.basicConfig(filename='server_error.log', level=logging.ERROR)

SERVER_VERSION = "3.0.0-SUPABASE"
print(f"\nBASKET BUDDY SERVER STARTING - VERSION: {SERVER_VERSION}", flush=True)

app = FastAPI()
router = APIRouter(prefix="/api")


# ── Supabase Auth Dependency ───────────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Extract the Supabase user_id from the JWT in the Authorization header.
    Returns None for anonymous requests (no token provided).
    """
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    try:
        from db import db
        user = db.client.auth.get_user(token)
        return user.user.id if user and user.user else None
    except Exception as e:
        print(f"[Auth] JWT verification failed: {e}", flush=True)
        return None


# ── Helper: save results to Supabase ──────────────────────────────────────
def _save_results(user_id: str | None, prefs: "UserPreferences", meal_plan: list,
                  shopping_list: list, route: list, total_cost: float,
                  cheapest_store_name: str, cheapest_store_cost: float,
                  total_time_minutes: float) -> None:
    """Persist the generated plan and route to Supabase when a user is authenticated."""
    if not user_id:
        return
    try:
        from db import db
        plan = db.save_meal_plan(
            user_id=user_id,
            preferences={
                "address": prefs.address,
                "budget": prefs.budget,
                "calorie_target": prefs.calorie_target,
                "household_size": prefs.household_size,
                "days_plan": prefs.days_plan,
                "meals_per_day": prefs.meals_per_day,
                "dietary_restrictions": prefs.dietary_restrictions,
                "health_issues": prefs.health_issues,
                "cuisines": prefs.cuisines,
            },
            meals=meal_plan,
        )
        db.save_shopping_route(plan["id"], {
            "total_cost": total_cost,
            "total_time_minutes": total_time_minutes,
            "route": route,
            "cheapest_single_store_name": cheapest_store_name,
            "cheapest_single_store_cost": cheapest_store_cost,
        })
        print(f"[Supabase] Saved plan {plan['id']} for user {user_id}", flush=True)
    except Exception as e:
        print(f"[Supabase] Failed to save results: {e}", flush=True)


# ── Coupon-first pricing helpers ──────────────────────────────────────────
STORE_MERCHANT_MAP = {
    "kroger": "kroger", "king soopers": "kroger", "aldi": "aldi",
    "walmart": "walmart", "target": "target", "trader joe": "trader joe",
    "meijer": "meijer", "costco": "costco",
}

def _resolve_merchant(store_key: str) -> str:
    lower = store_key.lower()
    for keyword, merchant in STORE_MERCHANT_MAP.items():
        if keyword in lower:
            return merchant
    return lower

def _overlay_coupon_prices(store_key: str, price_db: dict[str, dict],
                           postal: str, to_buy: dict[str, dict]) -> dict[str, str]:
    """Check coupons for this store and overlay coupon prices on price_db.
    Returns a dict {item_key: source} for items that had coupon matches.

    Never raises. Coupons are an optional overlay — a DB/network failure (e.g.
    Supabase unreachable, or bad credentials) must not sink an otherwise-complete
    plan. NB the `import` has to be inside the try as well: db.py builds its
    Supabase client at module scope, so a misconfigured SUPABASE_URL raises on
    import, not on the query — which used to 500 the whole request from a line
    that was deliberately outside the guard.
    """
    merchant = _resolve_merchant(store_key)
    try:
        from db import db
        coupons = db.get_coupons_by_postal(postal, merchant=merchant)
    except Exception as e:
        print(f"[Coupon] Lookup failed for {store_key} ({repr(e)[:80]}) — skipping coupons.", flush=True)
        return {}
    if not coupons:
        return {}

    sources = {}
    for ing_name, data in to_buy.items():
        key = ing_name.lower().strip()
        match = matcher.match_item_to_coupon(ing_name, coupons)
        if match and match.get("price", 0) > 0:
            unit_price = match["price"]
            qty = float(data.get("qty", 1) or 1)
            price_db[key] = (unit_price / qty) if qty else unit_price
            sources[key] = "coupon"
            print(f"  [Coupon] {ing_name}: ${unit_price:.2f} at {store_key}", flush=True)
    return sources


@app.on_event("shutdown")
def _close_target_browser():
    # Free the persistent CloakBrowser (~250MB) used for direct Target pricing.
    try:
        target_pricing.shutdown()
    except Exception:
        pass
    try:
        walmart_pricing.shutdown()
    except Exception:
        pass

@app.middleware("http")
async def catch_exceptions_middleware(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        # Log the full traceback SERVER-SIDE only. It used to be serialised into
        # the response body, handing every caller our file paths, module layout
        # and local variable context on any 500.
        ref = uuid.uuid4().hex[:8]
        tb = traceback.format_exc()
        logging.error("[%s] Unhandled exception: %s\n%s", ref, exc, tb)
        # Never let the error REPORTER raise. On a Windows console (cp1252) any
        # traceback quoting a non-ASCII source line — this file has emoji in its
        # log strings — made print() itself throw, replacing the real exception
        # with a UnicodeEncodeError and hiding the actual failure.
        try:
            print(f"CRITICAL ERROR [{ref}]:\n{exc}\n{tb}", flush=True)
        except Exception:
            safe = tb.encode("ascii", "replace").decode("ascii")
            print(f"CRITICAL ERROR [{ref}] (non-ascii stripped):\n{safe}", flush=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong generating your plan. "
                               f"Please try again. (ref {ref})", "ref": ref},
        )

# --- CORS CONFIGURATION START ---
# `allow_origins=["*"]` together with `allow_credentials=True` is rejected by
# browsers per the CORS spec (a wildcard origin can't be used with credentials),
# so that combination never actually worked — it only appeared to because no
# credentialed request was ever made. Allow an explicit list from the
# environment; fall back to wildcard WITHOUT credentials, which is what the app
# genuinely needs (the API takes a bearer token, not cookies).
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=bool(_cors_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
# --- CORS CONFIGURATION END ---


# ── Rate limiting ──────────────────────────────────────────────────────────
# Every endpoint was unauthenticated and unthrottled. /autocomplete bills a
# Google Places call per request, /generate_plan drives a multi-store scrape,
# and /prewarm used to spawn a browser warm per call — all reachable by anyone
# who knows the URL. This is a small in-process limiter (fixed window per
# client IP); it needs no extra dependency and no shared store, which is right
# for a single-instance deploy.
class _RateLimiter:
    def __init__(self):
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str, limit: int, window: float) -> bool:
        """True if allowed. Prunes as it goes so the dict can't grow forever."""
        now = time.time()
        key = (bucket, client)
        with self._lock:
            if len(self._hits) > 10_000:            # cheap guard against IP churn
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - window}
            times = [t for t in self._hits.get(key, ()) if t > now - window]
            if len(times) >= limit:
                self._hits[key] = times
                return False
            times.append(now)
            self._hits[key] = times
            return True


_rate_limiter = _RateLimiter()

_RATE_LIMITS = {                     # bucket → (max requests, window seconds)
    "plan": (int(os.getenv("RATE_LIMIT_PLAN", "10")), 600.0),
    "prewarm": (int(os.getenv("RATE_LIMIT_PREWARM", "60")), 600.0),
    "autocomplete": (int(os.getenv("RATE_LIMIT_AUTOCOMPLETE", "120")), 60.0),
    # Tight: this bucket only ever sees one caller (the daily local mint
    # script), so a burst here is a sign of someone guessing SESSION_UPLOAD_TOKEN.
    "internal_session": (int(os.getenv("RATE_LIMIT_INTERNAL_SESSION", "20")), 600.0),
}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str):
    """FastAPI dependency enforcing `bucket`'s limit for the calling IP."""
    if bucket not in _RATE_LIMITS:
        raise KeyError(f"unknown rate-limit bucket {bucket!r}")

    def _dep(request: Request):
        # Read the limit per call rather than closing over it at import time, so
        # it stays adjustable (and testable) without recreating the dependency.
        limit, window = _RATE_LIMITS[bucket]
        if not _rate_limiter.check(bucket, _client_ip(request), limit, window):
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in a few minutes "
                       f"(limit: {limit} per {int(window / 60)} min).",
            )

    return _dep

# Data Models
class UserPreferences(BaseModel):
    """Plan inputs.

    The numeric fields are BOUNDED. They used to be unconstrained, so
    meals_per_day=0 was a ZeroDivisionError, days_plan=-5 a 500, and
    days_plan=365 a 2000-meal basket fanned out across ten retailers. The web
    build renders `keyboardType="numeric"` as a plain text input, so negatives
    and exponents were reachable from the UI, not just from curl.
    """
    address: str = Field(min_length=1, max_length=300)
    # Not bounded to 12: the server reads values > 12 as MINUTES (see the
    # normalisation in generate_plan), so the upper bound is a day in minutes.
    shopping_time_hours: float = Field(default=3.0, gt=0, le=1440)
    budget: float = Field(default=150.0, ge=0, le=100_000)
    calorie_target: int = Field(default=2000, ge=800, le=8000)
    household_size: int = Field(default=1, ge=1, le=meal_planner.MAX_HOUSEHOLD)
    days_plan: int = Field(default=7, ge=1, le=meal_planner.MAX_DAYS)
    meals_per_day: int = Field(default=3, ge=1, le=meal_planner.MAX_MEALS_PER_DAY)
    dietary_restrictions: Optional[str] = Field(default=None, max_length=2000)
    allergies: Optional[str] = Field(default=None, max_length=2000)
    # Free-form "never include these" list from the ingredient picker. This used
    # to be collected by the UI and dropped on the floor before the request.
    avoid_ingredients: Optional[str] = Field(default=None, max_length=4000)
    health_issues: Optional[str] = Field(default=None, max_length=2000)
    cuisines: Optional[str] = Field(default=None, max_length=500)
    experiment: bool = True
    cook_time: str = Field(default="30-45 minutes", max_length=100)
    fridge_image_path: Optional[str] = None
    fridge_items: Optional[str] = Field(default=None, max_length=4000)
    has_costco_card: bool = False
    dev_mode: int = 1

class PlanRequest(BaseModel):
    preferences: UserPreferences

class WalmartPriceEntry(BaseModel):
    """One ingredient's device-sourced Walmart price — see
    frontend/services/walmartDirect.ts. unit_price is the matched product's
    own price, NOT a qty-scaled total (the device path doesn't run the
    buy-N-units optimization walmart_pricing.find_best_purchase does
    server-side) — Phase 2 uses it as price_database's per-unit figure
    directly, same slot _apply_prices() would fill from a server-priced
    store."""
    unit_price: float = Field(gt=0, le=500)
    description: str = Field(default="", max_length=300)
    brand: str = Field(default="", max_length=200)
    size_str: str = Field(default="", max_length=100)

class WalmartPhase2Request(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    walmart_prices: dict[str, WalmartPriceEntry] = Field(default_factory=dict)
    session_source: str = Field(default="", max_length=200)

class PriceListItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    qty: float = Field(default=1.0, gt=0, le=10_000)
    unit: str = Field(default="ct", max_length=40)

class PriceListRequest(BaseModel):
    address: str = Field(min_length=1, max_length=300)
    shopping_time_hours: float = Field(default=3.0, gt=0, le=1440)
    # Bounded: each item fans out a search across every store in range.
    items: List[PriceListItem] = Field(min_length=1, max_length=300)
    has_costco_card: bool = False

@app.get("/")
def read_root():
    return {"message": "Route 52 Backend is running!"}

@router.get("/")
def read_root_api():
    return {"message": "Route 52 Backend is running!"}


class PrewarmRequest(BaseModel):
    address: str
    shopping_time_hours: float = 3.0


def _store_failed(chain: str, reason) -> None:
    """One uniform, greppable line for every store pricer that failed or came
    back empty — `grep "STORE FAILED" <render logs>` finds every skip and why,
    instead of hunting through a dozen differently-worded per-chain messages
    (or, in a few spots, silent `except: pass` with nothing logged at all).
    Callers already catch the exception and skip/fall back on their own —
    this is purely the visibility layer, never control flow."""
    print(f"[STORE FAILED] {chain}: {reason}", flush=True)


def _geocode_address(address: str):
    """Geocode an address to (lat, lon), using the shared geocode cache.

    Google is tried FIRST because it's the same source as the /autocomplete the
    user picked their address from — so anything selectable resolves. Nominatim
    (OpenStreetMap) is only a fallback: it's missing many exact US street
    addresses (e.g. it returns None for "5530 Pine Valley Drive, Zanesville, OH"
    that Google resolves fine), which previously 400'd the whole plan request.
    """
    from cache_manager import cache
    address = (address or "").strip()
    if not address:
        return None
    cache_key = {"func": "geocode", "address": address}
    cached_loc = cache.get(cache_key)
    if cached_loc:
        return cached_loc['lat'], cached_loc['lon']

    lat = lon = None
    # Primary: Google (near-complete US coverage; matches the autocomplete source).
    try:
        if getattr(config, "GOOGLE_MAPS_API_KEY", None):
            import googlemaps
            res = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY).geocode(address)
            if res:
                g = res[0]["geometry"]["location"]
                lat, lon = g["lat"], g["lng"]
    except Exception as e:
        print(f"[Geocode] Google failed ({repr(e)[:80]}), trying Nominatim.", flush=True)
    # Fallback: Nominatim (OSM).
    if lat is None:
        try:
            location = Nominatim(user_agent="basket_buddy_backend").geocode(address, timeout=10)
            if location:
                lat, lon = location.latitude, location.longitude
        except Exception as e:
            print(f"[Geocode] Nominatim failed ({repr(e)[:80]}).", flush=True)

    if lat is None:
        return None
    cache.set(cache_key, {'lat': lat, 'lon': lon})
    return lat, lon


def _warm_chain(name: str, ensure_fn) -> bool:
    """Mint+persist one chain's cookie (CloakBrowser warm); never raises. The warm
    saves the cookie to disk on success, so it survives even if the chain later
    proves out of range. Returns True if the warm succeeded, False otherwise."""
    try:
        ensure_fn()
        return True
    except Exception as e:
        print(f"[Prewarm] {name} warm failed ({repr(e)[:80]}).", flush=True)
        return False


def _warm_instacart(reason: str) -> None:
    """Warm the shared Instacart session so Target's Instacart fallback is already
    hot. Target's direct (RedSky/Imperva) path fails often; when it does, pricing
    falls back to Instacart — and without this that fallback pays a cold browser
    bootstrap on the critical path at plan time. Never raises."""
    try:
        print(f"[Prewarm] {reason} — warming Instacart fallback.", flush=True)
        instacart_pricing._get_session()
        print("[Prewarm] Instacart fallback warmed.", flush=True)
    except Exception as e:
        print(f"[Prewarm] Instacart fallback warm failed ({repr(e)[:80]}).", flush=True)


_WARM_CHAINS = (
    ("Walmart", lambda n: "walmart" in n.lower(), lambda: walmart_pricing._ensure_http_session()),
    ("Target", lambda n: target_pricing.is_target_store(n), lambda: target_pricing._ensure_http_session()),
)


@router.post("/prewarm", dependencies=[Depends(rate_limit("prewarm"))])
def prewarm(request: PrewarmRequest):
    """Fire-and-forget warm-up, fired on Continue once address + shopping time
    are known. Geocodes, resolves the drive isochrone + Google Places stores
    (priming the SAME caches generate_plan reads), then warms ONLY the chains
    actually found in range — no chain is ever warmed speculatively.

    (This used to also fire an eager, unconditional warm of every chain the
    instant an address suggestion was tapped, before the isochrone was even
    known — that meant Render was launching browsers for stores nowhere near
    the user. Removed: warming now only ever happens for stores this address
    actually found.)

    Returns immediately; all work happens on a shared bounded-pool thread. If
    the user dawdles past a cookie's TTL the pricing run just re-mints
    (existing fallback) — so this is a best-effort speedup, never a
    correctness risk."""
    address = (request.address or "").strip()
    sh_hours = request.shopping_time_hours

    def _resolve_then_warm_in_range():
        loc = None
        try:
            loc = _geocode_address(address)  # (lat, lon) or None; primes geocode cache
        except Exception as e:
            print(f"[Prewarm] geocode failed ({e}).", flush=True)
        if not loc:
            return

        # Resolve nearby stores, priming the same isochrone + store caches
        # generate_plan reads (mirror its math so the cache keys match).
        store_names: list[str] = []
        try:
            hrs = sh_hours / 60.0 if sh_hours > 12 else sh_hours  # >12 ⇒ minutes
            one_way_secs = int((hrs * 3600) / 4)
            iso = geo_utils.get_travel_isochrone(loc, one_way_secs)
            if iso:
                stores, _addrs = geo_utils.find_eligible_stores_google(iso, loc)
                store_names = list(stores.keys())
                print(f"[Prewarm] Nearby stores resolved + cached ({len(store_names)} found).", flush=True)
        except Exception as e:
            print(f"[Prewarm] store search failed ({repr(e)[:80]}).", flush=True)

        warmers, skipped = [], []
        for name, in_range, ensure_fn in _WARM_CHAINS:
            (warmers if any(in_range(n) for n in store_names) else skipped).append((name, ensure_fn))

        # Out of isochrone: do no work at all for these chains.
        if skipped:
            print(f"[Prewarm] Out of isochrone — no work done: "
                  f"{', '.join(n for n, _ in skipped)}.", flush=True)
        if not warmers:
            return

        # In range: warm it (cheap reuse if a Supabase/disk cookie is already
        # good — see each chain's _ensure_http_session). Sequential on purpose:
        # the browser gate serializes these anyway, so parallelism only
        # manufactures gate timeouts.
        results = {name: _warm_chain(name, ensure_fn) for name, ensure_fn in warmers}
        print(f"[Prewarm] Done (warmed in-range: {', '.join(n for n, _ in warmers)}).", flush=True)
        # If Target is in range but its warm failed, warm the Instacart fallback it
        # will drop to during pricing.
        if not results.get("Target", True):
            _warm_instacart("Target warm failed")

    # Run on the shared bounded pool under a single-flight key rather than a
    # fresh unbounded daemon thread per call. /prewarm is unauthenticated and
    # fires on every Continue tap, so a raw thread-per-call let a user (or a
    # bot) stack arbitrarily many browser warms, all fighting over the same
    # one-at-a-time browser gate. One warm at a time is all that was ever
    # useful — the cookies are shared and cached on disk.
    if pricing_pool.submit_chain("prewarm", None, _resolve_then_warm_in_range) is None:
        print("[Prewarm] already running — not starting another.", flush=True)
        return {"status": "already_warming"}
    return {"status": "warming"}


@router.get("/autocomplete", dependencies=[Depends(rate_limit("autocomplete"))])
def autocomplete(q: str = ""):
    """Address type-ahead for the /location screen — proxies Google Places
    Autocomplete with the same key the store search uses. Returns up to 5 US
    address suggestion strings; never throws (empty list on any error)."""
    q = (q or "").strip()
    if len(q) < 3:
        return {"suggestions": []}
    try:
        import googlemaps
        gmaps = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)
        preds = gmaps.places_autocomplete(q, components={"country": "us"})
        suggestions = [p.get("description") for p in preds if p.get("description")][:5]
        return {"suggestions": suggestions}
    except Exception as e:
        print(f"[Autocomplete] failed ({repr(e)[:80]}).", flush=True)
        return {"suggestions": []}


@router.get("/walmart/session", dependencies=[Depends(rate_limit("autocomplete"))])
def walmart_client_session():
    """EXPERIMENTAL (2026-09-20): hands the app a Walmart cookie+UA to replay
    Walmart's search endpoint directly from the user's own device/IP instead
    of this server's — see frontend/services/walmartDirect.ts. Testing
    whether spreading requests across real user IPs avoids the single-IP
    ban pattern Render's shared egress IP keeps hitting. Falls back to a
    live CloakBrowser mint (~30-60s) when nothing cached validates — these
    cookies have been observed dying within minutes, so that's the common
    case, not the exception (see walmart_pricing.get_client_session)."""
    session = walmart_pricing.get_client_session()
    if not session:
        raise HTTPException(status_code=503, detail="No live Walmart session available right now.")
    return session


@router.get("/walmart/session_pool", dependencies=[Depends(rate_limit("autocomplete"))])
def walmart_client_session_pool():
    """EXPERIMENTAL (2026-09-20): dumps every cached Walmart cookie this
    process knows about (local pool file + Supabase pool), unvalidated, so
    the app can test each one itself from the device and see how many
    survive replay from a real phone — see
    walmart_pricing.get_client_session_pool and
    frontend/services/walmartDirect.ts's testWalmartCookiePoolDirect."""
    return {"sessions": walmart_pricing.get_client_session_pool()}


def _build_plan_pricing(prefs: "UserPreferences", defer_walmart: bool = False) -> dict:
    """Steps 1-7: meal plan, store search, and pricing every store EXCEPT
    (when defer_walmart) Walmart, whose key is left in price_database with
    an empty dict rather than attempted or dropped — a caller wanting
    Walmart included (see the /generate_plan/phase1+2 pair below) fills it
    in itself before calling _finalize_plan. Stops short of the
    drop-unpriced-stores / coupon / optimizer / response steps — those are
    _finalize_plan's job, shared by both the single-shot legacy endpoint and
    the two-phase native-device-pricing flow."""

    # 1. Geocode Address (Google first — same source as autocomplete — then OSM)
    user_loc = _geocode_address(prefs.address)
    if not user_loc:
        print(f"[Geocode] Could not resolve address: {prefs.address!r}", flush=True)
        raise HTTPException(status_code=400, detail="Address not found")
    print(f"Using location for: {prefs.address}")
    
    # 2. (was: publish this request's calorie total to config.TOTAL_WEEKLY_CALORIES)
    # Removed. Nothing reads that global — meal_planner takes calorie_target as an
    # argument — so the only thing the assignment did was let concurrent requests
    # stomp each other's value on the threadpool. Don't reintroduce it; pass
    # per-request values as arguments.

    # 3. Handle Fridge Items
    plan_warnings: list[str] = []
    fridge_items = prefs.fridge_items or ""
    if prefs.fridge_image_path and os.path.exists(prefs.fridge_image_path):
        # fridge_manager.analyze_fridge_image is a stub that always returns "" —
        # there is no vision backend wired up. Say so instead of appearing to
        # have read the photo and found nothing in it.
        vision_items = fridge_manager.analyze_fridge_image(prefs.fridge_image_path)
        if vision_items:
            fridge_items = f"{fridge_items}, {vision_items}"
        else:
            plan_warnings.append(
                "Fridge-photo scanning isn't available yet — list your at-home "
                "items as text so they can be excluded from the shopping list."
            )

    # 4. Generate Meal Plan
    # Fetch meals from Supabase (fall back to meals.json if DB unavailable)
    print(f"\nFINAL FRIDGE LIST FOR MEAL PLANNER: {repr(fridge_items)}", flush=True)
    try:
        from db import db
        raw_meals = db.get_meals()
        db_meals = []
        for m in raw_meals:
            if isinstance(m.get("ingredients"), str):
                m["ingredients"] = json.loads(m["ingredients"])
            if isinstance(m.get("instructions"), str):
                m["instructions"] = json.loads(m["instructions"])
            db_meals.append(m)
    except Exception as e:
        print(f"[Supabase] Could not fetch meals from DB ({e}), falling back to meals.json", flush=True)
        db_meals = None
    try:
        meal_plan, ingredient_data, mp_warnings = meal_planner.create_weekly_meal_plan(
            prefs.days_plan, prefs.meals_per_day, prefs.calorie_target,
            prefs.dietary_restrictions, prefs.cuisines, fridge_items, prefs.experiment, prefs.cook_time,
            prefs.health_issues, prefs.budget, prefs.household_size, meals=db_meals,
            allergies=prefs.allergies or "",
            avoid_ingredients=prefs.avoid_ingredients or "",
        )
    except meal_planner.NoSafeMealsError as e:
        # The user's restrictions exclude every recipe. This is a real answer,
        # not a server fault — and far better than the old behaviour of quietly
        # dropping the restrictions and serving food they can't eat.
        raise HTTPException(status_code=422, detail=str(e))
    plan_warnings.extend(mp_warnings)

    if not ingredient_data:
        raise HTTPException(status_code=500, detail="Failed to generate meal plan")

    # Aggregate ingredient totals across all meals using proper base-unit math
    # (handles mixed units for the same ingredient across different meals).
    # meal_plan quantities are already scaled by household_size, so pass 1 here.
    aggregated = aggregate_ingredients(meal_plan, household_size=1)

    to_buy_quantities = {}
    at_home_ingredients = []

    for name, data in aggregated.items():
        # ingredient_data keys are lowercased; match by normalizing
        ing_meta = ingredient_data.get(name.lower().strip(), {})
        if ing_meta.get("is_at_home"):
            at_home_ingredients.append({"name": name, "qty": data["qty"], "unit": data["unit"]})
        else:
            to_buy_quantities[name] = {"qty": data["qty"], "unit": data["unit"]}

    print("\n" + "-" * 40)
    print(f"📋 INGREDIENTS NEEDED (TO BUY) [{len(to_buy_quantities)} items]:")
    for item, data in to_buy_quantities.items():
        print(f"   • {item.title()} ({data.get('qty')} {data.get('unit')})")
    print(f"🏠 INGREDIENTS ALREADY AT HOME [{len(at_home_ingredients)} items]:")
    for item in at_home_ingredients:
        print(f"   • {item['name'].title()} ({item['qty']} {item['unit']})")
    print("-" * 40)

    # 5. Find Stores & Optimize
    # Normalize Shopping Time: if user entered > 10, they probably meant minutes
    sh_hours = prefs.shopping_time_hours
    if sh_hours > 12: # Likely minutes
        sh_hours = sh_hours / 60.0

    MAX_TIME_SECS = sh_hours * 3600
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(user_loc, ONE_WAY_TIME_SECONDS)
    
    if not isochrone_geometry:
        # Fallback: 15 km bounding box around user
        print("[Server] ORS isochrone failed — using 15 km bounding-box fallback.", flush=True)
        lat0, lon0 = user_loc
        D = 0.135  # ~15 km in degrees
        isochrone_geometry = {
            "type": "Polygon",
            "coordinates": [[
                [lon0 - D, lat0 - D],
                [lon0 + D, lat0 - D],
                [lon0 + D, lat0 + D],
                [lon0 - D, lat0 + D],
                [lon0 - D, lat0 - D],
            ]]
        }
    
    # --- STORE FILTERING ---
    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, user_loc)
    print(f"DEBUG: Found {len(STORE_LOCATIONS)} raw stores: {list(STORE_LOCATIONS.keys())}")
    
    # Costco Membership Filter
    print(f"DEBUG: Costco Card Preference = {prefs.has_costco_card}")
    if not prefs.has_costco_card:
        print("🚫 Filtering out Costco stores...")
        filtered_locations = {}
        filtered_addresses = {}
        for k, v in STORE_LOCATIONS.items():
            k_lower = k.lower()
            if "costco" not in k_lower:
                filtered_locations[k] = v
                filtered_addresses[k] = STORE_ADDRESSES.get(k, "")
            else:
                print(f"   - Removed Costco store: {k}")
        STORE_LOCATIONS = filtered_locations
        STORE_ADDRESSES = filtered_addresses

    # Filter to unique chains closest to user
    STORE_LOCATIONS_RAW, STORE_ADDRESSES_RAW = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, user_loc)
    
    # Strip all keys to prevent mismatches between matrix, price db, and optimizer
    STORE_LOCATIONS = {k.strip(): v for k, v in STORE_LOCATIONS_RAW.items()}
    STORE_ADDRESSES = {k.strip(): v for k, v in STORE_ADDRESSES_RAW.items()}
    
    print(f"DEBUG: Stores after chain filtering & stripping: {list(STORE_LOCATIONS.keys())}")

    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = []
        for name, (lat, lon) in STORE_LOCATIONS.items():
            dist_sq = (lat - user_loc[0])**2 + (lon - user_loc[1])**2
            distances.append((dist_sq, name, (lat, lon)))
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
        STORE_ADDRESSES = {name: STORE_ADDRESSES[name] for name in STORE_LOCATIONS}
    
    all_coords = [user_loc] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)
    
    # Step 7: Get real prices for each store; exclude any store where pricing fails.
    lat, lon = user_loc
    price_database: dict = {k.strip(): {} for k in STORE_LOCATIONS.keys()}
    real_priced_keys: set = set()
    product_details: dict = {}  # (store_key, ing_key) → {product_name, size_str}
    costco_estimates: dict = {}  # store_key → {"distance_km": float, "store": str} when proxied

    # shopping_list is needed by the optimizer regardless of pricing source.
    shopping_list = [
        {"name": name, "qty": float(data.get("qty", 1) or 1)}
        for name, data in to_buy_quantities.items()
    ]

    # --- Real pricing -------------------------------------------------------
    # Every store is independent, so they are priced CONCURRENTLY (one thread
    # each) and the results applied sequentially in this main thread — that
    # keeps the shared dicts (price_database / product_details / ...) race-free
    # while collapsing wall-clock from the SUM of all stores to the SLOWEST one.
    kroger_key = next((k for k in price_database if is_kroger_banner(k)), None)
    aldi_key = next((k for k in price_database if is_aldi_store(k)), None)
    meijer_key = next((k for k in price_database if is_meijer_store(k)), None)
    loop_keys = [
        k for k in list(price_database.keys())
        if not is_kroger_banner(k) and not is_aldi_store(k) and not is_meijer_store(k)
    ]
    if defer_walmart:
        # Left in price_database (empty dict) rather than removed — the
        # phase2 endpoint fills it in from the device before _finalize_plan
        # runs; if it never gets filled, _finalize_plan's normal
        # drop-unpriced-stores step excludes it exactly like any other
        # store real pricing couldn't cover.
        loop_keys = [k for k in loop_keys if not is_walmart_store(k)]

    def _apply_prices(store_key, prices, log_each=False):
        """Write one store's real prices into price_database + product_details."""
        for ing_name, result in prices.items():
            total_cost = result.get("total_cost", 0.0)
            qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
            key = ing_name.lower().strip()
            unit_price = total_cost / qty if qty else total_cost
            price_database[store_key][key] = unit_price
            if log_each:
                print(f"  [ALDI price] {ing_name!r}: total=${total_cost:.2f} qty={qty} unit=${unit_price:.3f} | {result.get('description','')}", flush=True)
            if result.get("description"):
                brand = result.get("brand", "")
                product_details[(store_key, key)] = {
                    "product_name": f"{brand} {result['description']}".strip() if brand else result["description"],
                    "size_str": result.get("size_str", ""),
                    "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                }
        real_priced_keys.add(store_key)

    # ---- Per-store fetchers (network only; no shared-state mutation) ----
    def _fetch_kroger():
        try:
            _, _, prices = asyncio.run(
                kroger_async.price_all_async(to_buy_quantities, lat, lon, store_name=kroger_key)
            )
        except Exception as e:
            _store_failed("Kroger", e)
            prices = {}
        if not prices:
            ks_key = next((k for k in price_database if is_king_soopers_store(k)), None)
            if ks_key:
                print("[KS] Kroger API empty and King Soopers store in route — trying Instacart fallback.", flush=True)
                try:
                    _, _, ks_prices = kingsoopers_pricing.price_all_ks(
                        to_buy_quantities, lat, lon
                    )
                    if ks_prices:
                        prices = ks_prices
                        print(f"[KS] Instacart fallback priced {len(ks_prices)} ingredients.", flush=True)
                except Exception as e:
                    _store_failed("King Soopers (Instacart fallback)", e)
        return prices

    def _fetch_aldi():
        aldi_lat, aldi_lon = STORE_LOCATIONS.get(aldi_key, (lat, lon))
        try:
            _, _, prices = price_all_aldi(to_buy_quantities, aldi_lat, aldi_lon)
            return prices
        except Exception as e:
            _store_failed("ALDI", e)
            return {}

    def _fetch_meijer():
        m_lat, m_lon = STORE_LOCATIONS.get(meijer_key, (lat, lon))
        try:
            _, _, prices = meijer_pricing.price_all_meijer(to_buy_quantities, m_lat, m_lon)
            return prices
        except Exception as e:
            _store_failed("Meijer", e)
            return {}

    def _fetch_loop_store(store_key):
        """Full direct→Instacart decision for one non-direct store. Returns
        {'prices': dict, 'label': str, 'costco_meta': dict}; no shared mutation."""
        if is_trader_joes_store(store_key):
            try:
                _, tj_prices = trader_joes_pricing.price_all_tj(to_buy_quantities)
                return {"prices": tj_prices or {}, "label": "TJ"}
            except Exception as e:
                _store_failed("Trader Joe's", e)
                return {"prices": {}, "label": "TJ"}

        # Target: try direct RedSky pricing first; on failure fall through to
        # the generic Instacart "target" slug below (zero-regression fallback).
        if is_target_store(store_key):
            tg_lat, tg_lon = STORE_LOCATIONS.get(store_key, (lat, lon))
            try:
                _, _, tg_prices = target_pricing.price_all_target(to_buy_quantities, tg_lat, tg_lon)
                if tg_prices:
                    return {"prices": tg_prices, "label": "Target"}
                _store_failed("Target", f"empty result for '{store_key}' — falling back to Instacart")
            except Exception as e:
                _store_failed("Target", f"{e} — falling back to Instacart")

        # Walmart: try direct CloakBrowser pricing first; on failure fall through
        # to the generic Instacart slug below (Walmart isn't on Instacart, so this
        # simply yields no prices and the store is excluded — same as before).
        if is_walmart_store(store_key):
            try:
                _, _, wm_prices = walmart_pricing.price_all_walmart(to_buy_quantities, lat, lon)
                if wm_prices:
                    return {"prices": wm_prices, "label": "Walmart"}
                _store_failed("Walmart", f"empty result for '{store_key}' — falling back to Instacart")
            except Exception as e:
                _store_failed("Walmart", f"{e} — falling back to Instacart")

        # Australia — IGA (not on Instacart, AU isn't covered, so no fallback).
        # IGA is also a common independent-grocer banner in the US, which this
        # AU-only integration has no data for — gate on real AU coordinates so
        # a US "IGA" store doesn't get mislabeled with Australian prices.
        if is_iga_store(store_key):
            ig_lat, ig_lon = STORE_LOCATIONS.get(store_key, (lat, lon))
            if not iga_pricing.is_in_australia(ig_lat, ig_lon):
                _store_failed("IGA", f"'{store_key}' is a non-AU IGA-banner store — no pricing support yet")
                return {"prices": {}, "label": "IGA"}
            try:
                ig_store_id = iga_pricing.find_nearest_iga_store(ig_lat, ig_lon) or config.IGA_DEFAULT_STORE_ID
                _, _, iga_prices = iga_pricing.price_all_iga(
                    to_buy_quantities, store_id=ig_store_id, lat=ig_lat, lon=ig_lon,
                )
                if iga_prices:
                    return {"prices": iga_prices, "label": "IGA"}
                _store_failed("IGA", f"empty result for '{store_key}'")
            except Exception as e:
                _store_failed("IGA", e)
            return {"prices": {}, "label": "IGA"}

        # Costco: prices are near-uniform nationally, so when the local warehouse
        # isn't on Instacart Same-Day we price at the nearest covered Costco and
        # flag the line as an estimate (instead of dropping Costco entirely).
        if "costco" in store_key.lower():
            try:
                _, _, cc_prices, cc_meta = instacart_pricing.price_all_costco(to_buy_quantities, lat, lon)
                return {"prices": cc_prices or {}, "label": "IC:costco", "costco_meta": cc_meta or {}}
            except Exception as e:
                _store_failed("Costco (Instacart)", e)
            return {"prices": {}, "label": "IC:costco"}

        slug = get_instacart_slug(store_key)
        if slug:
            try:
                _, _, ic_prices = instacart_pricing.price_all_instacart(to_buy_quantities, lat, lon, slug)
                return {"prices": ic_prices or {}, "label": f"IC:{slug}"}
            except Exception as e:
                _store_failed(f"Instacart:{slug}", e)
        return {"prices": {}, "label": ""}

    # ---- Fan out: every store priced at once ----
    # Price every store concurrently, but under a hard wall-clock BUDGET so a
    # plan request always returns promptly with whatever priced — never blocking
    # on a slow browser chain (Target's warm, ALDI's mint on a small host). Any
    # chain still running at the deadline is skipped (its store excluded) and
    # left to finish in the background rather than held onto. Already-finished
    # chains are still collected regardless of order (result() on a done future
    # returns instantly), so the fast chains never get starved by a slow one.
    #
    # The fan-out runs on the SHARED bounded pool (pricing_pool), not a
    # per-request executor: a chain abandoned at the deadline keeps running, so
    # a per-request pool let those threads multiply without limit across
    # requests. Single-flight per chain means an overrunning chain is skipped
    # next time instead of stacking a second copy, and the Deadline lets chains
    # with per-ingredient loops stop early once we've stopped waiting.
    budget = float(os.environ.get("PRICING_BUDGET_SECONDS", "75"))
    deadline_obj = pricing_pool.Deadline(budget)

    def _submit(key, fn, *args):
        """Submit a chain, logging (and skipping) one already in flight."""
        fut = pricing_pool.submit_chain(key, deadline_obj, fn, *args)
        if fut is None:
            print(f"[Pricing] '{key}' is still running from an earlier request — "
                  f"skipping it for this one (store excluded).", flush=True)
        return fut

    fut_kroger = _submit("kroger", _fetch_kroger)
    fut_aldi = _submit("aldi", _fetch_aldi) if aldi_key else None
    fut_meijer = _submit("meijer", _fetch_meijer) if meijer_key else None
    loop_futs = {k: _submit(f"store:{k}", _fetch_loop_store, k) for k in loop_keys}

    def _within_budget(fut, label):
        if fut is None:
            return None
        try:
            return fut.result(timeout=max(0.0, deadline_obj.remaining()))
        except FuturesTimeout:
            # Leave it running: it will stop at its next cooperative checkpoint,
            # and single-flight stops the next request from starting another.
            _store_failed(label, f"exceeded the {budget:.0f}s pricing budget — skipping")
            return None
        except Exception as e:
            _store_failed(label, f"errored: {repr(e)[:100]}")
            return None

    # ---- Fan in: apply results sequentially (main thread, no races) ----
    kroger_prices = _within_budget(fut_kroger, "Kroger")
    if kroger_prices:
        if kroger_key:
            print(f"[Kroger] Applying real prices to store: '{kroger_key}'", flush=True)
            _apply_prices(kroger_key, kroger_prices)
        else:
            print("[Kroger] Real prices fetched but no Kroger-family store in route — discarding.", flush=True)
    elif kroger_key:
        # _fetch_kroger()/_within_budget already log their own reason on an
        # exception or a timeout; this covers the third, previously-silent
        # case — the call returned cleanly with zero products (e.g. no live
        # product endpoint for this specific store) — so kroger_key never
        # gets applied and, until now, nothing said why.
        _store_failed("Kroger", f"no products returned for '{kroger_key}'")

    if aldi_key:
        aldi_prices = _within_budget(fut_aldi, "ALDI")
        if aldi_prices:
            print(f"[ALDI] Applying real prices to store: '{aldi_key}'", flush=True)
            _apply_prices(aldi_key, aldi_prices, log_each=True)
        else:
            _store_failed("ALDI", "real pricing returned nothing")
    else:
        print("[ALDI] No ALDI store in route — skipping real pricing.", flush=True)

    if meijer_key:
        meijer_prices = _within_budget(fut_meijer, "Meijer")
        if meijer_prices:
            print(f"[Meijer] Applying real prices to store: '{meijer_key}'", flush=True)
            _apply_prices(meijer_key, meijer_prices)
        else:
            _store_failed("Meijer", "real pricing returned nothing")
    else:
        print("[Meijer] No Meijer store in route — skipping direct pricing.", flush=True)

    for store_key in loop_keys:
        res = _within_budget(loop_futs[store_key], store_key)
        if not res:
            continue
        prices = res.get("prices") or {}
        if not prices:
            continue
        label = res.get("label", "")
        cc_meta = res.get("costco_meta") or {}
        tag = " (estimate)" if cc_meta.get("is_estimate") else ""
        print(f"[{label}] Applying real prices to '{store_key}'{tag}", flush=True)
        _apply_prices(store_key, prices)
        if cc_meta.get("is_estimate"):
            costco_estimates[store_key] = {
                "distance_km": cc_meta.get("distance_km"),
                "store": cc_meta.get("store", ""),
            }

    return {
        "prefs": prefs,
        "user_loc": user_loc, "lat": lat, "lon": lon,
        "meal_plan": meal_plan, "at_home_ingredients": at_home_ingredients,
        "plan_warnings": plan_warnings, "to_buy_quantities": to_buy_quantities,
        "STORE_LOCATIONS": STORE_LOCATIONS, "STORE_ADDRESSES": STORE_ADDRESSES,
        "location_names": location_names, "durations_matrix": durations_matrix,
        "price_database": price_database, "product_details": product_details,
        "real_priced_keys": real_priced_keys, "costco_estimates": costco_estimates,
        "shopping_list": shopping_list, "MAX_TIME_SECS": MAX_TIME_SECS,
    }


def _finalize_plan(ctx: dict, user_id: Optional[str]) -> dict:
    """Drop-unpriced-stores through the response + save — the tail shared by
    the legacy single-shot /generate_plan and phase2 of the two-phase native
    flow (called after phase2 has merged device-priced Walmart into ctx, if
    it found any). ctx is exactly _build_plan_pricing's return value, plus
    whatever phase2 merged into it."""
    prefs = ctx["prefs"]
    user_loc, lat, lon = ctx["user_loc"], ctx["lat"], ctx["lon"]
    meal_plan, at_home_ingredients = ctx["meal_plan"], ctx["at_home_ingredients"]
    plan_warnings, to_buy_quantities = ctx["plan_warnings"], ctx["to_buy_quantities"]
    STORE_LOCATIONS, STORE_ADDRESSES = ctx["STORE_LOCATIONS"], ctx["STORE_ADDRESSES"]
    location_names, durations_matrix = ctx["location_names"], ctx["durations_matrix"]
    price_database, product_details = ctx["price_database"], ctx["product_details"]
    real_priced_keys, costco_estimates = ctx["real_priced_keys"], ctx["costco_estimates"]
    shopping_list, MAX_TIME_SECS = ctx["shopping_list"], ctx["MAX_TIME_SECS"]

    # Drop any store that real pricing couldn't cover — no synthetic fallback.
    unpriced = [k for k in list(price_database.keys()) if k not in real_priced_keys]
    for k in unpriced:
        _store_failed(k, "no real prices — excluding from optimization")
        del price_database[k]

    if not price_database:
        raise HTTPException(status_code=503, detail="No stores with real pricing found in your area.")

    # Filter location_names and durations_matrix to only the priced stores.
    priced_set = set(price_database.keys())
    keep_indices = [i for i, name in enumerate(location_names) if name == "Start" or name in priced_set]
    location_names = [location_names[i] for i in keep_indices]
    durations_matrix = [[durations_matrix[r][c] for c in keep_indices] for r in keep_indices]

    # Step 7b: Overlay coupon prices on top of scraped prices.
    # Coupon prices replace scraped prices when matched. The entire stage is
    # best-effort and wrapped: by this point we have a priceable basket, and no
    # coupon problem (Flipp down, Supabase down, reverse-geocode down) is worth
    # turning that into a 500 for the user.
    coupon_sources: dict[str, dict[str, str]] = {}
    try:
        postal = instacart_pricing._get_postal(lat, lon)
    except Exception as e:
        print(f"[Coupon] Postal lookup failed ({repr(e)[:80]}) — skipping coupons.", flush=True)
        postal = ""
    if postal:
        try:
            from coupon_scraper import fetch_and_store
            fetch_and_store(postal)
        except Exception as e:
            print(f"[Coupon] Fetch/store failed ({e}), using existing data.", flush=True)
        for sk in list(price_database.keys()):
            sources = _overlay_coupon_prices(sk, price_database, postal, to_buy_quantities)
            if sources:
                coupon_sources[sk] = sources

    # Pass the time budget explicitly. It used to be published to
    # config.MAX_TIME_SECONDS (a module global) immediately before this call —
    # with FastAPI running sync endpoints on a threadpool, two concurrent
    # requests raced and one user's shopping-time limit could be applied to the
    # other's optimization.
    optimal_route, item_cost, total_time_seconds, item_assignments, cheapest_single_store_cost, cheapest_single_store_name = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list,
        max_time_seconds=MAX_TIME_SECS,
    )
    
    # Debug: print full item assignments so we can spot duplicates across stores
    print("[Optimizer] Item assignments per store:", flush=True)
    for s_key, s_items in item_assignments.items():
        print(f"  {s_key}: {[i['name'] for i in s_items]}", flush=True)

    formatted_shopping_list = []
    if optimal_route:
        for store_raw in optimal_route:
            store = store_raw.strip()
            if store == "Start": continue # Skip the start location in the list
            items = item_assignments.get(store_raw, [])
            store_items = []
            for item_data in items:
                item_name = item_data["name"]
                item_qty = item_data["qty"]
                lookup_key = item_name.lower().strip()
                store_prices = price_database.get(store, {})
                unit_price = store_prices.get(lookup_key, 0.0)
                
                # Debug logging to catch mismatches
                if unit_price == 0.0:
                    available_keys = list(store_prices.keys())
                    print(f"❌ PRICE MISS: Store '{store}' | Key '{lookup_key}' not found.")
                    print(f"   Available keys in this store: {available_keys[:20]}")
                
                total_item_price = unit_price * item_qty
                item_entry = {"name": item_name, "qty": item_qty, "price": total_item_price}
                detail = product_details.get((store, lookup_key))
                if detail:
                    item_entry["product_name"] = detail["product_name"]
                    item_entry["size_str"] = detail["size_str"]
                    item_entry["units_to_buy"] = detail["units_to_buy"]

                store_items.append(item_entry)
            
            store_entry = {
                "store": store,
                "address": STORE_ADDRESSES.get(store, ""),
                "coordinates": {"lat": STORE_LOCATIONS[store][0], "lng": STORE_LOCATIONS[store][1]},
                "items": store_items
            }
            # Costco priced via the nearest-covered-warehouse proxy: flag as an
            # estimate so the UI can label it (Costco pricing is ~national).
            est = costco_estimates.get(store)
            if est:
                km = est.get("distance_km")
                store_entry["estimated"] = True
                store_entry["pricing_note"] = (
                    "Estimated — local Costco isn't on Instacart, so prices are from the "
                    f"nearest covered Costco (~{int(km)} km away). Costco prices are ~national."
                    if km else "Estimated from the nearest covered Costco."
                )
            formatted_shopping_list.append(store_entry)

    # Step 8: Calculate prices for meal ingredients
    # Create a lookup for unit prices based on optimal assignments
    item_unit_prices = {}
    for store_name, items in item_assignments.items():
        if store_name == "Start": continue
        store_prices = price_database.get(store_name, {})
        for itm in items:
            l_key = itm["name"].lower().strip()
            item_unit_prices[l_key] = store_prices.get(l_key, 0.0)

    # Attach prices to meal plan ingredients
    for meal in meal_plan:
        for ing in meal.get('ingredients', []):
            l_key = ing['name'].lower().strip()
            u_price = item_unit_prices.get(l_key, 0.0)
            ing['price'] = u_price * ing['qty']

    total_cost = item_cost if item_cost != float('inf') else 0

    res = {
        "meal_plan": meal_plan,
        "shopping_list": formatted_shopping_list,
        "at_home_ingredients": at_home_ingredients,
        "total_cost": total_cost,
        "cheapest_single_store_cost": cheapest_single_store_cost if cheapest_single_store_cost != float('inf') else 0,
        "cheapest_single_store_name": cheapest_single_store_name,
        "total_time_minutes": total_time_seconds / 60 if total_time_seconds else 0,
        "route": optimal_route if optimal_route else [],
        "user_location": {"lat": user_loc[0], "lng": user_loc[1]},
        # Every constraint we could not fully honour. The UI must show these —
        # they are the difference between "your nut-free plan" and "a plan we
        # couldn't verify is nut-free".
        "warnings": plan_warnings,
        # The budget field was collected by the UI and never used for anything.
        # It can't gate meal SELECTION (prices aren't known until after the plan
        # exists), but the plan can at least be reported against it.
        "budget": prefs.budget,
        "over_budget": bool(prefs.budget and total_cost > prefs.budget),
    }

    # Persist to Supabase if user is authenticated
    _save_results(
        user_id=user_id, prefs=prefs, meal_plan=meal_plan,
        shopping_list=formatted_shopping_list, route=optimal_route or [],
        total_cost=res["total_cost"],
        cheapest_store_name=cheapest_single_store_name or "",
        cheapest_store_cost=cheapest_single_store_cost if cheapest_single_store_cost != float('inf') else 0,
        total_time_minutes=res["total_time_minutes"],
    )

    print(f"DEBUG SERVER: Sending benchmark {cheapest_single_store_name} to frontend", flush=True)
    return res


@router.post("/generate_plan", dependencies=[Depends(rate_limit("plan"))])
def generate_plan(request: PlanRequest, user_id: Optional[str] = Depends(get_current_user)):
    """Legacy single-shot path (web, and any native client that skips the
    two-phase flow): prices every store including Walmart itself, same as
    always. See /generate_plan/phase1 + phase2 for the native path that lets
    the device price Walmart instead."""
    print(f"\nRECEIVED PLAN REQUEST (Server v{SERVER_VERSION})", flush=True)
    ctx = _build_plan_pricing(request.preferences, defer_walmart=False)
    return _finalize_plan(ctx, user_id)


# ---------------------------------------------------------------------------
# Two-phase native flow (2026-09-20): phase1 prices everything except
# Walmart and hands the app the ingredient list; the app light-scans its
# cached Walmart cookies from the DEVICE itself (see
# frontend/services/walmartDirect.ts), prices Walmart with whichever one
# works, and phase2 merges that in before running the SAME optimizer as the
# legacy path — Walmart genuinely competes for a spot in the route, not
# just listed alongside it. In-memory only: fine for Render's single
# instance, and a lost context (restart, TTL) just means phase2 404s and
# the app falls back to the legacy endpoint.
# ---------------------------------------------------------------------------
_PLAN_PHASE_TTL = float(os.environ.get("PLAN_PHASE_TTL_SECONDS", "600"))
_plan_phase_lock = threading.Lock()
_plan_phase_cache: dict[str, tuple[float, dict, Optional[str]]] = {}


def _cache_plan_context(ctx: dict, user_id: Optional[str]) -> str:
    token = uuid.uuid4().hex
    expires_at = time.time() + _PLAN_PHASE_TTL
    with _plan_phase_lock:
        # Lazy-prune expired entries on every insert — no background thread
        # needed for what's at most a handful of concurrent in-flight plans.
        for k in [k for k, (exp, _, _) in _plan_phase_cache.items() if exp < time.time()]:
            del _plan_phase_cache[k]
        _plan_phase_cache[token] = (expires_at, ctx, user_id)
    return token


def _pop_plan_context(token: str) -> tuple[Optional[dict], Optional[str]]:
    with _plan_phase_lock:
        entry = _plan_phase_cache.pop(token, None)
    if not entry:
        return None, None
    expires_at, ctx, user_id = entry
    if expires_at < time.time():
        return None, None
    return ctx, user_id


@router.post("/generate_plan/phase1", dependencies=[Depends(rate_limit("plan"))])
def generate_plan_phase1(request: PlanRequest, user_id: Optional[str] = Depends(get_current_user)):
    """Meal plan + every store priced except Walmart. Returns a token
    (redeem with phase2 within _PLAN_PHASE_TTL) and the ingredient names the
    app needs to price Walmart for on the device."""
    print(f"\nRECEIVED PLAN REQUEST phase1 (Server v{SERVER_VERSION})", flush=True)
    ctx = _build_plan_pricing(request.preferences, defer_walmart=True)
    token = _cache_plan_context(ctx, user_id)
    return {"token": token, "ingredients": list(ctx["to_buy_quantities"].keys())}


@router.post("/generate_plan/phase2", dependencies=[Depends(rate_limit("plan"))])
def generate_plan_phase2(request: WalmartPhase2Request):
    """Merges device-priced Walmart items into the phase1 context (if any —
    an empty walmart_prices just means Walmart gets excluded, same as the
    legacy path when server-side pricing fails) and runs the same
    finalize step (drop-unpriced, coupon, optimizer, response, save) the
    legacy endpoint uses."""
    ctx, user_id = _pop_plan_context(request.token)
    if ctx is None:
        raise HTTPException(status_code=410, detail="This plan's token expired or was already used — start over.")

    price_database = ctx["price_database"]
    product_details = ctx["product_details"]
    real_priced_keys = ctx["real_priced_keys"]
    to_buy_quantities = ctx["to_buy_quantities"]
    walmart_keys = [k for k in price_database if is_walmart_store(k)]

    for store_key in walmart_keys:
        matched = 0
        for ing_name, entry in request.walmart_prices.items():
            if ing_name not in to_buy_quantities:
                continue  # not part of this plan — ignore anything unexpected
            key = ing_name.lower().strip()
            price_database[store_key][key] = entry.unit_price
            if entry.description:
                product_details[(store_key, key)] = {
                    "product_name": f"{entry.brand} {entry.description}".strip(),
                    "size_str": entry.size_str,
                    # Device pricing doesn't run the buy-N-units optimization
                    # (walmart_pricing.find_best_purchase) — one unit is the
                    # honest default rather than implying a real computed count.
                    "units_to_buy": 1,
                }
            matched += 1
        if matched:
            real_priced_keys.add(store_key)
            print(f"[Walmart] Device-priced {matched}/{len(to_buy_quantities)} ingredients "
                  f"via {request.session_source or 'device'} — applying to '{store_key}'.", flush=True)
        else:
            _store_failed(store_key, "device pricing returned nothing — excluding from optimization")

    return _finalize_plan(ctx, user_id)


@router.post("/price_list", dependencies=[Depends(rate_limit("plan"))])
def price_list(request: PriceListRequest, user_id: Optional[str] = Depends(get_current_user)):
    print(f"\nRECEIVED PRICE LIST REQUEST (Server v{SERVER_VERSION})", flush=True)
    prefs = request

    # 1. Geocode Address (Google first — same source as autocomplete — then OSM)
    user_loc = _geocode_address(prefs.address)
    if not user_loc:
        print(f"[Geocode] Could not resolve address: {prefs.address!r}", flush=True)
        raise HTTPException(status_code=400, detail="Address not found")
    print(f"Using location for: {prefs.address}")

    # 2. Build to_buy_quantities from the items list
    to_buy_quantities = {}
    for item in prefs.items:
        to_buy_quantities[item.name] = {"qty": item.qty, "unit": item.unit}

    # 3. Find Stores & Optimize (same logic as generate_plan)
    sh_hours = prefs.shopping_time_hours
    if sh_hours > 12:
        sh_hours = sh_hours / 60.0
    MAX_TIME_SECS = sh_hours * 3600
    ONE_WAY_TIME_SECONDS = int(MAX_TIME_SECS / 4)
    isochrone_geometry = geo_utils.get_travel_isochrone(user_loc, ONE_WAY_TIME_SECONDS)
    if not isochrone_geometry:
        print("[Server] ORS isochrone failed — using 15 km bounding-box fallback.", flush=True)
        lat0, lon0 = user_loc
        D = 0.135
        isochrone_geometry = {
            "type": "Polygon",
            "coordinates": [[
                [lon0 - D, lat0 - D], [lon0 + D, lat0 - D],
                [lon0 + D, lat0 + D], [lon0 - D, lat0 + D],
                [lon0 - D, lat0 - D],
            ]]
        }

    STORE_LOCATIONS, STORE_ADDRESSES = geo_utils.find_eligible_stores_google(isochrone_geometry, user_loc)
    if not prefs.has_costco_card:
        STORE_LOCATIONS = {k: v for k, v in STORE_LOCATIONS.items() if "costco" not in k.lower()}
        STORE_ADDRESSES = {k: STORE_ADDRESSES[k] for k in STORE_LOCATIONS if k in STORE_ADDRESSES}

    STORE_LOCATIONS_RAW, STORE_ADDRESSES_RAW = geo_utils.filter_unique_closest_chains(STORE_LOCATIONS, STORE_ADDRESSES, user_loc)
    STORE_LOCATIONS = {k.strip(): v for k, v in STORE_LOCATIONS_RAW.items()}
    STORE_ADDRESSES = {k.strip(): v for k, v in STORE_ADDRESSES_RAW.items()}

    if len(STORE_LOCATIONS) > config.MAX_STORES_TO_USE:
        distances = [( (lat - user_loc[0])**2 + (lon - user_loc[1])**2, name, (lat, lon) ) for name, (lat, lon) in STORE_LOCATIONS.items()]
        distances.sort(key=lambda x: x[0])
        STORE_LOCATIONS = {name: loc for _, name, loc in distances[:config.MAX_STORES_TO_USE]}
        STORE_ADDRESSES = {name: STORE_ADDRESSES[name] for name in STORE_LOCATIONS}

    all_coords = [user_loc] + list(STORE_LOCATIONS.values())
    location_names = ["Start"] + list(STORE_LOCATIONS.keys())
    matrix_response = geo_utils.get_distance_matrix(all_coords)
    durations_matrix = geo_utils.process_matrix_result(matrix_response)

    # 4. Price each store (same coupon-first pipeline)
    lat, lon = user_loc
    price_database: dict = {k.strip(): {} for k in STORE_LOCATIONS.keys()}
    real_priced_keys: set = set()
    product_details: dict = {}
    costco_estimates: dict = {}

    shopping_list = [
        {"name": name, "qty": float(data.get("qty", 1) or 1)}
        for name, data in to_buy_quantities.items()
    ]

    # --- Kroger ---
    kroger_key = next((k for k in price_database if is_kroger_banner(k)), None)
    if kroger_key:
        try:
            _, _, kroger_prices = asyncio.run(kroger_async.price_all_async(to_buy_quantities, lat, lon))
        except Exception as e:
            _store_failed("Kroger", e)
            kroger_prices = {}
        if kroger_prices:
            for ing_name, result in kroger_prices.items():
                total_cost = result.get("total_cost", 0.0)
                qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                key = ing_name.lower().strip()
                price_database[kroger_key][key] = total_cost / qty
                if result.get("description"):
                    product_details[(kroger_key, key)] = {
                        "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                        "size_str": result.get("size_str", ""),
                        "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                    }
            real_priced_keys.add(kroger_key)
        else:
            _store_failed("Kroger", f"no products returned for '{kroger_key}'")

    # --- ALDI, Meijer, Walmart, Target, Trader Joe's, Costco, Instacart fallback ---
    # (same blocks as generate_plan but without the King Soopers King Soopers fallback)
    for store_key in list(price_database.keys()):
        if store_key in real_priced_keys:
            continue
        if is_kroger_banner(store_key):
            continue
        if is_aldi_store(store_key):
            try:
                _, _, aldi_prices = price_all_aldi(to_buy_quantities, lat, lon)
            except Exception as e:
                _store_failed("ALDI", e)
                aldi_prices = {}
            if aldi_prices:
                for ing_name, result in aldi_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty if qty else total_cost
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_meijer_store(store_key):
            try:
                _, _, meijer_prices = meijer_pricing.price_all_meijer(to_buy_quantities, lat, lon)
            except Exception as e:
                _store_failed("Meijer", e)
                meijer_prices = {}
            if meijer_prices:
                for ing_name, result in meijer_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_trader_joes_store(store_key):
            try:
                _, tj_prices = trader_joes_pricing.price_all_tj(to_buy_quantities)
            except Exception as e:
                _store_failed("Trader Joe's", e)
                tj_prices = {}
            if tj_prices:
                for ing_name, result in tj_prices.items():
                    total_cost = result.get("total_cost", 0.0)
                    qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                    key = ing_name.lower().strip()
                    price_database[store_key][key] = total_cost / qty
                    if result.get("description"):
                        product_details[(store_key, key)] = {
                            "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                            "size_str": result.get("size_str", ""),
                            "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                        }
                real_priced_keys.add(store_key)
            continue
        if is_target_store(store_key):
            try:
                tg_lat, tg_lon = STORE_LOCATIONS.get(store_key, (lat, lon))
                _, _, tg_prices = target_pricing.price_all_target(to_buy_quantities, tg_lat, tg_lon)
                if tg_prices:
                    for ing_name, result in tg_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
            except Exception as e:
                _store_failed("Target", f"{e} — falling back to Instacart")
        if is_walmart_store(store_key):
            try:
                wm_lat, wm_lon = STORE_LOCATIONS.get(store_key, (lat, lon))
                _, _, wm_prices = walmart_pricing.price_all_walmart(to_buy_quantities, wm_lat, wm_lon)
                if wm_prices:
                    for ing_name, result in wm_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
            except Exception as e:
                _store_failed("Walmart", f"{e} — falling back to Instacart")
        if is_iga_store(store_key) and iga_pricing.is_in_australia(lat, lon):
            try:
                ig_store_id = iga_pricing.find_nearest_iga_store(lat, lon) or config.IGA_DEFAULT_STORE_ID
                _, _, iga_prices = iga_pricing.price_all_iga(
                    to_buy_quantities, store_id=ig_store_id, lat=lat, lon=lon,
                )
                if iga_prices:
                    for ing_name, result in iga_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    continue
            except Exception as e:
                _store_failed("IGA", e)
        if "costco" in store_key.lower():
            try:
                _, _, cc_prices, cc_meta = instacart_pricing.price_all_costco(to_buy_quantities, lat, lon)
                if cc_prices:
                    for ing_name, result in cc_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
                    if cc_meta.get("is_estimate"):
                        costco_estimates[store_key] = {
                            "distance_km": cc_meta.get("distance_km"),
                            "store": cc_meta.get("store", ""),
                        }
            except Exception as e:
                _store_failed("Costco (Instacart)", e)
            continue
        slug = get_instacart_slug(store_key)
        if slug:
            try:
                _, _, ic_prices = instacart_pricing.price_all_instacart(to_buy_quantities, lat, lon, slug)
                if ic_prices:
                    for ing_name, result in ic_prices.items():
                        total_cost = result.get("total_cost", 0.0)
                        qty = float(to_buy_quantities.get(ing_name, {}).get("qty", 1) or 1)
                        key = ing_name.lower().strip()
                        price_database[store_key][key] = total_cost / qty
                        if result.get("description"):
                            product_details[(store_key, key)] = {
                                "product_name": f"{result.get('brand','')} {result['description']}".strip(),
                                "size_str": result.get("size_str", ""),
                                "units_to_buy": math.ceil(result.get("units_to_buy", 1)),
                            }
                    real_priced_keys.add(store_key)
            except Exception as e:
                _store_failed(f"Instacart:{slug}", e)

    unpriced = [k for k in list(price_database.keys()) if k not in real_priced_keys]
    for k in unpriced:
        _store_failed(k, "no real prices — excluding from optimization")
        del price_database[k]
    if not price_database:
        raise HTTPException(status_code=503, detail="No stores with real pricing found in your area.")

    priced_set = set(price_database.keys())
    keep_indices = [i for i, n in enumerate(location_names) if n == "Start" or n in priced_set]
    location_names = [location_names[i] for i in keep_indices]
    durations_matrix = [[durations_matrix[r][c] for c in keep_indices] for r in keep_indices]

    # Coupon overlay — best-effort, same as generate_plan (see the note there).
    try:
        postal = instacart_pricing._get_postal(lat, lon)
    except Exception as e:
        print(f"[Coupon] Postal lookup failed ({repr(e)[:80]}) — skipping coupons.", flush=True)
        postal = ""
    if postal:
        try:
            from coupon_scraper import fetch_and_store
            fetch_and_store(postal)
        except Exception:
            pass
        for sk in list(price_database.keys()):
            _overlay_coupon_prices(sk, price_database, postal, to_buy_quantities)

    # Pass the time budget explicitly. It used to be published to
    # config.MAX_TIME_SECONDS (a module global) immediately before this call —
    # with FastAPI running sync endpoints on a threadpool, two concurrent
    # requests raced and one user's shopping-time limit could be applied to the
    # other's optimization.
    optimal_route, item_cost, total_time_seconds, item_assignments, cheapest_single_store_cost, cheapest_single_store_name = optimizer.find_optimal_store(
        durations_matrix, price_database, location_names, shopping_list,
        max_time_seconds=MAX_TIME_SECS,
    )

    formatted_shopping_list = []
    if optimal_route:
        for store_raw in optimal_route:
            store = store_raw.strip()
            if store == "Start":
                continue
            items = item_assignments.get(store_raw, [])
            store_items = []
            for item_data in items:
                item_name = item_data["name"]
                item_qty = item_data["qty"]
                lookup_key = item_name.lower().strip()
                store_prices = price_database.get(store, {})
                unit_price = store_prices.get(lookup_key, 0.0)
                total_item_price = unit_price * item_qty
                item_entry = {"name": item_name, "qty": item_qty, "price": total_item_price}
                detail = product_details.get((store, lookup_key))
                if detail:
                    item_entry["product_name"] = detail["product_name"]
                    item_entry["size_str"] = detail["size_str"]
                    item_entry["units_to_buy"] = detail["units_to_buy"]
                store_items.append(item_entry)
            store_entry = {
                "store": store,
                "address": STORE_ADDRESSES.get(store, ""),
                "coordinates": {"lat": STORE_LOCATIONS[store][0], "lng": STORE_LOCATIONS[store][1]},
                "items": store_items,
            }
            est = costco_estimates.get(store)
            if est:
                km = est.get("distance_km")
                store_entry["estimated"] = True
                store_entry["pricing_note"] = (
                    f"Estimated — local Costco isn't on Instacart, so prices are from the "
                    f"nearest covered Costco (~{int(km)} km away). Costco prices are ~national."
                    if km else "Estimated from the nearest covered Costco."
                )
            formatted_shopping_list.append(store_entry)

    res = {
        "shopping_list": formatted_shopping_list,
        "total_cost": item_cost if item_cost != float('inf') else 0,
        "cheapest_single_store_cost": cheapest_single_store_cost if cheapest_single_store_cost != float('inf') else 0,
        "cheapest_single_store_name": cheapest_single_store_name,
        "total_time_minutes": total_time_seconds / 60 if total_time_seconds else 0,
        "route": optimal_route if optimal_route else [],
        "user_location": {"lat": user_loc[0], "lng": user_loc[1]},
    }
    return res


# ── Session cookie upload (internal — not client-facing) ────────────────────
# Lets a script running on a real residential IP (a laptop — the datacenter
# IPs on Render/GitHub Actions are what Target/Walmart's WAFs actually flag)
# mint a fresh WAF cookie and push it here. This writes to the exact same
# Supabase row target_pricing.py / walmart_pricing.py already read on every
# request via session_store.load() — see _load_remote_session() in those
# files — so nothing else needs to change for prod to pick it up.
#
# Bearer-token gated. Deliberately narrow: the token can only overwrite
# session rows for the chains below, nothing else in Supabase — unlike the
# service-role key, this is the only credential that should ever leave this
# server or reach a laptop.
_SESSION_UPLOAD_TOKEN = os.environ.get("SESSION_UPLOAD_TOKEN", "")
_UPLOADABLE_CHAINS = {"target", "walmart", "aldi", "instacart"}


class SessionUpload(BaseModel):
    cookies: Dict[str, str]
    ua: str = Field(default="", max_length=500)
    store_id: Optional[str] = Field(default=None, max_length=40)
    extra: Optional[Dict] = None


@app.post("/internal/sessions/{chain}", dependencies=[Depends(rate_limit("internal_session"))])
def upload_session(chain: str, body: SessionUpload, authorization: Optional[str] = Header(None)):
    if not _SESSION_UPLOAD_TOKEN:
        raise HTTPException(status_code=503, detail="Session upload disabled (SESSION_UPLOAD_TOKEN not set).")
    token = (authorization or "").replace("Bearer ", "").strip()
    # Constant-time compare — a timing side-channel on a short-lived cookie
    # token is a low-value target, but it costs nothing to close here too.
    if not token or not hmac.compare_digest(token, _SESSION_UPLOAD_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")
    if chain not in _UPLOADABLE_CHAINS:
        raise HTTPException(status_code=404, detail=f"Unknown chain {chain!r}.")
    if not body.cookies:
        raise HTTPException(status_code=400, detail="cookies must be non-empty.")
    import session_store
    ok = session_store.save(chain, {"cookies": body.cookies, "ua": body.ua},
                             store_id=body.store_id, extra=body.extra)
    if not ok:
        raise HTTPException(status_code=502, detail="Supabase write failed.")
    return {"ok": True, "chain": chain, "cookie_count": len(body.cookies)}


app.include_router(router)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)