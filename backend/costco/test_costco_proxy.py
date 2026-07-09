"""Verify the Costco national-price proxy: covered metro -> exact; remote -> estimate."""
import instacart_pricing as ic

BASKET = {
    "milk":           {"qty": 1,  "unit": "gallon"},
    "eggs":           {"qty": 12, "unit": "count"},
    "chicken breast": {"qty": 3,  "unit": "pound"},
    "olive oil":      {"qty": 1,  "unit": "count"},
}

CASES = [
    ("Seattle, WA (covered metro)",  47.6062, -122.3321),
    ("Pinedale, WY (remote)",        42.8666, -109.8607),
    ("Williston, ND (remote)",       48.1470, -103.6180),
    ("Presque Isle, ME (remote)",    46.6812,  -68.0161),
]

for label, lat, lon in CASES:
    print(f"\n{'='*70}\n{label}  ({lat}, {lon})")
    name, sid, prices, meta = ic.price_all_costco(BASKET, lat, lon)
    if not prices:
        print(f"  -> NO Costco priced. meta={meta}")
        continue
    total = sum(v.get("total_cost", 0) for v in prices.values() if v)
    tag = f"ESTIMATE (~{int(meta['distance_km'])} km away)" if meta["is_estimate"] else "EXACT (local same-day)"
    print(f"  -> {tag}  store={meta['store']!r}  shopId={sid}")
    print(f"  -> {len(prices)}/{len(BASKET)} priced, basket ${total:.2f}")
    for k, v in sorted(prices.items()):
        print(f"       {k:16s} ${v.get('total_cost',0):7.2f}  {v.get('description','')[:40]}")
