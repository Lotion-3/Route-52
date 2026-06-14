# BasketBuddy Meal Cache Reference

This file is the source of truth for adding meals to the cache. All meals **must** use only the 199 approved ingredients listed below. When adding a new meal, copy the schema template, fill in all fields, and append it to `meals.json` in this directory.

---

## Meal Schema

Each meal entry in `meals.json` follows this structure:

```json
{
  "id": "unique-kebab-case-id",
  "name": "Meal Name",
  "meal_type": "Breakfast | Lunch | Dinner | Snack",
  "cuisine": "American | Italian | Mexican",
  "calories": 500,
  "cook_time_minutes": 25,
  "dietary_tags": [],
  "allergen_tags": [],
  "health_tags": [],
  "ingredients": [
    { "name": "exact ingredient name from the 199 list", "qty": 1.0, "unit": "unit" }
  ],
  "instructions": [
    "Step 1 text.",
    "Step 2 text."
  ]
}
```

### Field Reference

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Unique, kebab-case. e.g. `"chicken-stir-fry"` |
| `name` | string | Display name shown to user |
| `meal_type` | string | `Breakfast`, `Lunch`, `Dinner`, or `Snack` |
| `cuisine` | string | `American`, `Italian`, or `Mexican` |
| `calories` | int | Per serving (for 1 person) |
| `cook_time_minutes` | int | Total active + passive time |
| `dietary_tags` | string[] | See tags list below |
| `allergen_tags` | string[] | Allergens **present** in this meal |
| `health_tags` | string[] | Conditions this meal is suitable for |
| `ingredients` | object[] | Use exact names from the 199 list |
| `instructions` | string[] | Ordered steps, written clearly |

### Dietary Tags (use these exact strings)
```
Vegetarian, Vegan, Pescatarian, Gluten-Free, Dairy-Free, Egg-Free,
No Beef, No Pork, No Lamb, No Poultry, No Seafood, No Red Meat,
Hindu (No Beef), Jain, Sattvic (No Onion & Garlic), Brahmin,
No Root Vegetables, No Underground Vegetables,
Halal, Kosher, Keto, Paleo, Whole30, Low-Carb, Low-Fat, Low-Sodium,
High-Protein, Nut-Free, Soy-Free, Sugar-Free, Low-FODMAP, Mediterranean, DASH Diet
```

### Allergen Tags (allergens PRESENT in the meal)
```
Milk / Dairy, Eggs, Fish, Shellfish, Tree Nuts, Peanuts,
Wheat / Gluten, Soy, Sesame, Mustard, Sulfites, Corn
```

### Health Tags (conditions this meal is SUITABLE for)
```
Diabetes-Friendly, Heart-Healthy, Low-Sodium, High-Protein,
Anti-Inflammatory, Gut-Friendly, Low-Cholesterol, Kidney-Friendly,
PCOS-Friendly, Thyroid-Friendly, Weight-Loss, High-Fiber
```

### Units to use
```
lbs, oz, g, kg,
cups, tbsp, tsp, ml, fl oz,
whole, cloves, slices, strips, pieces, fillets, links, cans, jars,
heads, bunches, stalks, sprigs, leaves, pinch
```

---

## Filtering Rules (how the system uses these tags)

- User selects **allergens** → exclude any meal whose `allergen_tags` contains that allergen
- User selects **dietary restrictions** → include only meals whose `dietary_tags` covers all selected restrictions
- User selects **health conditions** → prefer meals whose `health_tags` match; do not hard-exclude
- User selects **cuisine** → match `cuisine` field exactly
- User sets **calorie target** → filter meals within ±20% of `(daily_calories / meals_per_day)`
- User sets **max cook time** → exclude meals where `cook_time_minutes` exceeds it
- **Household size** → multiply all ingredient `qty` values at runtime; do not pre-scale in the cache

---

## The 199 Approved Ingredients

Only these ingredients may appear in the `ingredients` array of any meal. Use the exact name as written here.

### Produce — Vegetables
| # | Ingredient |
|---|------------|
| 1 | Yellow onions |
| 2 | Red onions |
| 3 | Green onions |
| 4 | Garlic bulb |
| 5 | Fresh ginger root |
| 6 | Baby spinach |
| 7 | Romaine lettuce |
| 8 | Iceberg lettuce |
| 9 | Kale |
| 10 | Broccoli |
| 11 | Cauliflower |
| 12 | Brussels sprouts |
| 13 | Green beans |
| 14 | Asparagus |
| 15 | Zucchini |
| 16 | Yellow squash |
| 17 | Red bell peppers |
| 18 | Green bell peppers |
| 19 | Jalapenos |
| 20 | Carrots |
| 21 | Celery |
| 22 | Cucumber |
| 23 | Vine tomatoes |
| 24 | Cherry tomatoes |
| 25 | Roma tomatoes |
| 26 | Russet potatoes |
| 27 | Sweet potatoes |
| 28 | Red potatoes |
| 29 | Corn on the cob |
| 30 | White mushrooms |
| 31 | Baby bella mushrooms |
| 32 | Cabbage green |
| 33 | Red cabbage |
| 34 | Bok choy |
| 35 | Snap peas |
| 36 | Baby carrots |
| 37 | Radishes |
| 38 | Beets |
| 39 | Butternut squash |
| 40 | Spaghetti squash |

