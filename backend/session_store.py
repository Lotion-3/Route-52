"""
Shared store for WAF session cookies (Walmart _px3, Target Imperva, ALDI's
instacart_sid, the shared Instacart session, ...) and pre-fetched static
assets, backed by Supabase tables `chain_sessions` / `chain_assets`.

This is the bridge for the GitHub-Actions offload: a scheduled Action mints
each chain's cookie (and, for Walmart/Target, pre-fetches their static JS/CSS
bundles) on a 7GB runner via mint_sessions.py and publishes both here; the
512MB web server then calls load()/load_assets() to reuse them and replay via
curl_cffi WITHOUT launching a browser or hitting the retailer's CDN itself.
Falls back silently (returns None) if Supabase is unavailable, so nothing
here is a hard dependency — each chain warms/fetches on its own as before.

Supabase tables (run once — see schema.sql):

    create table if not exists chain_sessions (
      chain       text primary key,
      cookies     jsonb        not null,
      user_agent  text,
      store_id    text,
      extra       jsonb        default '{}'::jsonb,  -- chain-specific fields
                                                       -- (e.g. ALDI's qp/zoneId)
      updated_at  timestamptz  not null default now()
    );

    create table if not exists chain_assets (
      chain       text primary key,
      assets      jsonb        not null,  -- {url: {status, headers, body_b64}}
      updated_at  timestamptz  not null default now()
    );

    create table if not exists chain_block_events (
      id          bigserial primary key,
      chain       text         not null,
      category    text         not null,  -- 'explicit' | 'soft' | 'transport'
      detail      text         default '',
      created_at  timestamptz  not null default now()
    );
"""
from __future__ import annotations

import base64
from typing import Optional

_SESSIONS_TABLE = "chain_sessions"
_ASSETS_TABLE = "chain_assets"


def save(chain: str, session: dict, store_id: Optional[str] = None,
         extra: Optional[dict] = None) -> bool:
    """Upsert a chain's {cookies, ua, extra} session. Returns True on success."""
    try:
        from db import db
        db.client.table(_SESSIONS_TABLE).upsert({
            "chain": chain,
            "cookies": session.get("cookies") or {},
            "user_agent": session.get("ua") or session.get("user_agent") or "",
            "store_id": store_id,
            "extra": extra or {},
            "updated_at": _now_iso(),
        }, on_conflict="chain").execute()
        return True
    except Exception as e:
        print(f"[session_store] save({chain}) failed: {repr(e)[:120]}", flush=True)
        return False


def load(chain: str, max_age_seconds: int = 20 * 60) -> Optional[dict]:
    """Return {'cookies': {...}, 'ua': str, 'store_id': str|None, 'extra': dict}
    for `chain` if a row exists and is within max_age_seconds, else None.
    Never raises."""
    try:
        from db import db
        resp = db.client.table(_SESSIONS_TABLE).select("*").eq("chain", chain).limit(1).execute()
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        if _age_seconds(row.get("updated_at")) > max_age_seconds:
            return None
        return {
            "cookies": row.get("cookies") or {},
            "ua": row.get("user_agent") or "",
            "store_id": row.get("store_id"),
            "extra": row.get("extra") or {},
        }
    except Exception as e:
        print(f"[session_store] load({chain}) failed: {repr(e)[:120]}", flush=True)
        return None


def save_assets(chain: str, assets: dict) -> bool:
    """Publish a chain's pre-fetched static-asset cache ({url: {status, headers,
    body: bytes}}) to Supabase. Bodies are base64-encoded — jsonb has no native
    bytes type. Returns True on success."""
    try:
        from db import db
        encoded = {
            url: {
                "status": a.get("status"),
                "headers": a.get("headers") or {},
                "body_b64": base64.b64encode(a.get("body") or b"").decode("ascii"),
            }
            for url, a in assets.items()
        }
        db.client.table(_ASSETS_TABLE).upsert({
            "chain": chain,
            "assets": encoded,
            "updated_at": _now_iso(),
        }, on_conflict="chain").execute()
        return True
    except Exception as e:
        print(f"[session_store] save_assets({chain}) failed: {repr(e)[:120]}", flush=True)
        return False


def load_assets(chain: str, max_age_seconds: int = 6 * 3600) -> Optional[dict]:
    """Return {url: {status, headers, body: bytes}} published by mint_sessions.py,
    or None if unavailable/stale. Never raises. Never launches a browser or hits
    the retailer's CDN — this is a pure Supabase read, safe to call on every
    Render boot."""
    try:
        from db import db
        resp = db.client.table(_ASSETS_TABLE).select("*").eq("chain", chain).limit(1).execute()
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        if _age_seconds(row.get("updated_at")) > max_age_seconds:
            return None
        assets = row.get("assets") or {}
        return {
            url: {
                "status": a.get("status"),
                "headers": a.get("headers") or {},
                "body": base64.b64decode(a.get("body_b64") or ""),
            }
            for url, a in assets.items()
        }
    except Exception as e:
        print(f"[session_store] load_assets({chain}) failed: {repr(e)[:120]}", flush=True)
        return None


_BLOCK_EVENTS_TABLE = "chain_block_events"


def log_block_event(chain: str, category: str, detail: str = "") -> bool:
    """Record one block/failure event (see chain_block_events in the module
    docstring) so the actual explicit/soft/transport rate over time is
    something you can query instead of having to notice it in scrolling logs.
    One row per retry-loop round, not per item — see the callers in
    walmart_pricing.py / target_pricing.py. Never raises; best-effort, same as
    every other function in this module."""
    try:
        from db import db
        db.client.table(_BLOCK_EVENTS_TABLE).insert({
            "chain": chain,
            "category": category,
            "detail": (detail or "")[:200],
            "created_at": _now_iso(),
        }).execute()
        return True
    except Exception as e:
        print(f"[session_store] log_block_event({chain}) failed: {repr(e)[:120]}", flush=True)
        return False


# ---------------------------------------------------------------------------

def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _age_seconds(iso_ts: Optional[str]) -> float:
    if not iso_ts:
        return float("inf")
    try:
        import datetime
        ts = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
    except Exception:
        return float("inf")
