"""
Diagnose why ~25/78 ingredients fail Kroger pricing.
Runs the full pipeline verbosely for every ingredient that returns None.
"""
import asyncio, os, aiohttp
from dotenv import load_dotenv
from kroger_pricing import find_best_purchase
from kroger_search_map import get_all_terms

load_dotenv("config.env")
_CLIENT_ID     = os.getenv("KROGER_CLIENT_ID")
_CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
BASE_URL       = "https://api-ce.kroger.com/v1"

# Houston store used in the last live test
STORE_ID = "03400223"

# Typical 5-day, 3 meal/day ingredient list (pull from meals.json to be accurate)
import json, pathlib
meals_path = pathlib.Path(__file__).parent / "meals.json"
meals_data = json.loads(meals_path.read_text(encoding="utf-8"))

# Pick first 78 unique ingredients (mirrors what the server sends)
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
print(f"Testing {len(INGREDIENTS)} ingredients against store {STORE_ID}")


async def get_token(session):
    async with session.post(
        f"{BASE_URL}/connect/oauth2/token",
        data={"grant_type": "client_credentials", "scope": "product.compact"},
        auth=aiohttp.BasicAuth(_CLIENT_ID, _CLIENT_SECRET),
    ) as r:
        return (await r.json(content_type=None)).get("access_token")


async def diagnose_one(session, token, name, qty, unit, semaphore):
    headers = {"Authorization": f"Bearer {token}"}
    terms = get_all_terms(name)
    hit_statuses = []

    for term in terms:
        async with semaphore:
            try:
                async with session.get(
                    f"{BASE_URL}/products",
                    headers=headers,
                    params={"filter.term": term, "filter.locationId": STORE_ID, "filter.limit": 10},
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status != 200:
                        hit_statuses.append(f"HTTP {resp.status}")
                        continue
                    data = await resp.json(content_type=None)
                    products = data.get("data", [])
                    if not products:
                        hit_statuses.append(f"'{term}' → 0 results")
                        continue
                    result = find_best_purchase(name, qty, unit, products)
                    if result:
                        return name, "OK", result["total_cost"], result["description"]
                    else:
                        sizes = [p.get("items", [{}])[0].get("size", "?") for p in products[:3]]
                        hit_statuses.append(f"'{term}' → {len(products)} products, find_best_purchase=None (sizes={sizes})")
            except Exception as e:
                hit_statuses.append(f"'{term}' → exc: {e}")

    return name, "MISS", 0, " | ".join(hit_statuses[-3:])  # last 3 attempts


async def main():
    sem = asyncio.Semaphore(20)
    async with aiohttp.ClientSession() as session:
        token = await get_token(session)
        print(f"Token: {'OK' if token else 'FAILED'}\n")

        tasks = [
            diagnose_one(session, token, name, float(d["qty"]), str(d["unit"]), sem)
            for name, d in INGREDIENTS.items()
        ]
        results = await asyncio.gather(*tasks)

    ok   = [(n, cost, desc) for n, status, cost, desc in results if status == "OK"]
    miss = [(n, reason)      for n, status, cost, reason in results if status == "MISS"]

    print(f"{'='*70}")
    print(f"PRICED {len(ok)}/{len(INGREDIENTS)}")
    print(f"{'='*70}")

    if miss:
        print(f"\nFAILED ({len(miss)}):")
        for name, reason in sorted(miss):
            print(f"  MISS {name:<40} {reason}")

    print(f"\nSAMPLE HIT:")
    for name, cost, desc in ok[:10]:
        print(f"  HIT  {name:<40} ${cost:.2f}  {desc[:40]}")

asyncio.run(main())
