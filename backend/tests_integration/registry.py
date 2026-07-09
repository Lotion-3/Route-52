"""Declarative registry of every store integration under test.

Adding a store = add ONE StoreCase here. The `price_fn` adapter normalizes the
store's native pricer to `(basket, lat, lon) -> prices_dict`; everything else
(coverage, sanity, latency, reliability, reporting) is handled by the harness.
"""
from __future__ import annotations

import asyncio

from .harness import Market, StoreCase

# --- native pricers ---------------------------------------------------------
import kroger_async
import target_pricing
import walmart_pricing
import meijer_pricing
import trader_joes_pricing
import instacart_pricing
from aldi.aldi_pricing import price_all_aldi


# --- adapters: wrap each native pricer to (basket, lat, lon) -> prices -------
def _kroger(banner: str):
    return lambda b, lat, lon: asyncio.run(
        kroger_async.price_all_async(b, lat, lon, store_name=banner)
    )[2]

def _instacart(slug: str):
    return lambda b, lat, lon: instacart_pricing.price_all_instacart(b, lat, lon, slug)[2]

_target = lambda b, lat, lon: target_pricing.price_all_target(b, lat, lon)[2]
_walmart = lambda b, lat, lon: walmart_pricing.price_all_walmart(b, lat, lon)[2]
_aldi = lambda b, lat, lon: price_all_aldi(b, lat, lon)[2]
_meijer = lambda b, lat, lon: meijer_pricing.price_all_meijer(b, lat, lon)[2]
_tj = lambda b, lat, lon: trader_joes_pricing.price_all_tj(b)[1]
_costco = lambda b, lat, lon: instacart_pricing.price_all_costco(b, lat, lon)[2]

# --- reusable markets -------------------------------------------------------
CARMEL = Market("Carmel IN", 39.97, -86.13)
LA = Market("Los Angeles", 34.05, -118.24)
PDX = Market("Portland", 45.52, -122.68)
DEN = Market("Denver", 39.74, -104.99)
MIA = Market("Miami", 25.76, -80.19)
NYC = Market("Manhattan", 40.71, -74.00)  # no Kroger — edge case


# --- the suite --------------------------------------------------------------
def all_cases() -> list[StoreCase]:
    return [
        # Official Kroger API (fast, sanctioned) — several banners incl. overlap markets.
        StoreCase("Kroger",        _kroger("Kroger"),       [CARMEL], ("api", "kroger")),
        StoreCase("Kroger/Ralphs", _kroger("Ralphs"),       [LA],     ("api", "kroger")),
        StoreCase("Kroger/FredMeyer", _kroger("Fred Meyer"),[PDX],    ("api", "kroger")),
        StoreCase("Kroger/KingSoopers", _kroger("King Soopers"), [DEN], ("api", "kroger")),
        StoreCase("Kroger/Food4Less", _kroger("Food 4 Less"),[LA],    ("api", "kroger")),
        # Direct storefront (structured API).
        StoreCase("Meijer",        _meijer,                 [CARMEL], ("api", "direct")),
        # Instacart marketplace (one integration, many banners).
        StoreCase("ALDI",          _aldi,                   [CARMEL], ("instacart",)),
        StoreCase("IC: Publix",    _instacart("publix"),    [MIA],    ("instacart",)),
        StoreCase("IC: WholeFoods", _instacart("whole-foods-market"), [CARMEL], ("instacart",)),
        StoreCase("Costco",        _costco,                 [CARMEL], ("instacart",)),
        StoreCase("Trader Joe's",  _tj,                     [CARMEL], ("instacart", "direct")),
        # Browser / anti-bot-fronted (slow, flaky without a proxy) — opt-in.
        StoreCase("Target",        _target,                 [CARMEL], ("browser",), min_coverage=0.3),
        StoreCase("Walmart",       _walmart,                [CARMEL], ("browser",)),
        # Edge case: a market with no Kroger must degrade to empty, not crash.
        StoreCase("Kroger/no-store", _kroger("Kroger"),     [NYC], ("api", "edge"), expect_empty=True),
    ]


def select(cases: list[StoreCase], labels=None, tags=None) -> list[StoreCase]:
    """Filter cases by label substring(s) and/or tag(s)."""
    out = cases
    if tags:
        out = [c for c in out if any(t in c.tags for t in tags)]
    if labels:
        out = [c for c in out if any(l.lower() in c.label.lower() for l in labels)]
    return out
