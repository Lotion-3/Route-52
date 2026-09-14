"""Mint N fresh sessions for every WAF-fronted chain, verify each live, and
APPEND every survivor to the never-pruned Supabase pool (chain_session_pool
— see session_store.save_to_pool()/load_pool()).

This is the ongoing-archive tool: unlike mint_and_upload_session.py (which
overwrites the single "current" session per chain), every verified cookie
minted here is kept forever, never overwritten or deleted. Run this
periodically (daily/weekly, by hand or via Windows Task Scheduler) and the
pool only grows — Target/Walmart/ALDI/Instacart's runtime code already tries
pool entries newest-first, advancing past whichever ones eventually die
without ever losing the record. One especially long-lived cookie (Walmart,
observed to survive 41 days) is exactly the kind of entry this is for: it
costs nothing to keep it in the pool long after most others have died.

One-time setup: run the migration in supabase-pool-migration.sql (or the SQL
in this script's own docstring below) against your Supabase project before
the first run — chain_session_pool doesn't exist until you create it.

    CREATE TABLE IF NOT EXISTS chain_session_pool (
        id          BIGSERIAL PRIMARY KEY,
        chain       TEXT NOT NULL,
        cookies     JSONB NOT NULL,
        user_agent  TEXT DEFAULT '',
        store_id    TEXT,
        extra       JSONB DEFAULT '{}'::jsonb,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_chain_session_pool_chain_time
        ON chain_session_pool(chain, created_at DESC);

Usage (from backend/, Anaconda python, CLOAK_PROXY unset so the mint uses
this machine's real residential IP — see the no-proxy-without-permission
project note if you're an agent running this on the user's behalf: same
"ask before running" rule as mint_and_upload_session.py, since this mints
real WAF sessions and writes to production Supabase):

    python mint_pool_refresh.py                     # 5 of each chain (default)
    python mint_pool_refresh.py --count 3            # 3 of each chain
    python mint_pool_refresh.py --chain walmart target   # only these chains
    python mint_pool_refresh.py --count 10 --chain walmart   # 10 Walmart only

Target/Walmart mints launch a real CloakBrowser Chromium each (slow, ~10-60s
apiece); ALDI/Instacart are usually faster. Expect several minutes for the
default (5 x 4 chains).
"""
from __future__ import annotations

import argparse
import time

import config  # loads config.env before anything else
import session_store


def _mint_target(n: int) -> int:
    import target_pricing
    survivors = 0
    for i in range(n):
        print(f"[target {i + 1}/{n}] warming ...", flush=True)
        try:
            s = target_pricing._warm_http_session()  # raises _ImpervaBlocked on a weak warm;
        except Exception as e:                        # already RedSky-replay-verified if it returns.
            print(f"  FAILED: {repr(e)[:150]}", flush=True)
            continue
        ok = session_store.save_to_pool("target", {"cookies": s["cookies"], "ua": s["ua"]})
        print(f"  OK — {len(s['cookies'])} cookies, appended to pool: {ok}", flush=True)
        survivors += 1
        time.sleep(3)
    return survivors


def _mint_walmart(n: int) -> int:
    import walmart_pricing
    survivors = 0
    for i in range(n):
        print(f"[walmart {i + 1}/{n}] warming + live-verifying ...", flush=True)
        try:
            s = walmart_pricing._warm_http_session()
            # A successful warm doesn't guarantee a successful replay (empirically
            # ~1/3-2/3 don't survive) — verify live before trusting it, same
            # standard as every other mint tool in this repo.
            _, _, prices = walmart_pricing.price_all_walmart(
                {"Large Eggs": {"qty": 12, "unit": "whole"}}, 39.97, -86.13)
            if not prices:
                print("  minted but replay produced no prices — treating as dead.", flush=True)
                continue
        except Exception as e:
            print(f"  FAILED: {repr(e)[:150]}", flush=True)
            continue
        ok = session_store.save_to_pool("walmart", {"cookies": s["cookies"], "ua": s["ua"]})
        print(f"  OK — {len(s['cookies'])} cookies, appended to pool: {ok}", flush=True)
        survivors += 1
        time.sleep(3)
    return survivors


def _mint_aldi(n: int) -> int:
    from aldi import aldi_pricing
    survivors = 0
    for i in range(n):
        print(f"[aldi {i + 1}/{n}] bootstrapping + live-verifying ...", flush=True)
        try:
            cookies, qp, zone_id, shop_id = aldi_pricing._bootstrap()
            if not cookies.get("__Host-instacart_sid"):
                print("  no SID minted — skipping.", flush=True)
                continue
            _, _, prices = aldi_pricing.price_all_aldi(
                {"Large Eggs": {"qty": 12, "unit": "whole"}}, 39.97, -86.13)
            if not prices:
                print("  minted but live check produced no prices — treating as dead.", flush=True)
                continue
        except Exception as e:
            print(f"  FAILED: {repr(e)[:150]}", flush=True)
            continue
        ok = session_store.save_to_pool("aldi", {"cookies": cookies, "ua": ""},
                                         store_id=str(shop_id), extra={"qp": qp, "zone_id": zone_id})
        print(f"  OK — {len(cookies)} cookies, appended to pool: {ok}", flush=True)
        survivors += 1
        time.sleep(2)
    return survivors


def _mint_instacart(n: int) -> int:
    import instacart_pricing as ic
    survivors = 0
    for i in range(n):
        print(f"[instacart {i + 1}/{n}] bootstrapping + live-verifying ...", flush=True)
        try:
            cookies, qp, zone_id = ic._bootstrap("publix")
            _, _, prices = ic.price_all_instacart(
                {"Large Eggs": {"qty": 12, "unit": "whole"}}, 25.76, -80.19, "publix")
            if not prices:
                print("  minted but live check produced no prices — treating as dead.", flush=True)
                continue
        except Exception as e:
            print(f"  FAILED: {repr(e)[:150]}", flush=True)
            continue
        ok = session_store.save_to_pool("instacart", {"cookies": cookies, "ua": ""},
                                         extra={"qp": qp, "zone_id": zone_id})
        print(f"  OK — {len(cookies)} cookies, appended to pool: {ok}", flush=True)
        survivors += 1
        time.sleep(2)
    return survivors


_MINTERS = {
    "target": _mint_target,
    "walmart": _mint_walmart,
    "aldi": _mint_aldi,
    "instacart": _mint_instacart,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=5, help="how many to mint per chain (default 5)")
    ap.add_argument("--chain", nargs="*", choices=list(_MINTERS),
                     help="only these chains (default: all four)")
    args = ap.parse_args()
    chains = args.chain or list(_MINTERS)

    results: dict[str, int] = {}
    for chain in chains:
        print(f"\n=== {chain.upper()} ===", flush=True)
        results[chain] = _MINTERS[chain](args.count)

    print("\n" + "=" * 50)
    print("SUMMARY (survivors appended to the pool / attempted):")
    for chain in chains:
        print(f"  {chain:10} {results[chain]}/{args.count}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
