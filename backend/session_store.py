"""
Shared store for WAF session cookies (Walmart _px3, Target/Coles Imperva,
Woolworths Akamai, ...), backed by the Supabase `chain_sessions` table.

This is the bridge for the GitHub-Actions offload: a scheduled Action mints
each chain's cookie on a 7GB runner (where a real browser fits) via
mint_sessions.py and calls save() here; the 512MB web server then calls
load() to reuse that cookie and replay via curl_cffi WITHOUT launching a
browser of its own. Falls back silently (returns None) if Supabase is
unavailable, so nothing here is a hard dependency — the chain just warms its
own browser as before.

Supabase table (run once in the SQL editor):

    create table if not exists chain_sessions (
      chain       text primary key,
      cookies     jsonb        not null,
      user_agent  text,
      store_id    text,
      updated_at  timestamptz  not null default now()
    );
"""
from __future__ import annotations

import time
from typing import Optional

_TABLE = "chain_sessions"


def save(chain: str, session: dict, store_id: Optional[str] = None) -> bool:
    """Upsert a chain's {cookies, ua} session. Returns True on success."""
    try:
        from db import db
        db.client.table(_TABLE).upsert({
            "chain": chain,
            "cookies": session.get("cookies") or {},
            "user_agent": session.get("ua") or session.get("user_agent") or "",
            "store_id": store_id,
            "updated_at": _now_iso(),
        }, on_conflict="chain").execute()
        return True
    except Exception as e:
        print(f"[session_store] save({chain}) failed: {repr(e)[:120]}", flush=True)
        return False


def load(chain: str, max_age_seconds: int = 20 * 60) -> Optional[dict]:
    """Return {'cookies': {...}, 'ua': str, 'store_id': str|None} for `chain`
    if a row exists and is within max_age_seconds, else None. Never raises."""
    try:
        from db import db
        resp = db.client.table(_TABLE).select("*").eq("chain", chain).limit(1).execute()
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
        }
    except Exception as e:
        print(f"[session_store] load({chain}) failed: {repr(e)[:120]}", flush=True)
        return None


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
