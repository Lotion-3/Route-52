# basketBuddy — Codebase Review & Modularization Plan

_Date: 2026-07-05_

A review of the backend for inefficiencies, duplication, and modularization
opportunities, plus a reusable store-integration test pipeline. Findings are
ranked by value ÷ effort. Each proposed phase is verifiable via the new pipeline.

---

## Shipped in this pass

### 1. Reusable store-integration test pipeline — [`backend/tests_integration/`](backend/tests_integration/)

One command scores **every** pricing backend (official API, Instacart, or direct
storefront) on the same axes:

| Axis | Meaning |
|---|---|
| resolution | did a real market return anything? |
| coverage | fraction of the basket that priced (`priced/total`) |
| sanity | every line within `$0.01–$200` (catches unit/parse bugs) |
| latency | wall-clock seconds |
| reliability | coverage + latency spread across `--repeat` runs (key signal for flaky/protected sources) |

- Adding a store = one `StoreCase` in [`registry.py`](backend/tests_integration/registry.py); the adapter just returns the `{ingredient: {"total_cost": ...}}` dict, everything else is automatic.
- Verdicts: `GOOD` / `THIN` / `BROKEN` / `BADPRICE` / `OK-EMPTY` / `LEAK`.
- Non-zero exit on failure → CI-friendly.
- **Verified live:** all 5 Kroger banners `GOOD`; reliability mode shows variance (`5/5 5/5, 4.9±1.8s`); no-store edge case returns `OK-EMPTY`.

Run:

```bash
# from backend/ (needs config.env creds)
PYTHONPATH=. python -m tests_integration.run                    # smoke basket, API + Instacart
PYTHONPATH=. python -m tests_integration.run --tag kroger       # just the Kroger banners
PYTHONPATH=. python -m tests_integration.run --tag api --repeat 3 --basket full   # reliability
PYTHONPATH=. python -m tests_integration.run --store Target --tag browser          # slow cases
PYTHONPATH=. python -m tests_integration.run --all              # everything incl. browser
```

Files: `harness.py` (data-source-agnostic core), `registry.py` (declarative
suite + adapters), `baskets.py` (`smoke`/`full` fixtures), `run.py` (CLI),
`README.md`.

> **Scope note:** this harness *measures* integration health; it does not defeat
> anti-bot protections. A protected, flaky source shows up as low coverage / high
> variance — the signal for deciding whether to route it through a sanctioned
> path (official API / Instacart) instead.

### 2. Cache speedup — [`backend/cache_manager.py`](backend/cache_manager.py)

- Added an **in-memory LRU tier**: hot keys (geocode, isochrone, store search) are
  hit many times per request but were re-reading + re-parsing JSON from disk every
  call. Now served from memory.
- **Atomic disk writes** (temp file + `os.replace`) + a **lock**, so the concurrent
  per-store pricing fan-out can't interleave a half-written cache file.
- Public interface unchanged (`cache.get` / `cache.set`); disk tier still warms
  across process restarts (prewarm primes it, generate_plan reads it).
- Unit-tested: basic get, TTL fresh/expired, miss, disk-persist across instances,
  LRU eviction — all pass.

---

## Findings (ranked by value ÷ effort)

| # | Finding | Impact | Effort / Risk |
|---|---|---|---|
| 1 | ~55 one-off scripts clutter the tree | navigability | low / low |
| 2 | Duplicated anti-bot session stack (Target + Walmart) | ~500 dup lines; fix-once | med |
| 3 | Store dispatch not formalized (server.py) | adding a store touches ~5 places | med |
| 4 | Misnamed engine: `kroger_pricing.py` is generic | clarity | low |
| 5 | Prewarm redundancy races pricing | speed + reliability | low–med |
| 6 | Inconsistent pricer return shapes | dispatch complexity | low |
| 7 | `.cache/` grows unbounded on disk | disk | low |
| 8 | Optimizer micro-opts | marginal | low |

### 1. Clutter — ~55 one-off scripts in the tree

- `backend/archive/` — 19 files (old prototypes, debug scripts).
- `backend/probe_costco*.py` — 15 files (Costco reverse-engineering probes).
- `backend/test_*.py` (root) — 11 ad-hoc scripts (now superseded by `tests_integration/`).
- `backend/aldi/aldi_*` recon/debug — ~10 files.

**Action:** move to a `backend/scratch/` (git-ignored) or delete (all in git
history). Keep only `tests_integration/` as the sanctioned test path.

### 2. Duplicated anti-bot session stack

[`target_pricing.py`](backend/target_pricing.py) (858 lines) and
[`walmart_pricing.py`](backend/walmart_pricing.py) (697 lines) reimplement the
*same* machinery:

- CloakBrowser warm (homepage + search-nav) to mint a clearance/PX cookie
- proxy-pool rotation (`_rotate_proxy_session` / `_current_proxy` / `{session}`)
- disk session cache (`_HTTP_SESSION_CACHE`, `_HTTP_COOKIE_TTL`, load/save/validate)
- curl_cffi replay with JA3 impersonation
- IP-refresh retry loop (`MAX_IP_REFRESHES`, `_WARM_TRIES`)
- a `_Blocked` / `_ImpervaBlocked` exception