### Produce — Fruits
| # | Ingredient |
|---|------------|
| 41 | Bananas |
| 42 | Gala apples |
| 43 | Lemons |
| 44 | Limes |
| 45 | Navel oranges |
| 46 | Strawberries |
| 47 | Blueberries |
| 48 | Red seedless grapes |
| 49 | Mangos |
| 50 | Fresh pineapple |
| 51 | Peaches |
| 52 | Raspberries |
| 53 | Avocados |
| 54 | Watermelon |
| 55 | Blackberries |

### Meat & Seafood
| # | Ingredient |
|---|------------|
| 56 | Boneless skinless chicken breast |
| 57 | Boneless skinless chicken thighs |
| 58 | Ground beef 80/20 |
| 59 | Ground turkey |
| 60 | Boneless pork chops |
| 61 | Pork tenderloin |
| 62 | Bacon |
| 63 | Italian sausage links |
| 64 | Breakfast sausage links |
| 65 | Beef stew meat |
| 66 | Sirloin steak |
| 67 | Salmon fillet |
| 68 | Tilapia fillet |
| 69 | Frozen shrimp medium |
| 70 | Canned tuna in water |
| 71 | Hot dogs |
| 72 | Deli turkey breast |
| 73 | Deli ham |
| 74 | Pepperoni |
| 75 | Ground pork |
| 76 | Beef short ribs |
| 77 | Ground lamb |
| 78 | Imitation crab meat |
| 79 | Rotisserie chicken |
| 80 | Chicken wings |

### Dairy & Eggs
| # | Ingredient |
|---|------------|
| 81 | Large eggs |
| 82 | Whole milk gallon |
| 83 | 2% milk gallon |
| 84 | Butter unsalted |
| 85 | Salted butter |
| 86 | Heavy whipping cream |
| 87 | Sour cream |
| 88 | Plain Greek yogurt |
| 89 | Cream cheese |
| 90 | Shredded mozzarella |
| 91 | Shredded cheddar |
| 92 | Parmesan cheese |
| 93 | Monterey jack cheese |
| 94 | Cottage cheese |
| 95 | Half and half |

### Bread & Bakery
| # | Ingredient |
|---|------------|
| 96 | White sandwich bread |
| 97 | Whole wheat bread |
| 98 | Flour tortillas large |
| 99 | Corn tortillas |
| 100 | Hamburger buns |

### Grains & Pasta
| # | Ingredient |
|---|------------|
| 101 | White rice long grain |
| 102 | Brown rice |
| 103 | Jasmine rice |
| 104 | Spaghetti pasta |
| 105 | Penne pasta |
| 106 | Elbow macaroni |
| 107 | Egg noodles |
| 108 | Lasagna noodles |
| 109 | Rolled oats |
| 110 | Panko bread crumbs |
| 111 | Plain bread crumbs |
| 112 | All purpose flour |
| 113 | Cornmeal |
| 114 | Quinoa |
| 115 | Ramen noodles |
| 116 | Orzo pasta |

### Canned & Jarred Goods
| # | Ingredient |
|---|------------|
| 117 | Canned diced tomatoes |
| 118 | Canned crushed tomatoes |
| 119 | Tomato paste |
| 120 | Tomato sauce |
| 121 | Canned black beans |
| 122 | Canned kidney beans |
| 123 | Canned chickpeas |
| 124 | Canned corn |
| 125 | Canned green beans |
| 126 | Canned coconut milk |
| 127 | Canned chicken broth |
| 128 | Canned beef broth |
| 129 | Canned diced green chiles |
| 130 | Refried beans |
| 131 | Canned pinto beans |
| 132 | Salsa jar |
| 133 | Marinara pasta sauce jar |
| 134 | Diced tomatoes with green chiles |
| 135 | Canned lentils |
| 136 | Artichoke hearts canned |
| 137 | Sun dried tomatoes jar |
| 138 | Roasted red peppers jar |
| 139 | Canned pumpkin |
| 140 | Chicken noodle soup can |
| 141 | Tomato soup can |

