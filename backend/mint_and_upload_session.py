"""
Run this ON YOUR LAPTOP (a real residential IP) to mint a fresh WAF session
cookie and push it straight to production over the internal endpoint added in
server.py (`POST /internal/sessions/{chain}`).

Why local: Target/Walmart's WAFs (Imperva/PerimeterX) fingerprint datacenter
IPs — Render, GitHub Actions runners — far more aggressively than a home
connection; that's the whole reason CLOAK_PROXY/residential proxies exist for
those chains. Minting here and uploading just the *cookie* means prod stays
usable without this laptop ever holding the Supabase service-role key or any
proxy credential — see server.py's upload_session() docstring for why that
split matters.

One-time setup:
    1. Create backend/.env.local (gitignored — NOT config.env) with:
           PROD_BASE_URL=https://route52.onrender.com
           SESSION_UPLOAD_TOKEN=<same random value set as Render's SESSION_UPLOAD_TOKEN env var>
       Generate the token with: python -c "import secrets; print(secrets.token_urlsafe(32))"

Usage:
    python mint_and_upload_session.py                        # mints+uploads "target"
    python mint_and_upload_session.py walmart
    python mint_and_upload_session.py target walmart aldi instacart

Schedule this daily (Windows Task Scheduler) so the session never goes stale
the way the checked-in saved_target_cookies.json pool did.

Notes for Claude (or anyone else) running this on the user's behalf:
  * Ask before running it, same as any other action that touches production —
    a run here is a live write to the prod Supabase session row (immediately
    live for real traffic) plus a real request against Target/Walmart's WAF
    from the user's own IP. Don't fire it off proactively just because a
    cookie looks stale; confirm first.
  * Run from backend/, with the Anaconda python (the project's venv/ is dead —
    see the python-env-anaconda memory note), e.g.:
        cd backend && python mint_and_upload_session.py target
  * If backend/.env.local doesn't exist yet, stop and ask the user for
    PROD_BASE_URL / SESSION_UPLOAD_TOKEN rather than inventing a token —
    it must match whatever's set on Render, or every upload 401s.
  * CloakBrowser actually launches a browser for target/walmart, so each of
    those takes several seconds to ~a minute, not instant — a hang isn't
    necessarily a bug.
  * A "mint FAILED" for target/walmart most often just means Imperva/
    PerimeterX blocked this particular warm attempt (see target_pricing.py's
    _ImpervaBlocked) — that's expected occasionally, not something to
    debug/patch. Re-running is the normal recovery, not a code fix.
  * Exit code is 0 only if every requested chain both minted and uploaded
    successfully; treat nonzero as "at least one chain still needs a retry,"
    and check the printed per-chain FAILED lines to see which.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force this machine's REAL egress IP for the mint. A proxy here would defeat
# the entire point of running on a residential connection instead of
# Render/GitHub Actions — cleared before importing any chain module in case
# CLOAK_PROXY/TARGET_PROXY/WALMART_PROXY happens to be set in this shell.
for _var in ("CLOAK_PROXY", "TARGET_PROXY", "WALMART_PROXY"):
    os.environ.pop(_var, None)

from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).resolve().parent / ".env.local")

PROD_BASE_URL = os.environ.get("PROD_BASE_URL", "").rstrip("/")
SESSION_UPLOAD_TOKEN = os.environ.get("SESSION_UPLOAD_TOKEN", "")


def _mint_target() -> dict:
    import target_pricing
    session = target_pricing._warm_http_session()
    return {"cookies": session["cookies"], "ua": session["ua"]}


def _mint_walmart() -> dict:
    import walmart_pricing
    session = walmart_pricing._warm_http_session()
    return {"cookies": session["cookies"], "ua": session["ua"]}


def _mint_aldi() -> dict:
    from aldi import aldi_pricing
    cookies, qp, zone_id, shop_id = aldi_pricing._bootstrap()
    return {"cookies": cookies, "store_id": shop_id, "extra": {"qp": qp, "zone_id": zone_id}}


def _mint_instacart() -> dict:
    import instacart_pricing
    cookies, qp, zone_id = instacart_pricing._bootstrap()
    return {"cookies": cookies, "extra": {"qp": qp, "zone_id": zone_id}}


_MINTERS = {
    "target": _mint_target,
    "walmart": _mint_walmart,
    "aldi": _mint_aldi,
    "instacart": _mint_instacart,
}


def upload(chain: str) -> bool:
    minter = _MINTERS.get(chain)
    if not minter:
        print(f"[{chain}] unknown chain — choices: {', '.join(_MINTERS)}", flush=True)
        return False
    print(f"[{chain}] minting on this machine's own IP...", flush=True)
    try:
        payload = minter()
    except Exception as e:
        print(f"[{chain}] mint FAILED: {repr(e)[:200]}", flush=True)
        return False
    try:
        resp = requests.post(
            f"{PROD_BASE_URL}/internal/sessions/{chain}",
            json=payload,
            headers={"Authorization": f"Bearer {SESSION_UPLOAD_TOKEN}"},
            timeout=30,
        )
    except Exception as e:
        print(f"[{chain}] upload request failed: {repr(e)[:200]}", flush=True)
        return False
    if resp.status_code == 200:
        print(f"[{chain}] uploaded ok — {resp.json()}", flush=True)
        return True
    print(f"[{chain}] upload FAILED: {resp.status_code} {resp.text[:200]}", flush=True)
    return False


def main() -> int:
    if not PROD_BASE_URL or not SESSION_UPLOAD_TOKEN:
        print("Missing PROD_BASE_URL / SESSION_UPLOAD_TOKEN — create backend/.env.local, "
              "see this file's docstring.", flush=True)
        return 1
    chains = sys.argv[1:] or ["target"]
    results = [upload(c) for c in chains]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
