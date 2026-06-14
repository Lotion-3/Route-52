"""
Full audit of Kroger + ALDI pricing quality.
Shows every ingredient with the matched product name, price, and size so we can spot bad matches.
"""
import asyncio, aiohttp, os, json, pathlib, sys
from dotenv import load_dotenv
load_dotenv("config.env")

from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

STORE = "03400223"  # Houston Kroger
BASE = "https://api-ce.kroger.com/v1"

# Load ingredients from meals.json (same slice the server uses)
meals_path = pathlib.Path(__file__).parent / "meals.json"
meals_data = json.loads(meals_path.read_text(encoding="utf-8"))
seen = {}
for meal in meals_data[:35]:
    for ing in meal.get("ingredients", []):
        name = ing["name"]
        if name not in seen:
            seen[name] = {"qty": float(ing.get("qty", 1)), "unit": ing.get("unit", "whole")}
        if len(seen) >= 78:
            break
    if len(seen) >= 78:
        break

INGREDIENTS = seen


async def get_token(session):
    async with session.post(
        f"{BASE}/connect/oauth2/token",
        data={"grant_type": "client_credentials", "scope": "product.compact"},
        auth=aiohttp.BasicAuth(os.getenv("KROGER_CLIENT_ID"), os.getenv("KROGER_CLIENT_SECRET")),
    ) as r:
        return (await r.json(content_type=None)).get("access_token")


async def price_one(session, token, name, qty, unit, sem):
    headers = {"Authorization": f"Bearer {token}"}
    for term in get_all_terms(name):
        async with sem:
            async with session.get(
                f"{BASE}/products",
                headers=headers,
                params={"filter.term": term, "filter.locationId": STORE, "filter.limit": 10},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    continue
                prods = (await r.json(content_type=None)).get("data", [])
                res = find_best_purchase(name, qty, unit, prods)
                if res:
                    return name, qty, unit, res["total_cost"], res["description"], res["size_str"]
    return name, qty, unit, None, None, None


async def main():
    sem = asyncio.Semaphore(15)
    async with aiohttp.ClientSession() as s:
        token = await get_token(s)
        tasks = [price_one(s, token, n, d["qty"], d["unit"], sem) for n, d in INGREDIENTS.items()]
        results = await asyncio.gather(*tasks)

    hits = [(n, q, u, cost, desc, sz) for n, q, u, cost, desc, sz in results if cost is not None]
    misses = [(n, q, u) for n, q, u, cost, desc, sz in results if cost is None]

    print(f"KROGER AUDIT — Store {STORE}")
    print(f"PRICED {len(hits)}/{len(INGREDIENTS)}")
    print("=" * 100)
    print(f"{'Ingredient':<32} {'Qty':>5} {'Unit':<8} {'Cost':>7}  {'Product matched':<45}  Size")
    print("-" * 100)
    for n, q, u, cost, desc, sz in sorted(hits, key=lambda x: x[0]):
        print(f"{n:<32} {q:>5.1f} {u:<8} ${cost:>5.2f}  {(desc or '')[:45]:<45}  {sz or ''}")

    if misses:
        print(f"\nMISSED ({len(misses)}):")
        for n, q, u in misses:
            print(f"  {n} ({q} {u})")

asyncio.run(main())
