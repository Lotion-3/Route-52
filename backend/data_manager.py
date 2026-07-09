import math
import random
import json
from typing import List, Dict, Any

# How many cooking-units fit in one typical retail package for each unit.
# Used to convert aggregated cooking-unit qty → number of packages to buy.
_PACKAGE_SIZE: Dict[str, float] = {
    "tsp": 100,   "teaspoon": 100,   "teaspoons": 100,
    "tbsp": 33,   "tablespoon": 33,  "tablespoons": 33,
    "cup": 2,     "cups": 2,
    "fl oz": 16,  "fluid oz": 16,
    "oz": 16,     "ounce": 16,       "ounces": 16,
    "lb": 2,      "lbs": 2,          "pound": 2,   "pounds": 2,
    "g": 500,     "gram": 500,       "grams": 500,
    "kg": 1,      "kilogram": 1,
    "ml": 500,    "milliliter": 500,
    "liter": 1,   "l": 1,
    "whole": 1,   "piece": 1,        "pieces": 1,
    "can": 1,     "cans": 1,
    "jar": 1,     "jars": 1,
    "bottle": 1,  "bottles": 1,
    "bag": 1,     "bags": 1,
    "box": 1,     "boxes": 1,
    "package": 1, "packages": 1,
    "slice": 20,  "slices": 20,
    "clove": 10,  "cloves": 10,
    "sprig": 5,   "sprigs": 5,
    "bunch": 1,   "bunches": 1,
    "stalk": 4,   "stalks": 4,
    "strip": 8,   "strips": 8,
    "link": 4,    "links": 4,
}

# Static base-price ranges (low, high) keyed by ingredient keywords.
# Checked in order; first match wins.
_PRICE_TABLE = [
    (["chicken", "turkey", "poultry"],                      (4.5,  9.0)),
    (["ground beef", "beef", "steak", "bison"],             (5.0, 12.0)),
    (["pork", "bacon", "ham", "sausage", "chorizo"],        (3.5,  8.0)),
    (["salmon", "tuna", "shrimp", "fish", "seafood",
      "tilapia", "cod", "halibut", "scallop"],              (5.0, 14.0)),
    (["egg"],                                               (2.5,  5.5)),
    (["milk", "cream", "half and half"],                    (2.5,  5.5)),
    (["cheese", "cheddar", "mozzarella", "parmesan",
      "feta", "brie", "gouda", "ricotta"],                  (3.5,  7.5)),
    (["butter", "ghee"],                                    (3.0,  6.0)),
    (["yogurt", "greek yogurt", "sour cream",
      "cottage cheese"],                                    (2.0,  5.0)),
    (["bread", "toast", "tortilla", "pita", "naan",
      "bagel", "bun", "roll"],                              (2.5,  5.0)),
    (["pasta", "noodle", "spaghetti", "penne",
      "linguine", "fettuccine", "macaroni"],                (1.0,  3.0)),
    (["rice", "quinoa", "oat", "barley", "couscous",
      "bulgur", "farro"],                                   (1.5,  4.5)),
    (["flour", "cornstarch", "cornmeal", "breadcrumb"],     (1.5,  3.5)),
    (["potato", "sweet potato", "yam"],                     (1.0,  3.5)),
    (["tomato paste", "tomato sauce", "crushed tomato",
      "diced tomato", "tomato"],                            (1.0,  3.5)),
    (["bean", "chickpea", "lentil", "pea",
      "edamame", "tofu", "tempeh"],                         (1.0,  3.5)),
    (["onion", "shallot", "leek", "scallion"],              (0.75, 2.5)),
    (["garlic"],                                            (0.75, 2.0)),
    (["bell pepper", "jalapeño", "serrano", "pepper"],      (0.75, 2.5)),
    (["carrot", "celery", "broccoli", "cauliflower",
      "zucchini", "eggplant", "asparagus", "artichoke"],    (1.0,  3.5)),
    (["spinach", "kale", "lettuce", "cabbage",
      "arugula", "chard", "collard"],                       (1.5,  4.0)),
    (["mushroom"],                                          (2.0,  5.0)),
    (["cucumber", "radish", "beet", "turnip"],              (0.75, 2.5)),
    (["apple", "pear", "peach", "plum", "apricot"],         (1.5,  4.0)),
    (["banana"],                                            (0.5,  2.0)),
    (["blueberry", "strawberry", "raspberry",
      "blackberry", "berry"],                               (2.5,  6.0)),
    (["avocado"],                                           (1.0,  3.0)),
    (["lemon", "lime", "orange", "grapefruit",
      "clementine", "mandarin"],                            (0.75, 2.5)),
    (["olive oil", "vegetable oil", "canola oil",
      "coconut oil", "avocado oil", "sesame oil"],          (4.0, 10.0)),
    (["salt", "pepper", "spice", "seasoning", "cumin",
      "paprika", "oregano", "thyme", "cinnamon", "bay",
      "turmeric", "cayenne", "coriander", "rosemary",
      "chili powder", "taco", "italian seasoning",
      "garlic powder", "onion powder"],                     (2.0,  5.5)),
    (["sugar", "brown sugar", "honey", "maple syrup",
      "agave", "molasses"],                                 (2.5,  6.0)),
    (["soy sauce", "fish sauce", "worcestershire",
      "hot sauce", "vinegar", "balsamic"],                  (2.5,  6.0)),
    (["mustard", "ketchup", "mayo", "mayonnaise",
      "ranch", "dressing", "salsa", "dijon"],               (2.0,  5.0)),
    (["broth", "stock"],                                    (2.0,  4.5)),
    (["coconut milk"],                                      (1.5,  3.5)),
    (["peanut butter", "almond butter", "tahini"],          (4.0,  8.0)),
    (["canned", "jar"],                                     (1.0,  3.5)),
    (["chocolate", "cocoa"],                                (2.5,  6.0)),
    (["wine", "beer", "alcohol"],                           (6.0, 15.0)),
]

