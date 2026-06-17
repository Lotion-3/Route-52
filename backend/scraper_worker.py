"""
Weekly scraper worker — prices every ingredient at every store and writes
results to Supabase.

Usage:
    # One-shot run:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python scraper_worker.py

    # Crontab (runs every Monday at 6 AM):
    0 6 * * 1 cd /opt/basketbuddy && \
      SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
      python scraper_worker.py >> /var/log/basketbuddy_scraper.log 2>&1
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "config.env"))

from db import db


# ── Pricing module imports ─────────────────────────────────────────────────
import aldi.aldi_pricing as aldi_pricing
import kroger_async
import instacart_pricing
from instacart_pricing import get_instacart_slug
import walmart_pricing
import target_pricing
import trader_joes_pricing
import meijer_pricing


# ── Chain-specific pricing dispatch ───────────────────────────────────────

CHAIN_DISPATCH = {
    "Kroger": "kroger",
    "King Soopers": "kroger",   # same Kroger API
    "ALDI": "aldi",
    "Walmart": "walmart",
    "Target": "target",
    "Trader Joe's": "trader_joes",
    "Costco": "costco",
    "Meijer": "meijer",
}


def _build_shopping_dict(ingredients: list[dict]) -> dict:
    """Convert ingredient list [{name, qty, unit}, ...] to the dict format
    expected by price_all_* functions: {name: {qty, unit}}.
    The qty is set to 1 since the scraper just stores unit prices."""
    return {ing["name"]: {"qty": 1, "unit": ing.get("unit", "ct")} for ing in ingredients}


async def price_store(store: dict, ingredients: dict) -> tuple[str, dict, dict]:
    """Price all ingredients at the given store.
    Returns (store_name, {ing_name: result, ...}, meta).
    """
    chain = store["chain"]
    method = CHAIN_DISPATCH.get(chain)
    lat, lon = store["lat"], store["lon"]

    if method == "kroger":
        _, _, prices = await kroger_async.price_all_async(ingredients, lat, lon)
        return store["name"], prices, {}
    elif method == "aldi":
        _, _, prices = aldi_pricing.price_all_aldi(ingredients, lat, lon)
        return store["name"], prices, {}
    elif method == "walmart":
        _, _, prices = walmart_pricing.price_all_walmart(ingredients, lat, lon)
        return store["name"], prices, {}
    elif method == "target":
        _, _, prices = target_pricing.price_all_target(ingredients, lat, lon)
        return store["name"], prices, {}
    elif method == "trader_joes":
        _, prices = trader_joes_pricing.price_all_tj(ingredients)
        return store["name"], prices, {}
    elif method == "meijer":
        _, _, prices = meijer_pricing.price_all_meijer(ingredients, lat, lon)
        return store["name"], prices, {}
    elif method == "costco":
        _, _, prices, meta = instacart_pricing.price_all_costco(ingredients, lat, lon)
        return store["name"], prices, meta
    else:
        # Fallback: try Instacart slug
        slug = get_instacart_slug(chain)
        if slug:
            _, _, prices = instacart_pricing.price_all_instacart(ingredients, lat, lon, slug)
            return store["name"], prices, {}
        return store["name"], {}, {"error": f"No pricing method for chain: {chain}"}


# ── Main ──────────────────────────────────────────────────────────────────

def run():
    start = time.time()

    # 1. Get all ingredients from Supabase
    ingredients = db.get_ingredients()
    if not ingredients:
        print("No ingredients found in DB — run seed_meals.py first.")
        sys.exit(1)
    shopping_dict = _build_shopping_dict(ingredients)
    print(f"Loaded {len(ingredients)} ingredients from Supabase.")

    # 2. Get all stores
    stores = db.get_all_stores()
    if not stores:
        print("No stores found in DB — run seed_stores.py first.")
        sys.exit(1)
    print(f"Loaded {len(stores)} stores from Supabase.")

    # 3. Price each store
    total_priced = 0
    total_failed = 0

    for store in stores:
        print(f"\nPricing {store['chain']} — {store['name']}...", end=" ", flush=True)
        try:
            store_name, prices, meta = asyncio.run(
                price_store(store, shopping_dict)
            )
        except Exception as e:
            print(f"FAILED ({e})", flush=True)
            total_failed += 1
            continue

        if not prices:
            print("no prices returned", flush=True)
            total_failed += 1
            continue

        # Upsert prices into Supabase
        inserted = db.batch_upsert_prices(store["id"], prices)
        total_priced += inserted
        print(f"priced {len(prices)} ingredients, upserted {inserted} rows", flush=True)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s — {total_priced} prices written, {total_failed} stores failed.")


if __name__ == "__main__":
    run()
