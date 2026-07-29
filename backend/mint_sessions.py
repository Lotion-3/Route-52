"""
GitHub-Actions entrypoint: mint every browser-dependent chain's WAF/session
cookie on a beefy runner (7GB RAM, where a real browser fits comfortably) and
publish it to Supabase via session_store, so the 512MB web server can replay
via curl_cffi (or a plain requests.Session) without ever launching a browser
of its own. Also pre-fetches Walmart/Target's static JS/CSS bundles here and
publishes those too, for the same reason — that's a handful of live CDN
requests at Render boot that has no business running on the box that's
already tight on memory.

Runs on a cron (see .github/workflows/mint-sessions.yml). Each chain is minted
independently — one failing (e.g. WAF block) doesn't stop the others.

A chain is skipped if its already-published Supabase session is still fresh
(younger than half that chain's TTL) — re-minting a cookie that's nowhere
near expiry just burns Actions minutes on a browser bootstrap for no reason.
ALDI's session lasts ~30 days, so in practice it's minted once and then
skipped on every run until it's actually close to expiring.

Env expected (set as GitHub Actions secrets):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (to write chain_sessions/chain_assets)
    CLOAK_PROXY                                (optional: route mint via proxy)
    MINT_CHAINS                                (optional: comma list; default all)

Local test:  python mint_sessions.py
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

# config.py hard-exits if ORS_API_KEY is unset, but this job doesn't need it —
# provide a harmless placeholder so importing the chain modules doesn't abort.
os.environ.setdefault("ORS_API_KEY", "not-needed-for-minting")
# Plenty of RAM on the runner: no need to serialize/limit browsers.
os.environ.setdefault("LOW_MEMORY_MODE", "0")

import session_store  # noqa: E402


def _mint_walmart() -> tuple[dict, Optional[str], dict]:
    import walmart_pricing
    session = walmart_pricing._warm_http_session()
    if not session or not session.get("cookies"):
        raise RuntimeError("warm returned no cookies")
    return session, None, {}


def _mint_target() -> tuple[dict, Optional[str], dict]:
    import target_pricing
    session = target_pricing._warm_http_session()
    if not session or not session.get("cookies"):
        raise RuntimeError("warm returned no cookies")
    return session, None, {}


def _mint_aldi() -> tuple[dict, Optional[str], dict]:
    from aldi import aldi_pricing
    cookies, qp, zone_id, shop_id = aldi_pricing._bootstrap()
    if "__Host-instacart_sid" not in cookies:
        raise RuntimeError("bootstrap returned no instacart_sid")
    return {"cookies": cookies}, (shop_id or None), {"qp": qp, "zone_id": zone_id}


def _mint_instacart() -> tuple[dict, Optional[str], dict]:
    import instacart_pricing
    cookies, qp, zone_id = instacart_pricing._bootstrap()
    if not cookies:
        raise RuntimeError("bootstrap returned no cookies")
    return {"cookies": cookies}, None, {"qp": qp, "zone_id": zone_id}


# chain_key -> (minter, session TTL seconds). TTL mirrors the value the chain's
# own module uses to trust a cached cookie, so "fresh" here means the same
# thing it means to the server reading it back.
_CHAINS: dict[str, tuple[callable, int]] = {
    "walmart":    (_mint_walmart, 60 * 60),
    "target":     (_mint_target, 60 * 60),
    "aldi":       (_mint_aldi, 30 * 24 * 3600),
    "instacart":  (_mint_instacart, 2 * 3600),
}

# Chains whose static JS/CSS bundles are also worth pre-fetching (module must
# expose _pre_seed_asset_cache() + _static_asset_cache, see walmart_pricing.py
# / target_pricing.py). Kept separate from _CHAINS since ALDI/Instacart don't
# have an equivalent bundle worth caching this way.
_ASSET_CHAINS = ("walmart", "target")


def _is_fresh(chain: str, ttl: int) -> bool:
    """True if Supabase already has a session for `chain` that's younger than
    half its TTL — close enough to fresh that re-minting now is wasted work."""
    return session_store.load(chain, max_age_seconds=ttl // 2) is not None


def _mint_session(chain: str, minter, ttl: int, ok: list, skipped: list, failed: list) -> None:
    if _is_fresh(chain, ttl):
        skipped.append(chain)
        print(f"[mint] {chain}: still fresh, skipping", flush=True)
        return
    t0 = time.time()
    try:
        session, store_id, extra = minter()
        if session_store.save(chain, session, store_id=store_id, extra=extra):
            ok.append(chain)
            print(f"[mint] {chain}: minted + published ({time.time()-t0:.0f}s, "
                  f"{len(session['cookies'])} cookies)", flush=True)
        else:
            failed.append(chain)
            print(f"[mint] {chain}: minted but Supabase save failed", flush=True)
    except Exception as e:
        failed.append(chain)
        print(f"[mint] {chain}: FAILED ({repr(e)[:120]})", flush=True)


def _mint_assets(chain: str, ok: list, failed: list) -> None:
    """Pre-fetch `chain`'s static JS/CSS bundle here (not on Render — see the
    module docstrings) and publish it to Supabase."""
    module_name = f"{chain}_pricing"
    t0 = time.time()
    try:
        module = __import__(module_name)
        module._pre_seed_asset_cache()
        cache = module._static_asset_cache
        if not cache:
            raise RuntimeError("pre-seed produced no assets")
        if session_store.save_assets(chain, cache):
            ok.append(chain)
            print(f"[mint] {chain} assets: published {len(cache)} files "
                  f"({time.time()-t0:.0f}s)", flush=True)
        else:
            failed.append(chain)
            print(f"[mint] {chain} assets: pre-seeded but Supabase save failed", flush=True)
    except Exception as e:
        failed.append(chain)
        print(f"[mint] {chain} assets: FAILED ({repr(e)[:120]})", flush=True)


def main() -> int:
    wanted = os.environ.get("MINT_CHAINS")
    chains = ([c.strip() for c in wanted.split(",") if c.strip()]
              if wanted else list(_CHAINS))

    ok: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for chain in chains:
        spec = _CHAINS.get(chain)
        if not spec:
            print(f"[mint] unknown chain '{chain}', skipping", flush=True)
            continue
        minter, ttl = spec
        _mint_session(chain, minter, ttl, ok, skipped, failed)

    for chain in _ASSET_CHAINS:
        if chain in chains:
            _mint_assets(chain, ok, failed)

    print(f"\n[mint] done — ok={ok} skipped(fresh)={skipped} failed={failed}", flush=True)
    # Exit 0 if anything is ok OR was skipped as already-fresh (still a healthy
    # state); non-zero only if every chain we attempted actually failed.
    return 0 if (ok or skipped) else 1


if __name__ == "__main__":
    sys.exit(main())
