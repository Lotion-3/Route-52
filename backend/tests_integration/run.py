"""CLI for the store-integration test pipeline.

Examples:
  python -m tests_integration.run                     # smoke basket, API+Instacart cases
  python -m tests_integration.run --tag kroger        # just the Kroger banners
  python -m tests_integration.run --store Target Walmart --tag browser --basket full
  python -m tests_integration.run --tag api --repeat 3 --basket full   # reliability check
  python -m tests_integration.run --all               # everything, incl. slow browser cases
"""
from __future__ import annotations

import argparse
import sys

from .baskets import BASKETS
from .harness import report, run_case
from .registry import all_cases, select


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="basketBuddy store-integration tests")
    ap.add_argument("--store", nargs="*", help="label substrings to include (e.g. Kroger Target)")
    ap.add_argument("--tag", nargs="*", help="tags to include (api, instacart, browser, kroger, edge)")
    ap.add_argument("--basket", choices=list(BASKETS), default="smoke")
    ap.add_argument("--repeat", type=int, default=1, help="runs per market (reliability/variance)")
    ap.add_argument("--timeout", type=float, default=180.0, help="per-run wall-clock guard (s)")
    ap.add_argument("--all", action="store_true", help="include slow browser cases (Target/Walmart)")
    args = ap.parse_args(argv)

    basket = BASKETS[args.basket]
    cases = all_cases()

    if args.store or args.tag:
        cases = select(cases, labels=args.store, tags=args.tag)
    elif not args.all:
        # Default: skip the slow, flaky browser cases unless explicitly asked.
        cases = [c for c in cases if "browser" not in c.tags]

    if not cases:
        print("No cases matched.", file=sys.stderr)
        return 2

    print(f"Running {len(cases)} case(s) | basket={args.basket} ({len(basket)} items) "
          f"| repeat={args.repeat}")
    rows = []
    for c in cases:
        print(f"  -> {c.label} ...", flush=True)
        rows.append((c, run_case(c, basket, repeat=args.repeat, timeout=args.timeout)))

    tally = report(rows)
    # Non-zero exit if anything is broken/leaking/badly-priced (CI-friendly).
    bad = sum(tally.get(k, 0) for k in ("BROKEN", "LEAK", "BADPRICE"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
