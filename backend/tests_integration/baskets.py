"""Shared basket fixtures. Names are chosen to exercise kroger_search_map's
term expansion (get_all_terms) the way real meal-plan ingredients do."""

# Small, fast basket for smoke tests.
SMOKE = {
    "Large Eggs": {"qty": 12, "unit": "whole"},
    "Milk": {"qty": 1, "unit": "gallon"},
    "Bananas": {"qty": 3, "unit": "whole"},
    "White Bread": {"qty": 1, "unit": "loaf"},
    "Cheddar Cheese": {"qty": 8, "unit": "oz"},
}

# Realistic full basket (~24 items across produce, dairy, meat, pantry).
FULL = {
    **SMOKE,
    "Chicken Breast": {"qty": 16, "unit": "oz"},
    "Ground Beef": {"qty": 16, "unit": "oz"},
    "White Rice": {"qty": 2, "unit": "lb"},
    "Spaghetti Pasta": {"qty": 1, "unit": "box"},
    "Marinara Sauce": {"qty": 1, "unit": "jar"},
    "Olive Oil": {"qty": 1, "unit": "bottle"},
    "Butter": {"qty": 1, "unit": "whole"},
    "Greek Yogurt": {"qty": 1, "unit": "whole"},
    "Baby Spinach": {"qty": 1, "unit": "bag"},
    "Broccoli": {"qty": 1, "unit": "whole"},
    "Carrots": {"qty": 1, "unit": "bag"},
    "Yellow Onions": {"qty": 2, "unit": "whole"},
    "Roma Tomatoes": {"qty": 4, "unit": "whole"},
    "Apples": {"qty": 4, "unit": "whole"},
    "Peanut Butter": {"qty": 1, "unit": "jar"},
    "Black Beans": {"qty": 1, "unit": "can"},
    "Russet Potatoes": {"qty": 5, "unit": "lb"},
    "Orange Juice": {"qty": 1, "unit": "whole"},
}

BASKETS = {"smoke": SMOKE, "full": FULL}
