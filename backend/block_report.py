"""Summarize WAF block events logged to Supabase `chain_block_events`.

The classification itself already exists in production code — every
Target/Walmart/ALDI/Instacart pricer raises a categorized exception
(`_Blocked`/`_ImpervaBlocked`, see their `.category`) and logs one row per
retry-loop round via `session_store.log_block_event(chain, category, detail)`:

    "explicit"  — confirmed WAF marker (px-captcha body, 403+captchaRelativeURL,
                  or a plain 401/403 for ALDI/Instacart). Trust this.
    "soft"      — response is wrong shape but no explicit marker. Ambiguous.
    "transport" — no HTTP response at all (network/timeout). Not a WAF signal.

This script is just the missing "make it visible" half: read those rows back
and print a breakdown per chain/category, plus the most recent events, so you
can answer "why is X getting blocked" without scrolling raw server logs.

Usage (from backend/, needs working SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY):
    python block_report.py                 # last 24h, all chains
    python block_report.py --hours 168     # last 7 days
    python block_report.py --chain walmart
    python block_report.py --recent 20     # just the last 20 raw events
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import config  # noqa: F401  (loads config.env before `from db import db`)
from db import db

_TABLE = "chain_block_events"


def fetch(hours: float, chain: str | None) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q = db.client.table(_TABLE).select("*").gte("created_at", since)
    if chain:
        q = q.eq("chain", chain)
    resp = q.order("created_at", desc=True).execute()
    return resp.data or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=24.0, help="lookback window (default 24h)")
    ap.add_argument("--chain", default=None, help="filter to one chain (target/walmart/aldi/instacart)")
    ap.add_argument("--recent", type=int, default=15, help="how many raw recent events to print (0 = none)")
    args = ap.parse_args(argv)

    try:
        rows = fetch(args.hours, args.chain)
    except Exception as e:
        print(f"Could not read {_TABLE}: {e}", file=sys.stderr)
        print("(Usually means SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY aren't set/valid "
              "in this environment's config.env — or the table doesn't exist yet.)",
              file=sys.stderr)
        return 1

    print(f"chain_block_events — last {args.hours:.1f}h"
          f"{f' (chain={args.chain})' if args.chain else ''}: {len(rows)} row(s)\n")

    if not rows:
        print("No block events recorded in this window. Either nothing got blocked, "
              "or the logging pipe itself is broken (check this env's Supabase creds, "
              "and separately Render's — they're independent).")
        return 0

    # --- breakdown: chain x category ---
    tally: Counter[tuple[str, str]] = Counter()
    for r in rows:
        tally[(r["chain"], r["category"])] += 1

    chains = sorted({c for c, _ in tally})
    cats = ["explicit", "soft", "transport"]
    print(f"{'CHAIN':12} {'EXPLICIT':>9} {'SOFT':>6} {'TRANSPORT':>10} {'TOTAL':>7}")
    print("-" * 50)
    for c in chains:
        counts = [tally.get((c, cat), 0) for cat in cats]
        print(f"{c:12} {counts[0]:>9} {counts[1]:>6} {counts[2]:>10} {sum(counts):>7}")

    explicit_total = sum(v for (_, cat), v in tally.items() if cat == "explicit")
    soft_total = sum(v for (_, cat), v in tally.items() if cat == "soft")
    if explicit_total and not soft_total:
        verdict = "Confirmed WAF blocks only — real anti-bot pressure, not a code bug."
    elif soft_total and not explicit_total:
        verdict = "Only ambiguous 'soft' failures — could be a parsing/shape bug, not necessarily a WAF block. Worth a closer look."
    else:
        verdict = "Mixed signal — see the per-chain split above."
    print(f"\n{verdict}")

    if args.recent:
        print(f"\nMost recent {min(args.recent, len(rows))} event(s):")
        for r in rows[: args.recent]:
            print(f"  {r['created_at']}  {r['chain']:10} {r['category']:10} {r.get('detail', '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