ALDI, Instacart, King Soopers, and Trader Joe's carry fragments too.

**Action:** extract `cloak_session.py` — a `CloakSession` class parameterized by
`warm_url`, `search_url_builder`, a `is_blocked(resp)` predicate, and a
`parse(text)` callback. Each store module shrinks to ~config + parser.
Bonus: the **proxy-pool + honest no-proxy warning** fix already made for Target
would auto-apply to Walmart.

### 3. Store dispatch not formalized

[`server.py`](backend/server.py) spreads the store logic across:

- hardcoded if-ladder in `_fetch_loop_store` (Trader Joe's → Target → Walmart →
  Costco → Instacart slug)
- separate `_fetch_kroger` / `_fetch_aldi` / `_fetch_meijer` fetchers
- `_WARM_CHAINS` for prewarm
- scattered `is_X_store` matchers + `get_instacart_slug` + module imports

**Action:** a `StoreAdapter` registry — each store = `{matcher, pricer, warmer,
tags, fallback}`. Collapses the dispatch, the fetchers, and `_WARM_CHAINS` into
one table; adding a store becomes a one-entry change. The
[`tests_integration/registry.py`](backend/tests_integration/registry.py) shape is
the template.

### 4. Misnamed core engine

[`kroger_pricing.py`](backend/kroger_pricing.py) (1328 lines) is **not**
Kroger-specific — it's the generic product-matching + unit-conversion engine
(`parse_size`, `to_base`, `find_best_purchase`, `build_priced_product`) that
Walmart, Target, and Meijer all import.

**Action:** rename → `product_matching.py` (or `pricing_core.py`) with a
re-export shim (`from product_matching import *`) so existing imports don't break.

### 5. Prewarm redundancy races pricing

Three triggers fire prewarm — "Start New Meal Plan" ([index.tsx](frontend/app/(tabs)/index.tsx)),
address tap, and Continue ([location.tsx](frontend/app/location.tsx)) — and each
spawns a full Target browser warm. Because Target's warm often fails (no proxy),
nothing caches, so all three run the full ~40s warm serially and **overrun into
the pricing stage** instead of finishing before it.

**Action:** add an in-flight / recent-success guard so the 2nd and 3rd triggers
reuse the running/just-finished warm instead of launching their own. Optionally
lower `TARGET_WARM_TRIES` so a doomed no-proxy warm fails fast (~10s) instead of
lingering.

### 6. Inconsistent pricer return shapes

- most pricers: `(display_name, store_id, prices)`
- Trader Joe's: `(display_name, prices)`
- Costco: `(display_name, store_id, prices, meta)`

**Action:** normalize to a small `PricingResult` dataclass; simplifies the server
dispatch and the test adapters.

### 7. `.cache/` grows unbounded on disk

The disk cache never evicts (visible in git status — modified `.cache/*.json`).
The new in-memory tier is capped, but disk is not.

**Action:** a periodic prune (size cap or age sweep) on the disk tier.

### 8. Optimizer micro-opts (low priority)

[`optimizer.py`](backend/optimizer.py): repeated `location_names.index(store_id)`
(O(n)) inside the k-loops; the final assignment recomputes
`calculate_split_shopping_price`. Marginal given few stores — worth it only if the
optimizer is ever fed many stores.

---

## Speed levers (in priority order)

Pricing is already well-parallelized (concurrent fan-out, sequential fan-in). The
remaining levers:

1. Cache in-memory tier — **done**.
2. Prewarm dedup so warms finish *before* pricing (finding #5).
3. Cache the Kroger live-store-id per (banner, area) to skip liveness probes on
   repeat visits.
4. Share one Instacart session across all IC stores in a route (currently
   bootstrapped per-slug).

---

## Recommended sequence

Each phase is now verifiable via the test pipeline.

- **Phase 1 — safe quick wins:** relocate/delete the ~55 scratch scripts (#1);
  rename `kroger_pricing.py` → `product_matching.py` with a shim (#4); add a
  disk-cache size cap (#7).
- **Phase 2 — high architectural value:** extract `cloak_session.py` shared by
  Target + Walmart (#2) — collapses ~500 duplicated lines and auto-hardens both
  flaky stores; plus the prewarm dedup (#5).
- **Phase 3 — biggest structural change:** `StoreAdapter` registry to collapse
  the server dispatch (#3) and normalize return shapes (#6) — "add a store"
  becomes a one-file change.

**Recommendation:** start with **Phase 2** — highest leverage, and it directly
hardens the two flakiest stores.

---

## Open context (from prior work)

- **No proxy configured** (`CLOAK_PROXY` / `TARGET_PROXY` unset) — Target/Walmart
  anti-bot warms stay a coin-flip until a rotating residential proxy (or pool) is
  set. This is the real fix for those two stores, not more scraping code.
- **Kroger multi-banner** is complete and verified: all banners resolve to the
  right `chain`, dead-ID markets (Fred Meyer, King Soopers) pick a live store, and
  transient 503s are retried instead of silently dropping items.
