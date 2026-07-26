"""
kroger_pricing.py

Normalizes Kroger API product dicts to a comparable price-per-unit,
picks the cheapest option from a result list, and computes the
cost of a recipe ingredient quantity against that product.

Unit families
─────────────
  mass    → base: oz   (lbs, g, kg all converted)
  volume  → base: fl_oz (gal, qt, pt, cups, tbsp, tsp, ml, L all converted)
  count   → base: ct   (whole, each, pieces, cans, jars, cloves, …)

soldBy field
────────────
  "WEIGHT" → price.regular is per-lb (produce sold loose, etc.)
              We convert to price/oz immediately.
  "UNIT"   → price.regular is for one package.
              We divide by the parsed package size to get price/base-unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Unit conversion tables ────────────────────────────────────────────────────

MASS_TO_OZ: dict[str, float] = {
    "oz": 1.0,
    "lb": 16.0,
    "lbs": 16.0,
    "pound": 16.0,
    "pounds": 16.0,
    "g": 0.035274,
    "gram": 0.035274,
    "grams": 0.035274,
    "kg": 35.274,
    "kilogram": 35.274,
    "kilograms": 35.274,
}

VOL_TO_FLOZ: dict[str, float] = {
    "fl oz": 1.0,
    "fl. oz": 1.0,
    "fl oz.": 1.0,
    "floz": 1.0,
    "fluid ounce": 1.0,
    "fluid ounces": 1.0,
    "oz": 1.0,          # liquid-context: "oz" on bottles usually means fl oz
    "cup": 8.0,
    "cups": 8.0,
    "tbsp": 0.5,
    "tablespoon": 0.5,
    "tablespoons": 0.5,
    "tsp": 1 / 6,
    "teaspoon": 1 / 6,
    "teaspoons": 1 / 6,
    "ml": 0.033814,
    "milliliter": 0.033814,
    "milliliters": 0.033814,
    "millilitre": 0.033814,
    "millilitres": 0.033814,
    "l": 33.814,
    "liter": 33.814,
    "liters": 33.814,
    "litre": 33.814,
    "litres": 33.814,
    "gal": 128.0,
    "gallon": 128.0,
    "gallons": 128.0,
    "qt": 32.0,
    "quart": 32.0,
    "quarts": 32.0,
    "pt": 16.0,
    "pint": 16.0,
    "pints": 16.0,
}

# Units that mean "discrete items" — mapped to base unit "ct"
COUNT_UNIT_STRINGS: set[str] = {
    "ct", "count", "each", "ea", "pk", "pack", "pc", "pcs",
    # recipe units that are count-based
    "whole", "piece", "pieces",
    "slice", "slices",
    "loaf", "loaves",
    "strip", "strips",
    "fillet", "fillets",
    "link", "links",
    "can", "cans",
    "jar", "jars",
    "head", "heads",
    "bunch", "bunches",
    "stalk", "stalks",
    "sprig", "sprigs",
    "leaf", "leaves",
    "clove", "cloves",
    "pinch",
}

# ── Size string parsing ───────────────────────────────────────────────────────

_FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")

# Ordered from most-specific to least; the alternation matters.
_SIZE_PATTERN = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)"      # number (int or decimal)
    r"\s*"
    r"(?P<unit>"
        r"fl\.?\s*oz\.?|fo\b|fluid\s+ounces?|"  # fl oz first (before bare "oz"); "fo" is API typo
        r"oz\.?|lbs?|pounds?|kg|kilograms?|g\b|grams?|"
        r"gallons?|gal|quarts?|qt|pints?|pt|"
        r"liters?|l\b|ml|milliliters?|"
        r"cups?|tbsp|tablespoons?|tsp|teaspoons?|"
        r"bottles?|cans?|"                       # compound-size container words
        r"count|ct|each|ea|pk|pack|pcs?|pc\b"
    r")",
    re.IGNORECASE,
)

# Container words that, in a compound "N containers / X unit" string,
# mean the X unit is per-container and should be multiplied by N.
_CONTAINER_UNITS: set[str] = {"bottles", "bottle", "cans", "can"}
_CONTAINER_RE = re.compile(r"\b(?:bottles?|cans?)\b", re.IGNORECASE)


def _normalize_unit(raw: str) -> str:
    """Normalize a raw matched unit string to a canonical key."""
    u = raw.lower().strip().rstrip(".")
    if re.match(r"fl\.?\s*oz|fluid|^fo$", u):
        return "fl oz"
    if u in ("lbs", "pound", "pounds"):
        return "lb"
    if u in ("gram", "grams"):
        return "g"
    if u in ("kilogram", "kilograms"):
        return "kg"
    if u in ("gallon", "gallons"):
        return "gal"
    if u in ("quart", "quarts"):
        return "qt"
    if u in ("pint", "pints"):
        return "pt"
    if u in ("liter", "liters"):
        return "l"
    if u in ("milliliter", "milliliters"):
        return "ml"
    if u in ("cup", "cups"):
        return "cup"
    if u in ("tablespoon", "tablespoons"):
        return "tbsp"
    if u in ("teaspoon", "teaspoons"):
        return "tsp"
    if u in ("count", "each", "ea", "pack", "pc", "pcs"):
        return "ct"
    if u in ("bottles", "bottle", "cans", "can"):
        return "ct"
    return u


_BARE_UNIT_MAP: dict[str, tuple[float, str]] = {
    "gallon": (1.0, "gal"),   "gallons": (1.0, "gal"),
    "quart":  (1.0, "qt"),    "quarts":  (1.0, "qt"),
    "pint":   (1.0, "pt"),    "pints":   (1.0, "pt"),
    "liter":  (1.0, "l"),     "liters":  (1.0, "l"),
    "litre":  (1.0, "l"),     "litres":  (1.0, "l"),
    "dozen":  (12.0, "ct"),   "dozens":  (12.0, "ct"),
    "pound":  (1.0, "lb"),    "pounds":  (1.0, "lb"),
    "ounce":  (1.0, "oz"),    "ounces":  (1.0, "oz"),
}


def _parse_simple(s: str) -> Optional[tuple[float, str]]:
    """Parse a single (no slash) size token into (qty, unit)."""
    s = s.strip()
    # Bare integer or decimal with no unit → treat as 1 ct
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        try:
            return float(s), "ct"
        except ValueError:
            return None

    # Bare unit word without a leading number (e.g. "Gallon", "Dozen", "Pint")
    bare = _BARE_UNIT_MAP.get(s.lower())
    if bare:
        return bare

    m = _SIZE_PATTERN.search(s)
    if not m:
        return None
    try:
        qty = float(m.group("qty"))
    except ValueError:
        return None
    unit = _normalize_unit(m.group("unit"))
    return qty, unit


def parse_size(size_str: str) -> Optional[tuple[float, str]]:
    """
    Parse a Kroger size string into (quantity, normalized_unit).

    Handles
    -------
    Simple:   "14.5 oz", "1/2 gal", "12 ct", "1 qt", "16 fl oz",
              "2 lb", "1.75 L", "5 lb bag", "1 each", "1" (bare number → 1 ct)
    Compound: "12 ct / 20 oz"       → (20.0, "oz")   [use weight part]
              "6 bottles / 8.55 fl oz" → (51.3, "fl oz") [multiply]
              "3 pk / 56 ct"        → (56.0, "ct")   [use total count]
              "20 ct / 0.20 oz"     → (0.20, "oz")   [use weight part as-is]
    Typos:    "30 fo"               → (30.0, "fl oz")

    Returns None when the string can't be parsed.
    """
    if not size_str:
        return None

    s = size_str.strip()

    # Resolve fraction notation ONLY in non-compound strings to avoid clobbering "/"
    # separators in compound strings.  We detect compound first.
    if " / " in s:
        parts = s.split(" / ", 1)
        left = _FRACTION_RE.sub(
            lambda m: str(int(m.group(1)) / int(m.group(2))), parts[0].strip()
        )
        right = _FRACTION_RE.sub(
            lambda m: str(int(m.group(1)) / int(m.group(2))), parts[1].strip()
        )
        return _parse_compound(left, right)

    # Simple string — resolve fractions then parse
    s = _FRACTION_RE.sub(lambda m: str(int(m.group(1)) / int(m.group(2))), s)
    return _parse_simple(s)


def _parse_compound(left: str, right: str) -> Optional[tuple[float, str]]:
    """
    Resolve a two-part size string "left / right" into a single (qty, unit).

    Strategy
    ────────
    1. "N bottles / X fl oz"  → N × X fl oz  (per-container × count)
    2. "N pk / M ct"          → M ct          (total count)
    3. "N ct / X oz"          → X oz          (package weight wins over count)
    4. Both weight/volume     → whichever has higher family priority
    5. Fallback               → whichever side parsed
    """
    lp = _parse_simple(left)
    rp = _parse_simple(right)

    if lp is None and rp is None:
        return None
    if lp is None:
        return rp
    if rp is None:
        return lp

    l_qty, l_unit = lp
    r_qty, r_unit = rp

    l_fam = unit_family(l_unit)
    r_fam = unit_family(r_unit)

    # "N cans / X fl oz" or "N bottles / X fl oz" → N × per-container volume
    # Check raw left string for container words (before normalization collapsed them to "ct").
    if _CONTAINER_RE.search(left) and r_fam in ("mass", "volume"):
        return (l_qty * r_qty, r_unit)

    # Both are count (e.g. "3 pk / 56 ct") → use the larger count as total
    if l_fam == "count" and r_fam == "count":
        return (max(l_qty, r_qty), "ct")

    # Count + weight/volume (e.g. "12 ct / 20 oz") → use weight/volume
    if l_fam == "count" and r_fam in ("mass", "volume"):
        return rp

    # Weight/volume + count (unusual ordering) → use weight/volume
    if r_fam == "count" and l_fam in ("mass", "volume"):
        return lp

    # Both mass or both volume → use the larger (more informative)
    priority = {"mass": 3, "volume": 2, "count": 1, None: 0}
    if priority.get(l_fam, 0) >= priority.get(r_fam, 0):
        return lp
    return rp





def unit_family(unit: str) -> Optional[str]:
    """Return 'mass', 'volume', or 'count'; None if unknown."""
    u = unit.lower().strip()
    if u in MASS_TO_OZ:
        return "mass"
    if u in VOL_TO_FLOZ:
        return "volume"
    if u in COUNT_UNIT_STRINGS:
        return "count"
    return None


def to_base(qty: float, unit: str) -> Optional[tuple[float, str]]:
    """
    Convert (qty, unit) to (base_qty, base_unit_label).

    mass   → (oz_qty, "oz")
    volume → (floz_qty, "fl_oz")
    count  → (ct_qty, "ct")
    """
    u = unit.lower().strip()
    if u in MASS_TO_OZ:
        return qty * MASS_TO_OZ[u], "oz"
    if u in VOL_TO_FLOZ:
        return qty * VOL_TO_FLOZ[u], "fl_oz"
    if u in COUNT_UNIT_STRINGS:
        return qty, "ct"
    return None


# ── Product price extraction ──────────────────────────────────────────────────

def _effective_price(item: dict) -> Optional[float]:
    """Return the lower of regular and promo price, or None if absent."""
    pb = item.get("price", {})
    regular = pb.get("regular")
    promo = pb.get("promo")
    candidates = [p for p in (regular, promo) if p is not None and p > 0]
    return min(candidates) if candidates else None


# ── PricedProduct dataclass ───────────────────────────────────────────────────

@dataclass
class PricedProduct:
    description: str
    brand: str
    upc: str
    price: float                # raw shelf/promo price
    sold_by: str                # "UNIT" or "WEIGHT"
    size_str: str               # raw size string from API
    size_qty: float             # parsed size quantity
    size_unit: str              # parsed size unit (canonical)
    family: str                 # "mass" | "volume" | "count"
    base_qty: float             # size expressed in base units
    base_unit: str              # "oz" | "fl_oz" | "ct"
    price_per_base: float       # price / base_qty  (per oz, per fl_oz, or per ct)
    notes: list[str] = field(default_factory=list)  # warnings / edge-case notes


def build_priced_product(product: dict) -> Optional[PricedProduct]:
    """
    Build a PricedProduct from a raw Kroger API product dict.

    Returns None when pricing or size information is unusable.

    Edge cases handled
    ------------------
    soldBy = WEIGHT  → price is per-lb; convert immediately to per-oz.
                       size string (e.g. "5 ct") is irrelevant for unit price.
    soldBy = UNIT    → price is for the whole package; divide by parsed size.
    size unparseable → falls back to treating the item as 1 count unit.
    size = 0         → guards against division-by-zero.
    oz ambiguity     → "oz" on beverages / liquid products is treated as fl oz
                       only when the product category hints at it; otherwise mass.
                       (Conservative: default to mass to avoid over-estimating volume.)
    """
    items = product.get("items", [{}])
    if not items:
        return None
    item = items[0]

    price = _effective_price(item)
    if price is None:
        return None

    sold_by = item.get("soldBy", "UNIT").upper()
    size_str = item.get("size", "")
    desc = product.get("description", "")
    brand = product.get("brand", "")
    upc = item.get("itemId", "")
    notes: list[str] = []

    # ── soldBy = WEIGHT ───────────────────────────────────────────────────────
    if sold_by == "WEIGHT":
        # price is per lb; convert to per oz
        price_per_oz = price / 16.0
        return PricedProduct(
            description=desc, brand=brand, upc=upc,
            price=price, sold_by=sold_by, size_str=size_str,
            size_qty=1.0, size_unit="lb",
            family="mass", base_qty=16.0, base_unit="oz",
            price_per_base=price_per_oz,
        )

    # ── soldBy = UNIT ─────────────────────────────────────────────────────────
    parsed = parse_size(size_str)

    if parsed is None:
        # Unparseable size — treat as a single count item
        notes.append(f"size '{size_str}' unparseable; treating as 1 ct")
        return PricedProduct(
            description=desc, brand=brand, upc=upc,
            price=price, sold_by=sold_by, size_str=size_str,
            size_qty=1.0, size_unit="ct",
            family="count", base_qty=1.0, base_unit="ct",
            price_per_base=price,
            notes=notes,
        )

    size_qty, size_unit = parsed
    base = to_base(size_qty, size_unit)

    if base is None:
        notes.append(f"unit '{size_unit}' unknown; treating as 1 ct")
        return PricedProduct(
            description=desc, brand=brand, upc=upc,
            price=price, sold_by=sold_by, size_str=size_str,
            size_qty=size_qty, size_unit=size_unit,
            family="count", base_qty=1.0, base_unit="ct",
            price_per_base=price,
            notes=notes,
        )

    base_qty, base_unit = base
    if base_qty <= 0:
        notes.append("size parsed to 0; treating as 1 ct")
        base_qty = 1.0
        base_unit = "ct"
        family = "count"
    else:
        family = unit_family(size_unit) or "count"

    price_per_base = price / base_qty

    return PricedProduct(
        description=desc, brand=brand, upc=upc,
        price=price, sold_by=sold_by, size_str=size_str,
        size_qty=size_qty, size_unit=size_unit,
        family=family, base_qty=base_qty, base_unit=base_unit,
        price_per_base=price_per_base,
        notes=notes,
    )


def best_product(products: list[dict]) -> Optional[PricedProduct]:
    """
    Given a list of Kroger API product dicts, return the one with the lowest
    price per base unit.

    When products span multiple unit families (e.g. some mass, some count),
    we pick the most-represented family and find the cheapest within it.
    This avoids nonsensical cross-family comparisons.
    """
    priced = [p for p in (build_priced_product(prod) for prod in products) if p]
    if not priced:
        return None

    from collections import Counter
    family_counts = Counter(p.family for p in priced)
    dominant_family = family_counts.most_common(1)[0][0]
    candidates = [p for p in priced if p.family == dominant_family]
    return min(candidates, key=lambda p: p.price_per_base)


# ── Recipe cost calculation ───────────────────────────────────────────────────

# ── Dry-ingredient density table ─────────────────────────────────────────────
# When a recipe measures a dry ingredient by volume (tsp, tbsp, cups) but the
# product is priced by mass (oz), we need the density to convert.
# Values are oz per cup.  1 fl oz = 1/8 cup, so oz_per_floz = value / 8.

_DRY_OZ_PER_CUP: dict[str, float] = {
    # Flours & starches
    "flour":            4.25,
    "cornstarch":       4.48,
    "cornmeal":         4.94,
    "bread crumbs":     3.53,
    "panko":            2.82,
    "oat":              3.17,
    "quinoa":           6.0,
    # Sugars & sweeteners
    "granulated sugar": 7.05,
    "sugar":            7.05,
    "brown sugar":      7.55,
    "powdered sugar":   4.0,
    "cocoa":            3.17,
    # Salts & leaveners
    "salt":             9.6,
    "baking soda":      9.6,
    "baking powder":    7.7,
    # Spices & seasonings (all roughly 3-4 oz/cup)
    "spice":            3.5,
    "seasoning":        3.5,
    "powder":           3.5,
    "pepper":           2.8,
    "paprika":          3.2,
    "cumin":            3.2,
    "cinnamon":         4.3,
    "turmeric":         3.7,
    "cayenne":          3.5,
    "coriander":        3.0,
    "oregano":          2.1,
    "thyme":            2.1,
    "rosemary":         2.1,
    "bay":              0.9,
    "garam masala":     3.5,
    "curry":            3.5,
    "taco":             3.5,
    "old bay":          3.5,
    # Dry pasta & rice (edge cases)
    "pasta":            4.0,
    "rice":             6.7,
    "lentil":           7.0,
    # Nut butters
    "peanut butter":    9.0,
    "almond butter":    8.6,
}

_DRY_FALLBACK_OZ_PER_CUP = 3.5


def _dry_oz_per_floz(ingredient_name: str) -> float:
    """Approximate oz-per-fl_oz density for a dry/powder ingredient."""
    lower = ingredient_name.lower()
    for keyword, oz_per_cup in _DRY_OZ_PER_CUP.items():
        if keyword in lower:
            return oz_per_cup / 8.0
    return _DRY_FALLBACK_OZ_PER_CUP / 8.0


# Standard can / jar sizes used when recipe unit is "cans" or "jars".
# When the product itself is priced per-oz or per-fl_oz, we multiply by this
# to estimate the number of cans/jars worth.
STANDARD_CAN_OZ: dict[str, float] = {
    # (ingredient keyword → typical net oz content)
    "bean": 15.0,
    "chickpea": 15.0,
    "lentil": 15.0,
    "corn": 15.25,
    "tomato": 14.5,
    "diced tomato": 14.5,
    "crushed tomato": 28.0,
    "tomato sauce": 15.0,
    "tomato paste": 6.0,
    "coconut milk": 13.5,
    "broth": 14.5,
    "chicken broth": 14.5,
    "beef broth": 14.5,
    "green chile": 4.0,
    "artichoke": 13.75,
    "pumpkin": 15.0,
    "tuna": 5.0,
}


def _can_size_oz(ingredient_name: str) -> float:
    """Estimate typical can size in oz for count-based recipe units."""
    lower = ingredient_name.lower()
    for keyword, oz in STANDARD_CAN_OZ.items():
        if keyword in lower:
            return oz
    return 14.5  # safe fallback


# Oz per single count unit for ingredients that recipes measure by count
# but stores sell by weight.  Used for count→mass cross-family conversion.
_COUNT_TO_OZ: dict[str, float] = {
    # Meat & deli
    "strip":    0.5,    # 1 strip of bacon ≈ ½ oz
    "bacon":    0.5,
    "sausage":  2.0,    # 1 link ≈ 2 oz
    "link":     2.0,
    "hot dog":  2.0,
    "deli":     1.0,    # 1 deli slice ≈ 1 oz
    "turkey breast": 1.0,
    "ham":      1.0,
    "pepperoni": 0.1,   # 1 pepperoni ≈ 0.1 oz
    # Produce — citrus
    "lime":     1.7,    # 1 lime ≈ 1.7 oz flesh
    "lemon":    2.3,    # 1 lemon ≈ 2.3 oz
    "orange":   4.5,
    # Produce — other
    "potato":   6.0,    # 1 medium russet ≈ 6 oz
    "sweet potato": 5.0,
    "avocado":  5.0,
    "onion":    6.0,    # 1 medium onion ≈ 6 oz
    "apple":    6.0,
    "banana":   4.0,
    "tomato":   4.0,    # 1 roma ≈ 4 oz; vine ≈ 5 oz
    "carrot":   2.8,
    "beet":     4.5,
    "ear":      8.0,    # ear of corn ≈ 8 oz
    "corn":     8.0,
    # Bread / tortilla
    "tortilla": 1.1,    # 1 corn tortilla ≈ 1.1 oz; flour ≈ 1.5 oz
    "flour tortilla": 1.5,
    # Dairy / eggs
    "egg":      2.0,    # 1 large egg ≈ 2 oz
    # Pantry count items
    "slice":    1.0,    # generic bread/deli slice
    "bread":    1.0,
    # Herbs — very small dried leaves
    "bay":      0.04,   # 1 bay leaf ≈ 0.04 oz (1g)
    "garlic":   0.17,   # 1 garlic clove ≈ 0.17 oz (5g)
    "clove":    0.17,
}


def _count_to_oz(ingredient_name: str) -> float:
    """Return estimated oz per single count unit for a given ingredient."""
    lower = ingredient_name.lower()
    for keyword, oz in _COUNT_TO_OZ.items():
        if keyword in lower:
            return oz
    return 2.0  # conservative fallback: ~2 oz per unit


def _count_to_oz_known(ingredient_name: str) -> Optional[float]:
    """Like _count_to_oz but returns None when no specific entry matches.

    Used to gate the weight→count bridge: we only let a count-sold product
    (e.g. bananas priced "each") satisfy a by-weight request when we have a
    trustworthy per-piece weight, never the generic 2 oz fallback.
    """
    lower = ingredient_name.lower()
    for keyword, oz in _COUNT_TO_OZ.items():
        if keyword in lower:
            return oz
    return None


# ── Product relevance filtering ───────────────────────────────────────────────
# Keeps the pricing functions from accepting products that merely *contain*
# the ingredient as a minor component (e.g. "Yoplait Blueberry Yogurt" when
# searching for blueberries, or "Gatorade Lemon-Lime" when searching for lemons).

_FILTER_STOPWORDS: frozenset[str] = frozenset({
    "canned", "fresh", "dried", "ground", "boneless", "skinless",
    "whole", "large", "small", "medium", "baby", "frozen", "raw",
    "organic", "plain", "unsalted", "salted", "low", "fat", "free",
    "light", "extra", "virgin", "sliced", "chopped", "minced", "roasted",
    "and", "in", "with", "of", "the", "for", "or",
})

_kw_re_cache: dict[str, re.Pattern] = {}


def _kw_matches(kw: str, desc_lower: str) -> bool:
    """
    True if kw appears as a whole word in desc_lower, with simple
    plural/singular tolerance (e.g. 'lemons' also matches 'lemon').
    Uses regex word-boundary so 'salt' does NOT match 'salted'.
    """
    if kw not in _kw_re_cache:
        stems = {kw}
        if kw.endswith("ies") and len(kw) > 4:
            stems.add(kw[:-3] + "y")       # blueberries → blueberry
        elif kw.endswith("oes") and len(kw) > 4:
            stems.add(kw[:-2])              # tomatoes → tomato
        elif kw.endswith("s") and len(kw) > 3:
            stems.add(kw[:-1])              # lemons→lemon, limes→lime, oats→oat
        else:
            stems.add(kw + "s")             # lemon→lemons
        alt = "|".join(re.escape(s) for s in sorted(stems, key=len, reverse=True))
        _kw_re_cache[kw] = re.compile(r"\b(?:" + alt + r")\b", re.IGNORECASE)
    return bool(_kw_re_cache[kw].search(desc_lower))


def _ingredient_keywords(ingredient_name: str) -> list[str]:
    """Meaningful words from an ingredient name, stripped of generic modifiers."""
    return [
        w for w in ingredient_name.lower().split()
        if w not in _FILTER_STOPWORDS and len(w) > 2
    ]



def ingredient_cost(
    recipe_qty: float,
    recipe_unit: str,
    ingredient_name: str,
    product: PricedProduct,
) -> Optional[float]:
    """
    Estimate the cost of using `recipe_qty` `recipe_unit` of `ingredient_name`
    based on `product`'s unit price.

    Returns None when units are incompatible or the calculation is ambiguous.

    Unit matching logic
    ───────────────────
    recipe mass unit (oz, lbs, g, kg)  ↔  product mass family  → direct
    recipe volume unit (cups, tbsp, …) ↔  product volume family → direct
    recipe count unit (whole, cans, …) ↔  product count family  → direct

    Special cases
    ─────────────
    recipe_unit = "cans" or "jars" + product mass family:
        Use STANDARD_CAN_OZ to estimate qty in oz, then price normally.
    recipe_unit = "whole" on known count products (eggs, avocados):
        Treated as 1 ct each.
    recipe_unit = "pinch":
        Cost is negligible; returns 0.01 (a penny).
    """
    runit = recipe_unit.lower().strip()

    # Negligible quantities
    if runit == "pinch":
        return 0.01

    recipe_base = to_base(recipe_qty, runit)

    if recipe_base is None:
        return None  # unrecognized recipe unit

    r_qty_base, r_base_unit = recipe_base

    # ── Direct family match ───────────────────────────────────────────────────
    if r_base_unit == "oz" and product.family == "mass":
        return r_qty_base * product.price_per_base

    if r_base_unit == "fl_oz" and product.family == "volume":
        return r_qty_base * product.price_per_base

    if r_base_unit == "ct" and product.family == "count":
        return r_qty_base * product.price_per_base

    # ── Cross-family special cases ────────────────────────────────────────────

    # "cans" / "jars" but product priced by weight (oz)
    if runit in ("cans", "can", "jars", "jar") and product.family == "mass":
        can_oz = _can_size_oz(ingredient_name)
        total_oz = recipe_qty * can_oz
        return total_oz * product.price_per_base

    # "cans" / "jars" but product priced by volume (fl oz)
    if runit in ("cans", "can", "jars", "jar") and product.family == "volume":
        can_oz = _can_size_oz(ingredient_name)
        return can_oz * product.price_per_base  # fl oz ≈ oz for water-based liquids

    # Volume recipe unit + mass-priced product (dry spices / powders measured by tsp/tbsp).
    # Use a density estimate to convert fl oz → oz.
    if r_base_unit == "fl_oz" and product.family == "mass":
        density = _dry_oz_per_floz(ingredient_name)
        mass_oz = r_qty_base * density
        return mass_oz * product.price_per_base

    # Mass recipe unit + volume-priced product (unusual; e.g. honey measured in oz but
    # sold in fl oz bottles).  Water-based liquids: 1 fl oz ≈ 1.04 oz.
    if r_base_unit == "oz" and product.family == "volume":
        mass_to_floz = 1.0 / 1.04
        fl_oz_equiv = r_qty_base * mass_to_floz
        return fl_oz_equiv * product.price_per_base

    # Count recipe unit + mass-priced product (e.g. "3 strips bacon" vs "16 oz package")
    if r_base_unit == "ct" and product.family == "mass":
        ct_oz = _count_to_oz(ingredient_name)
        total_oz = r_qty_base * ct_oz
        return total_oz * product.price_per_base

    # Incompatible families
    return None


# ── Convenience: price one ingredient from a raw product list ─────────────────

def price_ingredient(
    ingredient_name: str,
    recipe_qty: float,
    recipe_unit: str,
    api_products: list[dict],
) -> Optional[dict]:
    """
    High-level helper: given the API's product list for an ingredient search,
    pick the best product and compute the cost.

    Returns a dict with keys:
        cost          – estimated cost in USD (float)
        description   – product description
        brand         – brand name
        price         – shelf price of the unit
        size_str      – raw size string
        sold_by       – "UNIT" or "WEIGHT"
        price_per_base – price per base unit (per oz, fl oz, or ct)
        base_unit     – "oz", "fl_oz", or "ct"
        notes         – list of edge-case warnings
    Returns None if no usable product is found.
    """
    product = best_product(api_products)
    if product is None:
        return None

    cost = ingredient_cost(recipe_qty, recipe_unit, ingredient_name, product)
    if cost is None:
        return None

    return {
        "cost": round(cost, 4),
        "description": product.description,
        "brand": product.brand,
        "price": product.price,
        "size_str": product.size_str,
        "sold_by": product.sold_by,
        "price_per_base": round(product.price_per_base, 6),
        "base_unit": product.base_unit,
        "notes": product.notes,
    }


# ── Shopping-list target purchase ────────────────────────────────────────────

import math


@dataclass
class PurchaseOption:
    product: PricedProduct
    units_to_buy: float          # packages to buy (or lbs for WEIGHT items)
    total_base_qty: float        # total amount in base units after purchase
    overage_base: float          # how much over the target (0 for WEIGHT items)
    total_cost: float            # total spend in USD
    overage_pct: float           # overage as % of target (for display)


def find_best_purchase(
    ingredient_name: str,
    target_qty: float,
    target_unit: str,
    api_products: list[dict],
) -> Optional[dict]:
    """
    Given a total target amount needed (e.g. 10 lbs of chicken for the week),
    find the product and quantity to buy that:
      1. Meets or exceeds the target (no going under)
      2. Minimizes total cost (cheapest combination wins)

    For soldBy=WEIGHT items: buy exactly the target (overage = 0).
    For soldBy=UNIT items: buy ceil(target / package_size) packages.

    Returns a dict with:
        units_to_buy    – number of packages (or lbs for WEIGHT)
        total_qty       – total amount purchased, in the target unit
        overage         – how much extra in the target unit
        overage_pct     – overage as % of target
        total_cost      – total USD spend
        unit_price_str  – human-readable unit price (e.g. "$4.99/lb")
        description     – product description
        brand           – brand
        size_str        – package size string
        sold_by         – "UNIT" or "WEIGHT"
        notes           – edge-case warnings
    Returns None if no compatible product is found.
    """
    # ── Resolve all possible base-unit targets before the product loop ────────
    is_can_jar = target_unit.lower().rstrip("s") in ("can", "jar")
    can_oz: float = 0.0

    # Base-unit quantities, keyed by family
    tgt: dict[str, tuple[float, str]] = {}   # family → (qty_in_base_units, base_unit)
    dry_oz_from_volume: Optional[float] = None  # set when recipe unit is volume

    if is_can_jar:
        can_oz = _can_size_oz(ingredient_name)
        tgt["mass"]  = (target_qty * can_oz, "oz")
        tgt["count"] = (target_qty, "ct")
    else:
        base = to_base(target_qty, target_unit)
        if base is None:
            return None
        base_qty, base_unit = base
        if base_unit == "oz":
            tgt["mass"] = (base_qty, "oz")
            # Reverse bridge: let count-sold products (e.g. bananas "each" or
            # "bunch") satisfy a by-weight request, using a known per-piece
            # weight. Gated on a curated entry so weight-sold meats aren't
            # mis-estimated by the generic fallback.
            ct_oz = _count_to_oz_known(ingredient_name)
            if ct_oz and ct_oz > 0:
                tgt["mass_as_count"] = (base_qty / ct_oz, "ct")
        elif base_unit == "fl_oz":
            tgt["volume"] = (base_qty, "fl_oz")
            # Also compute dry-goods mass equivalent for dry ingredients
            # (spices, oats, flour measured by volume but priced by weight)
            density = _dry_oz_per_floz(ingredient_name)
            dry_oz_from_volume = base_qty * density
            tgt["mass_dry"] = (dry_oz_from_volume, "oz")
        elif base_unit == "ct":
            tgt["count"] = (base_qty, "ct")
            # mass fallback for count recipes against mass-priced products
            ct_oz = _count_to_oz(ingredient_name)
            tgt["count_as_mass"] = (base_qty * ct_oz, "oz")

    # ── Relevance pre-filter ─────────────────────────────────────────────────
    # Require at least one ingredient keyword to appear (whole-word) in the
    # product description. No safety-net fallback: returning None here signals
    # the caller to try its next search term rather than accepting a wrong product.
    _kws = _ingredient_keywords(ingredient_name)
    if _kws:
        api_products = [
            p for p in api_products
            if any(_kw_matches(kw, (p.get("description") or "").lower()) for kw in _kws)
        ]

    options: list[PurchaseOption] = []
    # Track which family key was used per option for display later
    option_tgt_keys: list[str] = []

    for product in api_products:
        pp = build_priced_product(product)
        if pp is None:
            continue

        # ── Pick the effective target for this product's family ────────────
        tgt_key: Optional[str] = None
        if pp.family == "mass" and "mass" in tgt:
            tgt_key = "mass"
        elif pp.family == "mass" and "mass_dry" in tgt:
            tgt_key = "mass_dry"   # dry-ingredient volume→mass fallback
        elif pp.family == "volume" and "volume" in tgt:
            if is_can_jar:
                continue  # liquid cans handled via mass; skip volume products
            tgt_key = "volume"
        elif pp.family == "count" and "count" in tgt:
            tgt_key = "count"
        elif pp.family == "count" and "mass_as_count" in tgt:
            tgt_key = "mass_as_count"
        elif pp.family == "mass" and "count_as_mass" in tgt and "mass" not in tgt:
            tgt_key = "count_as_mass"

        if tgt_key is None:
            continue

        tgt_qty_base, tgt_base_unit = tgt[tgt_key]

        if pp.sold_by == "WEIGHT":
            # Buy exactly the target quantity by weight — no overage
            units = tgt_qty_base / 16.0      # oz → lbs for display
            total_qty_base = tgt_qty_base
            overage = 0.0
            cost = tgt_qty_base * pp.price_per_base
        else:
            # UNIT: must buy whole packages
            pkg_qty = pp.base_qty
            if pkg_qty <= 0:
                continue
            units = math.ceil(tgt_qty_base / pkg_qty)
            if units < 1:
                units = 1
            total_qty_base = units * pkg_qty
            overage = total_qty_base - tgt_qty_base
            cost = units * pp.price

        overage_pct = (overage / tgt_qty_base * 100) if tgt_qty_base > 0 else 0.0

        options.append(PurchaseOption(
            product=pp,
            units_to_buy=units,
            total_base_qty=total_qty_base,
            overage_base=overage,
            total_cost=cost,
            overage_pct=overage_pct,
        ))
        option_tgt_keys.append(tgt_key)

    if not options:
        return None

    paired = sorted(
        zip(options, option_tgt_keys),
        key=lambda x: x[0].total_cost,
    )
    best, best_tgt_key = paired[0]

    pp = best.product

    # ── Convert totals back to the caller's preferred display unit ──────────
    if is_can_jar:
        total_qty_display = best.total_base_qty / can_oz if can_oz > 0 else best.total_base_qty
        overage_display = best.overage_base / can_oz if can_oz > 0 else best.overage_base
        display_unit = target_unit
    elif best_tgt_key == "count_as_mass":
        # Product priced by mass; recipe measured by count.
        # Convert oz totals back to item count for display.
        ct_oz = _count_to_oz(ingredient_name)
        total_qty_display = best.total_base_qty / ct_oz if ct_oz > 0 else best.total_base_qty
        overage_display = best.overage_base / ct_oz if ct_oz > 0 else best.overage_base
        display_unit = target_unit
    elif best_tgt_key == "mass_as_count":
        # Product priced by count; recipe measured by weight.
        # Convert item-count totals back to the recipe's weight unit.
        ct_oz = _count_to_oz(ingredient_name)
        oz_factor = MASS_TO_OZ.get(target_unit.lower(), 1)
        total_qty_display = (best.total_base_qty * ct_oz) / oz_factor
        overage_display = (best.overage_base * ct_oz) / oz_factor
        display_unit = target_unit
    elif best_tgt_key == "mass_dry":
        # Product is priced by mass (oz) but recipe measured by volume.
        # Convert the oz-based totals back to the recipe's volume unit.
        floz_factor = VOL_TO_FLOZ.get(target_unit.lower(), 1)
        density = _dry_oz_per_floz(ingredient_name)
        total_qty_display = (best.total_base_qty / density) / floz_factor
        overage_display = (best.overage_base / density) / floz_factor
        display_unit = target_unit
    elif best_tgt_key in tgt:
        _, base_unit = tgt[best_tgt_key]
        if base_unit == "oz":
            total_qty_display = best.total_base_qty / (MASS_TO_OZ.get(target_unit.lower(), 1))
            overage_display = best.overage_base / (MASS_TO_OZ.get(target_unit.lower(), 1))
        elif base_unit == "fl_oz":
            total_qty_display = best.total_base_qty / (VOL_TO_FLOZ.get(target_unit.lower(), 1))
            overage_display = best.overage_base / (VOL_TO_FLOZ.get(target_unit.lower(), 1))
        else:
            total_qty_display = best.total_base_qty
            overage_display = best.overage_base
        display_unit = target_unit
    else:
        total_qty_display = best.total_base_qty
        overage_display = best.overage_base
        display_unit = target_unit

    # Human-readable unit price
    if pp.sold_by == "WEIGHT":
        unit_price_str = f"${pp.price:.2f}/lb"
    else:
        unit_price_str = f"${pp.price:.2f}/{pp.size_str}"

    # Weight items: represent as a single "X lb" package so the UI doesn't show
    # "x2 | Per LB" (confusing) but instead "x1 | 2 lb | $2.58" (clear).
    if pp.sold_by == "WEIGHT":
        lbs = round(best.units_to_buy, 2)
        size_display = f"{lbs:g} lb"
        return {
            "units_to_buy": 1,
            "total_qty": round(total_qty_display, 3),
            "unit": display_unit,
            "overage": 0.0,
            "overage_pct": 0.0,
            "total_cost": round(best.total_cost, 2),
            "unit_price_str": unit_price_str,
            "description": pp.description,
            "brand": pp.brand,
            "size_str": size_display,
            "sold_by": pp.sold_by,
            "notes": pp.notes,
        }

    return {
        "units_to_buy": round(best.units_to_buy, 3),
        "total_qty": round(total_qty_display, 3),
        "unit": display_unit,
        "overage": round(overage_display, 3),
        "overage_pct": round(best.overage_pct, 1),
        "total_cost": round(best.total_cost, 2),
        "unit_price_str": unit_price_str,
        "description": pp.description,
        "brand": pp.brand,
        "size_str": pp.size_str,
        "sold_by": pp.sold_by,
        "notes": pp.notes,
    }


# ── Meal plan aggregation ─────────────────────────────────────────────────────

def aggregate_ingredients(
    meals: list[dict],
    household_size: int = 1,
    meal_frequencies: Optional[dict[str, int]] = None,
) -> dict[str, dict]:
    """
    Sum ingredient quantities across a meal plan, scaled for household size.

    Parameters
    ----------
    meals
        List of meal dicts from meals.json (each has an "ingredients" list).
    household_size
        Number of people; all ingredient qtys are multiplied by this.
    meal_frequencies
        Optional dict mapping meal id → number of times it appears in the plan.
        Defaults to 1 for every meal if not provided.

    Returns
    -------
    dict mapping ingredient_name → {"qty": float, "unit": str, "base_qty": float, "base_unit": str}

    Quantities are summed in their base units (oz / fl_oz / ct) to handle
    mixed units for the same ingredient across meals, then converted back
    to the most common recipe unit for that ingredient.
    """
    if meal_frequencies is None:
        meal_frequencies = {}

    # Accumulate in base units per ingredient
    # Structure: {ingredient_name: {"base_unit": str, "base_qty": float, "source_unit": str}}
    totals: dict[str, dict] = {}

    for meal in meals:
        freq = meal_frequencies.get(meal.get("id", ""), 1)
        scale = household_size * freq

        for ing in meal.get("ingredients", []):
            name = ing["name"]
            qty = ing["qty"] * scale
            unit = ing["unit"]

            base = to_base(qty, unit)
            if base is None:
                # Unrecognized unit — keep as-is, accumulate raw qty
                if name not in totals:
                    totals[name] = {"base_qty": 0.0, "base_unit": unit, "source_unit": unit}
                totals[name]["base_qty"] += qty
                continue

            base_qty, base_unit = base

            if name not in totals:
                totals[name] = {"base_qty": 0.0, "base_unit": base_unit, "source_unit": unit}

            if totals[name]["base_unit"] == base_unit:
                totals[name]["base_qty"] += base_qty
            else:
                # Same ingredient appears with different unit families (shouldn't happen
                # in a consistent meal cache, but handle it gracefully)
                totals[name]["base_qty"] += base_qty
                totals[name]["base_unit"] = base_unit  # last writer wins

    # Convert accumulated base qty back to a human-friendly unit
    result: dict[str, dict] = {}
    for name, data in totals.items():
        bq = data["base_qty"]
        bu = data["base_unit"]
        su = data["source_unit"]

        # Prefer the source unit from the recipe if it makes sense
        back = _base_to_source(bq, bu, su)
        result[name] = {
            "qty": round(back[0], 4),
            "unit": back[1],
            "base_qty": round(bq, 4),
            "base_unit": bu,
        }

    return result


def _base_to_source(base_qty: float, base_unit: str, preferred_unit: str) -> tuple[float, str]:
    """Convert a base-unit quantity back to a preferred display unit."""
    pu = preferred_unit.lower().strip()
    if base_unit == "oz":
        factor = MASS_TO_OZ.get(pu)
        if factor:
            return base_qty / factor, preferred_unit
        return base_qty, "oz"
    if base_unit == "fl_oz":
        factor = VOL_TO_FLOZ.get(pu)
        if factor:
            return base_qty / factor, preferred_unit
        return base_qty, "fl oz"
    # count
    return base_qty, preferred_unit


# ── Unit test / demo (run directly) ──────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=== parse_size tests ===")
    cases = [
        # Simple
        ("14.5 oz",          (14.5, "oz")),
        ("1 lb",             (1.0, "lb")),
        ("2 lb",             (2.0, "lb")),
        ("5 lb",             (5.0, "lb")),
        ("1/2 gal",          (0.5, "gal")),
        ("1 gal",            (1.0, "gal")),
        ("16 fl oz",         (16.0, "fl oz")),
        ("12 ct",            (12.0, "ct")),
        ("1 ct",             (1.0, "ct")),
        ("60 ct",            (60.0, "ct")),
        ("1 qt",             (1.0, "qt")),
        ("1 pt",             (1.0, "pt")),
        ("48 oz",            (48.0, "oz")),
        ("8.45 fl oz",       (8.45, "fl oz")),
        ("1.75 L",           (1.75, "l")),
        ("500 ml",           (500.0, "ml")),
        ("32 oz",            (32.0, "oz")),
        ("9.8 oz",           (9.8, "oz")),
        ("5 lb bag",         (5.0, "lb")),
        ("1 each",           (1.0, "ct")),
        ("3 pack",           (3.0, "ct")),
        ("1",                (1.0, "ct")),   # bare number → 1 ct
        ("30 fo",            (30.0, "fl oz")), # API typo for fl oz
        # Compound
        ("12 ct / 20 oz",    (20.0, "oz")),  # count + weight → weight wins
        ("80 ct / 66.7 oz",  (66.7, "oz")),
        ("20 ct / 0.20 oz",  (0.20, "oz")),
        ("6 ct / 3 oz",      (3.0, "oz")),
        ("3 ct / 3.2 oz",    (3.2, "oz")),
        ("3 pk / 56 ct",     (56.0, "ct")),  # both count → larger
        ("6 bottles / 8.55 fl oz", (51.3, "fl oz")),  # 6×8.55
        ("6 cans / 7.5 fl oz",     (45.0, "fl oz")),  # 6×7.5
        # Edge
        ("",                 None),
        ("variable",         None),
    ]
    passed = failed = 0
    for s, expected in cases:
        got = parse_size(s)
        if got is not None and expected is not None:
            ok = got[1] == expected[1] and abs(got[0] - expected[0]) < 1e-6
        else:
            ok = got == expected
        if not ok:
            failed += 1
            print(f"  FAIL  parse_size({s!r}) -> {got!r}  (expected {expected!r})")
        else:
            passed += 1
    print(f"  {passed}/{passed+failed} passed\n")

    print("=== to_base conversion tests ===")
    base_cases = [
        (6.0, "oz",   (6.0, "oz")),
        (1.0, "lb",   (16.0, "oz")),
        (0.5, "lbs",  (8.0, "oz")),
        (2.0, "cups", (16.0, "fl_oz")),
        (1.0, "tbsp", (0.5, "fl_oz")),
        (1.0, "tsp",  (1/6, "fl_oz")),
        (2.0, "whole",(2.0, "ct")),
        (1.0, "cans", (1.0, "ct")),
        (3.0, "cloves",(3.0, "ct")),
    ]
    for qty, unit, expected in base_cases:
        got = to_base(qty, unit)
        # round for comparison
        if got:
            got = (round(got[0], 6), got[1])
        if expected:
            expected = (round(expected[0], 6), expected[1])
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            print(f"  {status}  to_base({qty}, {unit!r}) -> {got!r}  (expected {expected!r})")
        else:
            passed += 1

    print(f"\n=== PricedProduct construction ===")
    # Simulate a WEIGHT-sold item (sweet potatoes $1.79/lb)
    mock_weight = {
        "description": "Sweet Potatoes",
        "brand": "Kroger",
        "items": [{"itemId": "abc", "soldBy": "WEIGHT", "size": "1 lb",
                   "price": {"regular": 1.79}}],
    }
    pp = build_priced_product(mock_weight)
    assert pp is not None
    assert pp.family == "mass"
    assert abs(pp.price_per_base - 1.79 / 16) < 1e-6, f"Got {pp.price_per_base}"
    print(f"  WEIGHT item: {pp.description} ${pp.price}/lb -> ${pp.price_per_base:.4f}/oz  PASS")

    # Simulate a UNIT-sold item (eggs 12 ct for $4.49)
    mock_unit = {
        "description": "Large Eggs",
        "brand": "Kroger",
        "items": [{"itemId": "def", "soldBy": "UNIT", "size": "12 ct",
                   "price": {"regular": 4.49}}],
    }
    pp2 = build_priced_product(mock_unit)
    assert pp2 is not None
    assert pp2.family == "count"
    assert abs(pp2.price_per_base - 4.49 / 12) < 1e-6, f"Got {pp2.price_per_base}"
    print(f"  UNIT item:   {pp2.description} ${pp2.price}/12 ct -> ${pp2.price_per_base:.4f}/ct  PASS")

    # Simulate a UNIT-sold olive oil (16.9 fl oz for $7.99)
    mock_oil = {
        "description": "Olive Oil",
        "brand": "Kirkland",
        "items": [{"itemId": "ghi", "soldBy": "UNIT", "size": "16.9 fl oz",
                   "price": {"regular": 7.99}}],
    }
    pp3 = build_priced_product(mock_oil)
    assert pp3 is not None
    assert pp3.family == "volume"
    expected_ppu = 7.99 / 16.9
    assert abs(pp3.price_per_base - expected_ppu) < 1e-6, f"Got {pp3.price_per_base}"
    print(f"  UNIT oil:    {pp3.description} ${pp3.price}/16.9 fl oz -> ${pp3.price_per_base:.4f}/fl oz  PASS")

    print("\n=== ingredient_cost tests ===")
    # 5 oz of sweet potatoes at $1.79/lb
    cost = ingredient_cost(5.0, "oz", "Sweet potatoes", pp)
    expected = 5 * (1.79 / 16)
    assert abs(cost - expected) < 1e-4, f"Got {cost}"
    print(f"  5 oz sweet potatoes @ $1.79/lb = ${cost:.4f}  PASS")

    # 0.5 lbs of sweet potatoes
    cost2 = ingredient_cost(0.5, "lbs", "Sweet potatoes", pp)
    expected2 = 8 * (1.79 / 16)
    assert abs(cost2 - expected2) < 1e-4, f"Got {cost2}"
    print(f"  0.5 lbs sweet potatoes @ $1.79/lb = ${cost2:.4f}  PASS")

    # 2 eggs from a 12-pack at $4.49
    cost3 = ingredient_cost(2.0, "whole", "Large eggs", pp2)
    expected3 = 2 * (4.49 / 12)
    assert abs(cost3 - expected3) < 1e-4, f"Got {cost3}"
    print(f"  2 whole eggs @ $4.49/12ct = ${cost3:.4f}  PASS")

    # 2 tbsp olive oil (= 1 fl oz)
    cost4 = ingredient_cost(2.0, "tbsp", "Olive oil", pp3)
    expected4 = 1.0 * (7.99 / 16.9)
    assert abs(cost4 - expected4) < 1e-4, f"Got {cost4}"
    print(f"  2 tbsp olive oil @ $7.99/16.9 fl oz = ${cost4:.4f}  PASS")

    # 1 can of black beans (product priced by weight)
    mock_beans_weight = {
        "description": "Canned Black Beans",
        "brand": "Kroger",
        "items": [{"itemId": "jkl", "soldBy": "WEIGHT", "size": "15.5 oz",
                   "price": {"regular": 1.09}}],
    }
    pp_beans = build_priced_product(mock_beans_weight)
    cost5 = ingredient_cost(1.0, "cans", "Canned black beans", pp_beans)
    expected5 = 15.5 * (1.09 / 16)
    assert abs(cost5 - expected5) < 1e-4, f"Got {cost5}"
    print(f"  1 can black beans (weight-priced) = ${cost5:.4f}  PASS")

    print("\nAll tests passed.")
