"""
Real grocery deals from the Flipp API (weekly flyers + digital coupons),
applied to the price database BEFORE route optimization so the savings are
reflected in both the cheapest-route comparison and the displayed prices.

Two deal types:
  - Flyer sale items: store-specific advertised prices (merchant + name + price).
    Matched to cart ingredients per store and normalized through
    find_best_purchase (which already handles relevance + size + unit math);
    overrides a store's unit price only when the sale actually beats it.
  - Digital coupons: manufacturer dollar-off coupons (brand + "$X off N").
    Matched to cart ingredients by keyword; reduces that ingredient's per-unit
    price at every store that carries it (a manufacturer coupon saves you
    regardless of where you buy).

Entry points:
    flyers, coupons = fetch_deals(postal_code)
    applied = apply_deals(price_database, to_buy_quantities, flyers, coupons)
        -> mutates price_database in place, returns {(store, ing_key): deal}
"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime
from typing import Optional

import requests
import urllib3

from kroger_pricing import find_best_purchase

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Flipp API
# ---------------------------------------------------------------------------

_DATA_URL = "https://flyers-ng.flippback.com/api/flipp/data?locale=en&postal_code={}&sid={}"
_FLYER_ITEMS_URL = "https://flyers-ng.flippback.com/api/flipp/flyers/{}/flyer_items?locale=en&sid={}"

# Banners we price against (must align with the stores the app searches).
STORE_KEYWORDS = [
    "Walmart", "Aldi", "Kroger", "Target", "Meijer", "Whole Foods",
    "Trader Joe's", "Trader Joes", "Costco", "Jewel Osco", "Publix",
    "Safeway", "Wegmans", "Sprouts", "Hy-Vee", "Food Lion", "Giant",
    "H-E-B", "HEB",
]

_CACHE_TTL = 6 * 3600          # flyers change weekly; 6h cache is plenty
_deals_cache: dict[str, tuple[float, tuple]] = {}   # postal -> (expires, (flyers, coupons))


def _sid() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(16))


def _get_flipp_data(postal_code: str) -> dict:
    r = requests.get(_DATA_URL.format(postal_code, _sid()), verify=False, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_flyer_items(flyer_id: int) -> list:
    r = requests.get(_FLYER_ITEMS_URL.format(flyer_id, _sid()), verify=False, timeout=15)
    r.raise_for_status()
    return r.json()


def _is_active(valid_from: Optional[str], valid_to: Optional[str]) -> bool:
    now = datetime.now()
    try:
        if valid_from:
            if now < datetime.fromisoformat(valid_from.split(".")[0].split("+")[0]):
                return False
        if valid_to:
            if now > datetime.fromisoformat(valid_to.split(".")[0].split("+")[0]):
                return False
    except Exception:
        return True
    return True


# ---------------------------------------------------------------------------
# Coupon savings parsing  ("$1.00 off 2"  ->  (1.0, 2))
# ---------------------------------------------------------------------------

_SAVINGS_RE = re.compile(r"\$?\s*(\d+(?:\.\d+)?)\s*off\s*(\d+)?", re.IGNORECASE)


def _parse_savings(sale_story: str) -> Optional[tuple[float, int]]:
    if not sale_story:
        return None
    m = _SAVINGS_RE.search(sale_story)
    if not m:
        return None
    try:
        dollars = float(m.group(1))
    except Exception:
        return None
    qty = int(m.group(2)) if m.group(2) else 1
    if dollars <= 0 or dollars > 50:
        return None
    return dollars, max(1, qty)


# ---------------------------------------------------------------------------
# Fetch + filter deals for a postal code
# ---------------------------------------------------------------------------

def fetch_deals(postal_code: str) -> tuple[dict, list]:
    """
    Return (flyers_by_banner, coupons) for a postal code.

    flyers_by_banner : {banner_keyword_lower: [(item_name, price_float), ...]}
    coupons          : [{brand, dollars, qty, keywords, description, image_url,
                         valid_to}, ...]
    """
    if not postal_code:
        return {}, []
    postal_code = postal_code.strip().upper()

    cached = _deals_cache.get(postal_code)
    if cached and cached[0] > time.time():
        return cached[1]

    try:
        data = _get_flipp_data(postal_code)
    except Exception as e:
        print(f"[Flipp] data fetch failed ({e}).", flush=True)
        return {}, []

    # --- Flyers -----------------------------------------------------------
    flyers_by_banner: dict[str, list[tuple[str, float]]] = {}
    for flyer in data.get("flyers", []):
        merchant = flyer.get("merchant", "") or ""
        categories = flyer.get("categories", [])
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",")]
        banner = next((kw.lower() for kw in STORE_KEYWORDS if kw.lower() in merchant.lower()), None)
        if not banner or "Groceries" not in categories:
            continue
        if not _is_active(flyer.get("valid_from"), flyer.get("valid_to")):
            continue
        try:
            items = _get_flyer_items(flyer["id"])
        except Exception:
            continue
        bucket = flyers_by_banner.setdefault(banner, [])
        for item in items:
            name = (item.get("name") or "").strip()
            price = item.get("price")
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if name and 0.01 <= price <= 500:
                bucket.append((name, price))

    # --- Digital coupons --------------------------------------------------
    coupons: list[dict] = []
    for c in data.get("coupons", []):
        cats = c.get("categories", [])
        if "Grocery" not in cats:
            continue
        if not _is_active(c.get("valid_from"), c.get("valid_to")):
            continue
        parsed = _parse_savings(c.get("sale_story", ""))
        if not parsed:
            continue
        dollars, qty = parsed
        brand = c.get("brand", "") or ""
        desc = c.get("promotion_text", "") or ""
        coupons.append({
            "brand": brand,
            "dollars": dollars,
            "qty": qty,
            "keywords": _coupon_keywords(brand, desc),
            "description": desc,
            "image_url": c.get("coupon_image_url", "") or "",
            "valid_to": c.get("valid_to", "") or "",
        })

    result = (flyers_by_banner, coupons)
    _deals_cache[postal_code] = (time.time() + _CACHE_TTL, result)
    total_flyer = sum(len(v) for v in flyers_by_banner.values())
    print(f"[Flipp] {postal_code}: {total_flyer} flyer items across "
          f"{len(flyers_by_banner)} banners, {len(coupons)} grocery coupons.", flush=True)
    return result


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

_STOP = {
    "off", "each", "all", "varieties", "or", "and", "the", "with", "select",
    "your", "any", "save", "when", "you", "buy", "pk", "oz", "ct", "lb",
}


def _coupon_keywords(brand: str, desc: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", f"{brand} {desc}".lower())
    return [w for w in words if w not in _STOP]


def _banner_of(store_name: str) -> Optional[str]:
    low = store_name.lower()
    return next((kw.lower() for kw in STORE_KEYWORDS if kw.lower() in low), None)


_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(fl\.?\s*oz|oz|lb|lbs|pound|gal|gallon|count|ct|pk|pack|each|liter|l|ml|g|kg|dozen)",
    re.IGNORECASE,
)


def _flyer_to_product(name: str, price: float) -> dict:
    """Wrap a flyer item in the product shape find_best_purchase expects."""
    m = _SIZE_RE.search(name)
    if m:
        size = f"{m.group(1)} {m.group(2)}"
    elif "dozen" in name.lower():
        size = "12 count"
    else:
        size = "1 each"
    return {
        "description": name,
        "brand": "",
        "items": [{
            "itemId": "flyer",
            "soldBy": "UNIT",
            "size": size,
            "price": {"regular": float(price), "promo": None},
        }],
    }


# ---------------------------------------------------------------------------
# Apply deals to the price database
# ---------------------------------------------------------------------------

def apply_deals(
    price_database: dict,
    to_buy_quantities: dict,
    flyers_by_banner: dict,
    coupons: list,
) -> dict:
    """
    Mutate price_database in place, lowering unit prices where a real deal
    beats the current price. Returns {(store_key, ing_key): deal_dict} describing
    every applied saving, for display in the response.
    """
    applied: dict[tuple[str, str], dict] = {}

    ingredients = list(to_buy_quantities.items())  # [(name, {qty, unit, ...}), ...]

    # --- 1. Flyer sale prices (store-specific) ----------------------------
    for store_key in list(price_database.keys()):
        banner = _banner_of(store_key)
        if not banner or banner not in flyers_by_banner:
            continue
        # Skip ALDI — prices come from the Instacart API directly and are already
        # accurate. Flipp's ALDI flyer data often covers a different zone or lags
        # behind, so applying it overwrites correct API prices with wrong ones.
        if banner == "aldi":
            continue
        flyer_products = [_flyer_to_product(n, p) for n, p in flyers_by_banner[banner]]
        if not flyer_products:
            continue
        store_prices = price_database[store_key]
        for ing_name, data in ingredients:
            ing_key = ing_name.lower().strip()
            cur_unit = store_prices.get(ing_key)
            if not cur_unit or cur_unit <= 0:
                continue
            qty = float(data.get("qty", 1) or 1)
            unit = str(data.get("unit", "whole"))
            best = find_best_purchase(ing_name, qty, unit, flyer_products)
            if not best:
                continue
            new_unit = best["total_cost"] / qty if qty else best["total_cost"]
            # Only apply genuine, sane improvements (guard against bad matches
            # and flyer prices that aren't a true per-package sale price).
            if new_unit < cur_unit and new_unit >= cur_unit * 0.4:
                store_prices[ing_key] = new_unit
                applied[(store_key, ing_key)] = {
                    "type": "flyer",
                    "label": best.get("description", ing_name),
                    "old_unit": cur_unit,
                    "new_unit": new_unit,
                    "savings": round((cur_unit - new_unit) * qty, 2),
                    "image_url": "",
                    "valid_to": "",
                }

    # --- 2. Digital coupons (manufacturer, all stores) --------------------
    for coupon in coupons:
        kws = set(coupon["keywords"])
        if not kws:
            continue
        for ing_name, data in ingredients:
            ing_low = ing_name.lower()
            ing_words = set(re.findall(r"[a-zA-Z]{3,}", ing_low))
            # Require a strong overlap (>=2 shared words) so a single generic
            # noun like "chicken" can't pull in an unrelated brand (e.g. a pasta
            # coupon onto chicken breast). Keeps clear matches like
            # "Nellie's ... Large Eggs" -> "Large Eggs".
            if len(ing_words & kws) < 2:
                continue
            qty = float(data.get("qty", 1) or 1)
            per_unit_cut = coupon["dollars"] / max(qty, 1)
            ing_key = ing_name.lower().strip()
            for store_key in price_database:
                store_prices = price_database[store_key]
                cur = store_prices.get(ing_key)
                if not cur or cur <= 0:
                    continue
                new = max(cur - per_unit_cut, cur * 0.1, 0.01)
                if new >= cur:
                    continue
                store_prices[ing_key] = new
                # Coupon wins the badge only if no (better) flyer deal is shown.
                applied.setdefault((store_key, ing_key), {
                    "type": "coupon",
                    "label": f"{coupon['brand']}: {coupon['description']}".strip(": "),
                    "old_unit": cur,
                    "new_unit": new,
                    "savings": round((cur - new) * qty, 2),
                    "image_url": coupon["image_url"],
                    "valid_to": coupon["valid_to"],
                })
            break  # one coupon applies to one ingredient line

    return applied