_STORE_MULTIPLIERS = {
    "aldi":         0.82,
    "trader joe":   0.93,
    "kroger":       1.00,
    "king soopers": 1.00,
    "ralphs":       1.00,
    "harris teeter":1.05,
    "meijer":       0.97,
    "walmart":      0.88,

    "costco":       0.78,
    "target":       1.05,
    "publix":       1.08,
    "safeway":      1.03,
    "food 4 less":  0.85,
    "giant":        1.02,
    "stop & shop":  1.04,
}


def _base_price(item_name: str) -> float:
    lower = item_name.lower()
    for keywords, (lo, hi) in _PRICE_TABLE:
        if any(kw in lower for kw in keywords):
            return round(random.uniform(lo, hi), 2)
    return round(random.uniform(1.5, 5.0), 2)


def _packages_needed(qty: float, unit: str) -> int:
    """Convert a cooking-unit quantity into the number of retail packages to buy."""
    pkg_size = _PACKAGE_SIZE.get(unit.lower().strip(), 1)
    return max(1, math.ceil(qty / pkg_size))


def _store_multiplier(store_name: str) -> float:
    lower = store_name.lower()
    for key, mult in _STORE_MULTIPLIERS.items():
        if key in lower:
            return mult
    return 1.0


def generate_synthetic_market(
    ingredient_data: Dict[str, Dict[str, Any]],
    store_names: List[str],
) -> tuple:
    # Per-item: price per package and number of packages needed.
    # unit_price stored as total_purchase_cost / qty so that
    # optimizer's (unit_price × qty) gives the correct dollar total.
    item_meta: Dict[str, Dict] = {}
    shopping_list: List[Dict] = []

    for item_raw, meta in ingredient_data.items():
        name = item_raw.strip()
        qty = meta.get("qty", 1) or 1
        unit = meta.get("unit", "whole") or "whole"
        pkg_price = _base_price(name)
        pkgs = _packages_needed(qty, unit)
        # Store normalized unit_price so optimizer's (unit_price × qty) = total purchase cost
        item_meta[name] = {
            "pkg_price": pkg_price,
            "pkgs": pkgs,
            "qty": qty,
        }
        shopping_list.append({"name": name, "qty": qty})

    price_database: Dict[str, Dict[str, float]] = {}
    for store_raw in store_names:
        store = store_raw.strip()
        mult = _store_multiplier(store)
        price_database[store] = {}
        for name, m in item_meta.items():
            variance = random.uniform(0.95, 1.05)
            store_pkg_price = m["pkg_price"] * mult * variance
            store_total = store_pkg_price * m["pkgs"]
            price_database[store][name.lower().strip()] = round(store_total / m["qty"], 6)

    with open("market_data.json", "w") as f:
        json.dump(price_database, f, indent=4)

    print(f"[DataManager] Prices set for {len(item_meta)} items across {len(store_names)} stores.", flush=True)
    return price_database, [], shopping_list
