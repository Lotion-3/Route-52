"""
Test Kroger API against all 200 ingredients.
Prefers Kroger/store brand items and larger quantities for best value.
Measures response times to inform weekly vs live calling decision.
"""

import os, time, json, requests
from dotenv import load_dotenv

load_dotenv("config.env")

CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
BASE_URL = "https://api-ce.kroger.com/v1"
LOCATION_ID = "53100503"  # Marianos Lakeshore East, Chicago

# Store brands to prefer (in priority order)
STORE_BRANDS = ["kroger", "simple truth", "private selection", "roundy", "heritage farm", "comforts"]

# Words that indicate a result is irrelevant to grocery search
IRRELEVANT_KEYWORDS = [
    "sunscreen", "lotion", "shampoo", "conditioner", "detergent", "cleaner",
    "candle", "soap", "vitamin", "supplement", "pill", "medication", "medicine",
    "toy", "pet", "dog", "cat", "artificial", "fake", "decor", "decoration",
    "dvd", "book", "magazine", "gift card", "battery", "batteries"
]


def get_token():
    resp = requests.post(
        f"{BASE_URL}/connect/oauth2/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials", "scope": "product.compact"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def is_relevant(description: str, search_term: str) -> bool:
    desc_lower = description.lower()
    for word in IRRELEVANT_KEYWORDS:
        if word in desc_lower:
            return False
    # At least one word from search term should appear in description
    term_words = [w for w in search_term.lower().split() if len(w) > 2]
    return any(w in desc_lower for w in term_words)


def score_product(product: dict, search_term: str) -> float:
    """Score a product — higher is better. Prefers store brand + larger size."""
    item = product.get("items", [{}])[0]
    price = item.get("price", {})
    regular = price.get("regular")
    if not regular:
        return -1

    description = product.get("description", "").lower()
    score = 0.0

    # Prefer store brands
    for i, brand in enumerate(STORE_BRANDS):
        if brand in description:
            score += (len(STORE_BRANDS) - i) * 10
            break

    # Prefer larger sizes (higher price = larger pack = better unit value)
    score += min(regular, 20) * 0.5

    # Penalise tiny sizes (under $1 often means tiny unit)
    if regular < 1.0:
        score -= 5

    return score


def best_price(token, term):
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter.term": term, "filter.locationId": LOCATION_ID, "filter.limit": 10}
    t0 = time.time()
    resp = requests.get(f"{BASE_URL}/products", headers=headers, params=params)
    elapsed = time.time() - t0
    resp.raise_for_status()

    products = resp.json().get("data", [])

    # Filter irrelevant results
    relevant = [p for p in products if is_relevant(p.get("description", ""), term)]
    if not relevant:
        relevant = products  # fall back to all if filter too aggressive

    # Score and pick best
    scored = [(score_product(p, term), p) for p in relevant]
    scored = [(s, p) for s, p in scored if s >= 0]
    if not scored:
        return None, elapsed

    _, best = max(scored, key=lambda x: x[0])
    item = best.get("items", [{}])[0]
    price = item.get("price", {})
    regular = price.get("regular")
    promo = price.get("promo")

    return {
        "name": best["description"],
        "price": promo if promo else regular,
        "regular_price": regular,
        "on_sale": bool(promo),
        "size": item.get("size", ""),
    }, elapsed


if __name__ == "__main__":
    ingredients = [l.strip() for l in open("ingredients.txt") if l.strip()]
    print(f"Testing {len(ingredients)} ingredients at Marianos Chicago...\n")

    token = get_token()

    results = {}
    misses = []
    times = []
    errors = []
    total_start = time.time()

    for i, item in enumerate(ingredients):
        try:
            data, elapsed = best_price(token, item)
            times.append(elapsed)
            if data:
                results[item] = data
                sale = " SALE" if data["on_sale"] else ""
                print(f"  [{i+1:3d}] {item:<35} ${data['price']:>6.2f}  {data['size']:<15} {data['name'][:35]}{sale}  {elapsed:.2f}s")
            else:
                misses.append(item)
                print(f"  [{i+1:3d}] {item:<35} MISS  {elapsed:.2f}s")
        except Exception as e:
            errors.append((item, str(e)))
            times.append(0)
            print(f"  [{i+1:3d}] {item:<35} ERROR: {e}")

    wall_time = time.time() - total_start

    print(f"\n{'='*70}")
    print(f"Results:       {len(results)}/200 ({len(results)/200*100:.0f}% hit rate)")
    print(f"Misses:        {len(misses)}")
    print(f"Errors:        {len(errors)}")
    print(f"Avg call time: {sum(times)/len(times)*1000:.0f}ms per item")
    print(f"Total API time:{sum(times):.1f}s")
    print(f"Wall time:     {wall_time:.1f}s")
    print(f"\nVerdict: {'Live calling feasible' if sum(times)/len(times) < 0.5 else 'Weekly refresh recommended'} (avg {sum(times)/len(times)*1000:.0f}ms/call)")
    if misses:
        print(f"\nMisses: {misses}")

    with open("kroger_prices_test.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved -> kroger_prices_test.json")
