"""Reusable store-integration test pipeline.

Validates every store pricing backend (official API, Instacart, or direct
storefront) against the same yardstick — resolution, coverage, price sanity,
latency, and run-to-run reliability — so adding a new store or data source means
adding ONE entry in registry.py and getting a full health report for free.

Scope note: this harness *measures* an integration's health (does it return
correct prices, how completely, how fast, how reliably). It does not itself
defeat anti-bot protections — a flaky, protected source simply shows up as low
coverage / high variance here, which is exactly the signal you want when
deciding whether a source is production-viable.

Run:  python -m tests_integration.run --help
"""