### Oils, Sauces & Condiments
| # | Ingredient |
|---|------------|
| 142 | Olive oil |
| 143 | Vegetable oil |
| 144 | Sesame oil |
| 145 | Soy sauce |
| 146 | Worcestershire sauce |
| 147 | Hot sauce |
| 148 | Ketchup |
| 149 | Yellow mustard |
| 150 | Dijon mustard |
| 151 | Mayonnaise |
| 152 | Apple cider vinegar |
| 153 | White vinegar |
| 154 | Balsamic vinegar |
| 155 | Honey |
| 156 | Maple syrup |
| 157 | Fish sauce |
| 158 | Oyster sauce |
| 159 | Hoisin sauce |
| 160 | Sriracha |
| 161 | Ranch dressing |

### Baking & Dry Goods
| # | Ingredient |
|---|------------|
| 162 | Granulated sugar |
| 163 | Brown sugar |
| 164 | Powdered sugar |
| 165 | Baking soda |
| 166 | Baking powder |
| 167 | Salt |
| 168 | Black pepper |
| 169 | Chicken bouillon cubes |
| 170 | Beef bouillon cubes |
| 171 | Cornstarch |
| 172 | Vanilla extract |
| 173 | Cocoa powder |
| 174 | Chocolate chips |
| 175 | Peanut butter |
| 176 | Almond butter |
| 177 | Strawberry jam |
| 178 | Active dry yeast |
| 179 | Red lentils dried |

### Spices & Seasonings
| # | Ingredient |
|---|------------|
| 180 | Garlic powder |
| 181 | Onion powder |
| 182 | Cumin ground |
| 183 | Chili powder |
| 184 | Smoked paprika |
| 185 | Cayenne pepper |
| 186 | Italian seasoning |
| 187 | Oregano dried |
| 188 | Thyme dried |
| 189 | Rosemary dried |
| 190 | Bay leaves |
| 191 | Cinnamon ground |
| 192 | Curry powder |
| 193 | Turmeric ground |
| 194 | Red pepper flakes |
| 195 | Garam masala |
| 196 | Taco seasoning |
| 197 | Everything bagel seasoning |
| 198 | Old bay seasoning |
| 199 | Coriander ground |

---

## Example Meal Entry

```json
{
  "id": "garlic-butter-salmon",
  "name": "Garlic Butter Salmon",
  "meal_type": "Dinner",
  "cuisine": "American",
  "calories": 480,
  "cook_time_minutes": 20,
  "dietary_tags": ["No Beef", "No Pork", "Pescatarian", "Gluten-Free", "Low-Carb", "Keto"],
  "allergen_tags": ["Fish", "Milk / Dairy"],
  "health_tags": ["Heart-Healthy", "High-Protein", "Diabetes-Friendly"],
  "ingredients": [
    { "name": "Salmon fillet", "qty": 6, "unit": "oz" },
    { "name": "Butter unsalted", "qty": 2, "unit": "tbsp" },
    { "name": "Garlic bulb", "qty": 3, "unit": "cloves" },
    { "name": "Lemons", "qty": 0.5, "unit": "whole" },
    { "name": "Baby spinach", "qty": 2, "unit": "cups" },
    { "name": "Olive oil", "qty": 1, "unit": "tbsp" },
    { "name": "Salt", "qty": 0.5, "unit": "tsp" },
    { "name": "Black pepper", "qty": 0.25, "unit": "tsp" },
    { "name": "Smoked paprika", "qty": 0.5, "unit": "tsp" }
  ],
  "instructions": [
    "Pat salmon dry and season both sides with salt, black pepper, and smoked paprika.",
    "Heat olive oil in a skillet over medium-high heat until shimmering.",
    "Place salmon skin-side up and sear for 4 minutes without moving.",
    "Flip salmon, add butter and minced garlic to the pan, and baste for 3–4 minutes until cooked through.",
    "Squeeze lemon over the fillet, remove from heat.",
    "In the same pan, wilt the baby spinach in the remaining butter for 1–2 minutes.",
    "Serve salmon over spinach."
  ]
}
```

---

## Adding a New Meal — Checklist

- [ ] `id` is unique and kebab-case
- [ ] All ingredient names match the 199 list exactly (copy-paste, don't retype)
- [ ] `qty` values are for **1 person** — the system scales by household size at runtime
- [ ] `allergen_tags` lists every allergen **present**, not ones to avoid
- [ ] `dietary_tags` only applied when the meal genuinely qualifies
- [ ] `calories` is realistic for the portion size
- [ ] At least 3 clear instruction steps
- [ ] Entry is valid JSON (no trailing commas, quotes around all strings)
