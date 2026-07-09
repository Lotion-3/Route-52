# Store-integration test pipeline

A reusable harness that scores **every** store pricing backend on the same axes,
so adding a new store or data source is a one-line change and gets a full health
report for free.

## Run

```bash
# from backend/ (needs config.env creds on PYTHONPATH)
PYTHONPATH=. python -m tests_integration.run                 # smoke basket, API + Instacart
PYTHONPATH=. python -m tests_integration.run --tag kroger    # just the Kroger banners
PYTHONPATH=. python -m tests_integration.run --tag api --repeat 3 --basket full   # reliability
PYTHONPATH=. python -m tests_integration.run --store Target --tag browser          # slow cases
PYTHONPATH=. python -m tests_integration.run --all           # everything incl. browser
```

Exit code is non-zero if any case is `BROKEN`, `LEAK`, or `BADPRICE` — CI-friendly.

## What it measures

| Axis | Meaning |
|---|---|
| **resolution** | did a real market return anything at all? |
| **coverage** | fraction of the basket that priced (`priced/total`) |
| **sanity** | every line within a plausible range (`$0.01–$200`) — catches unit/parse bugs |
| **latency** | wall-clock seconds per run |
| **reliability** | coverage + latency spread across `--repeat` runs — the key signal for flaky, protection-fronted sources |

Verdicts: `GOOD` (≥ min_coverage, sane), `THIN` (priced but sparse), `BROKEN`
(error/zero), `BADPRICE` (out-of-range line), `OK-EMPTY`/`LEAK` (edge cases).

## Add a store

Add one `StoreCase` to `registry.py`:

```python
StoreCase(
    "IC: Wegmans",                      # label
    _instacart("wegmans"),             # adapter -> (basket, lat, lon) -> prices
    [Market("Rochester", 43.16, -77.61)],
    ("instacart",),                    # tags for --tag filtering
    min_coverage=0.5,
)
```

The adapter's only job is to call the native pricer and return the
`{ingredient: {"total_cost": ...}}` dict. Everything else is automatic.

## Files

- `harness.py` — `StoreCase`, `run_case`, `verdict`, `report` (data-source agnostic)
- `registry.py` — the declarative suite + per-pricer adapters
- `baskets.py` — `smoke` (5 items) and `full` (~24) fixtures
- `run.py` — CLI

## Scope

This harness *measures* integration health; it does not defeat anti-bot
protections. A protected, flaky source simply shows up as low coverage / high
variance here — exactly the signal for deciding if a source is production-viable
or should route through a sanctioned path (official API / Instacart) instead.
