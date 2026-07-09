"""Core test harness: run a StoreCase, collect metrics, print a verdict report.

A StoreCase normalizes each store's heterogeneous pricer into one signature —
`price_fn(basket, lat, lon) -> {ingredient: {"total_cost": float, ...}}` — so the
runner can treat every backend identically and score it on the same axes:

  * resolution — did it return anything for a real market?
  * coverage   — fraction of the basket that priced
  * sanity     — prices within a plausible per-line range (no $0 / no $9999)
  * latency    — wall-clock seconds
  * reliability— coverage/latency spread across `repeat` runs (the key signal
                 for flaky, protection-fronted sources)
"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, field
from typing import Callable, Optional

# price_fn(basket, lat, lon) -> {name: {"total_cost": float, ...}}
PriceFn = Callable[[dict, float, float], dict]

PRICE_FLOOR = 0.01     # a line under this is almost certainly a parse bug
PRICE_CAP = 200.0      # a single line over this is almost certainly a unit bug


@dataclass(frozen=True)
class Market:
    name: str
    lat: float
    lon: float


@dataclass
class StoreCase:
    label: str                          # e.g. "Kroger", "Instacart: Publix"
    price_fn: PriceFn
    markets: list[Market]
    tags: tuple[str, ...] = ()          # e.g. ("api",) ("instacart",) ("browser",)
    min_coverage: float = 0.5           # fraction priced to count as GOOD
    expect_empty: bool = False          # edge case: must return no prices


@dataclass
class RunResult:
    market: str
    ok: bool
    priced: int
    total: int
    bad_prices: int
    seconds: float
    error: Optional[str] = None


def _invoke(fn: PriceFn, basket: dict, lat: float, lon: float, timeout: float):
    """Run one pricer with a wall-clock guard. A timed-out browser thread may
    linger (Python can't kill it) — acceptable for a validation harness."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, basket, lat, lon).result(timeout=timeout)


def run_case(case: StoreCase, basket: dict, repeat: int = 1,
             timeout: float = 180.0) -> list[RunResult]:
    out: list[RunResult] = []
    for m in case.markets:
        for _ in range(repeat):
            t0 = time.time()
            try:
                prices = _invoke(case.price_fn, basket, m.lat, m.lon, timeout) or {}
                dt = time.time() - t0
                totals = [p.get("total_cost", 0.0) for p in prices.values()]
                bad = sum(1 for v in totals if not (PRICE_FLOOR <= v <= PRICE_CAP))
                out.append(RunResult(m.name, True, len(prices), len(basket), bad, dt))
            except FutTimeout:
                out.append(RunResult(m.name, False, 0, len(basket), 0,
                                     time.time() - t0, f"timeout>{timeout:.0f}s"))
            except Exception as e:
                out.append(RunResult(m.name, False, 0, len(basket), 0,
                                     time.time() - t0, repr(e)[:90]))
    return out


def verdict(case: StoreCase, rs: list[RunResult]) -> str:
    """GOOD / THIN / BROKEN / OK(empty) — one label per case, worst market wins."""
    if case.expect_empty:
        return "OK-EMPTY" if all(r.priced == 0 and r.ok for r in rs) else "LEAK"
    if any(not r.ok for r in rs):
        return "BROKEN"
    if any(r.bad_prices for r in rs):
        return "BADPRICE"
    frac = [r.priced / r.total for r in rs if r.total]
    if not frac or min(frac) == 0:
        return "BROKEN"
    return "GOOD" if min(frac) >= case.min_coverage else "THIN"


def report(rows: list[tuple[StoreCase, list[RunResult]]]) -> dict:
    """Print a per-case table + summary; return counts for programmatic use."""
    print(f"\n{'CASE':26s} {'VERDICT':9s} {'COVERAGE':17s} {'LAT(s)':9s} NOTES")
    print("-" * 88)
    tally: dict[str, int] = {}
    for case, rs in rows:
        v = verdict(case, rs)
        tally[v] = tally.get(v, 0) + 1
        cov = [f"{r.priced}/{r.total}" for r in rs]
        cov_str = " ".join(cov[:3]) + (" ..." if len(cov) > 3 else "")
        lats = [r.seconds for r in rs]
        lat_str = (f"{statistics.mean(lats):.1f}"
                   + (f"+/-{statistics.pstdev(lats):.1f}" if len(lats) > 1 else ""))
        err = next((r.error for r in rs if r.error), "")
        print(f"{case.label:26s} {v:9s} {cov_str:17s} {lat_str:9s} {err}")
    print("-" * 88)
    print("SUMMARY: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return tally
