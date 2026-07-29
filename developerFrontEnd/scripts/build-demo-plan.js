#!/usr/bin/env node

/**
 * One-off generator for developerFrontEnd's static demo fixture.
 *
 * Picks 8 random meals from the REAL backend/meals.json, spreads them across
 * a few days, fabricates a plausible 3-store shopping route + prices + a home
 * address, and writes the result to developerFrontEnd/mocks/demoMealPlan.ts
 * (plus the address pool used by the demo address-autocomplete to
 * developerFrontEnd/mocks/demoAddresses.ts).
 *
 * Not part of the running app — re-run any time to roll a fresh random set:
 *   node developerFrontEnd/scripts/build-demo-plan.js
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..'); // repo root
const MEALS_PATH = path.join(ROOT, 'backend', 'meals.json');
const MEAL_PLAN_OUT = path.join(__dirname, '..', 'mocks', 'demoMealPlan.ts');
const ADDRESSES_OUT = path.join(__dirname, '..', 'mocks', 'demoAddresses.ts');

const meals = JSON.parse(fs.readFileSync(MEALS_PATH, 'utf8'));

// ── 1. Pick 8 random meals ───────────────────────────────────────────────────
function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
}

const picked = shuffle(meals).slice(0, 8);

// ── 2. Spread across sequential days, ~3/day, round-robin by meal type so a
//      single day doesn't end up with three breakfasts ──────────────────────
const TYPE_ORDER = { Breakfast: 0, Lunch: 1, Dinner: 2, Snack: 3 };
const sortedByType = picked
    .slice()
    .sort((a, b) => (TYPE_ORDER[a.meal_type] ?? 9) - (TYPE_ORDER[b.meal_type] ?? 9));

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const PER_DAY = 3;
const numDays = Math.ceil(sortedByType.length / PER_DAY);
const days = Array.from({ length: numDays }, () => []);
sortedByType.forEach((meal, i) => days[i % numDays].push(meal));
days.forEach((dayMeals) =>
    dayMeals.sort((a, b) => (TYPE_ORDER[a.meal_type] ?? 9) - (TYPE_ORDER[b.meal_type] ?? 9))
);

// ── 3. Pantry staples the "shopper" already has at home ──────────────────────
const AT_HOME_NAMES = new Set([
    'salt', 'black pepper', 'pepper', 'olive oil', 'vegetable oil', 'cooking spray',
    'garlic powder', 'onion powder', 'paprika', 'cinnamon', 'sugar', 'flour',
    'baking powder', 'baking soda', 'vanilla extract',
]);
const isAtHome = (name) => AT_HOME_NAMES.has(name.trim().toLowerCase());

// ── 4. Category buckets, mirroring the keyword logic already used in
//      results.tsx / GroupedCart so the demo groups look the same way the
//      real shopping list would ───────────────────────────────────────────────
const CATEGORY_KEYWORDS = {
    Produce: ['tomato', 'onion', 'potato', 'carrot', 'pepper', 'apple', 'banana', 'lettuce', 'spinach', 'avocado', 'lemon', 'lime', 'cucumber', 'garlic', 'mushroom', 'broccoli', 'berr', 'fruit', 'mango', 'corn tortilla', 'scallion', 'cilantro', 'herb'],
    Meat: ['chicken', 'beef', 'meat', 'pork', 'turkey', 'bacon', 'sausage', 'shrimp', 'fish', 'salmon', 'tuna'],
    Dairy: ['milk', 'cheese', 'yogurt', 'egg', 'cream', 'butter'],
    Frozen: ['frozen', 'ice cream'],
    Pantry: ['rice', 'pasta', 'bread', 'oil', 'salt', 'oat', 'flour', 'sugar', 'sauce', 'spice', 'bean', 'tortilla', 'stock', 'broth', 'vinegar', 'honey', 'syrup', 'crumb', 'quinoa', 'cumin', 'oregano', 'seasoning', 'paprika'],
};

function categoryFor(name) {
    const n = name.toLowerCase();
    for (const [cat, words] of Object.entries(CATEGORY_KEYWORDS)) {
        if (words.some((w) => n.includes(w))) return cat;
    }
    return 'Other';
}

const STORE_FOR_CATEGORY = {
    Meat: 'Meijer',
    Dairy: 'Meijer',
    Produce: 'Aldi',
    Frozen: 'Aldi',
    Pantry: 'Target',
    Other: 'Target',
};

const STORE_INFO = {
    Meijer: { address: '5350 E 86th St, Indianapolis, IN 46250', coordinates: { lat: 39.8968, lng: -86.1133 } },
    Aldi: { address: '3902 N Illinois St, Indianapolis, IN 46208', coordinates: { lat: 39.8109, lng: -86.1614 } },
    Target: { address: '8210 Craig St, Indianapolis, IN 46250', coordinates: { lat: 39.8712, lng: -86.1329 } },
};
const STORE_ROUTE_ORDER = ['Meijer', 'Aldi', 'Target'];

// ── 5. Plausible-but-fabricated pricing ──────────────────────────────────────
const KNOWN_PRICES = {
    'large eggs': 3.49, 'eggs': 3.49,
    'boneless skinless chicken breast': 6.49, 'chicken breast': 6.49, 'chicken thighs': 5.49,
    'ground beef': 5.99, 'ground turkey': 5.49,
    'whole milk': 3.79, 'milk': 3.79, 'whole milk gallon': 3.79,
    'shredded cheddar': 3.29, 'shredded mozzarella': 3.29, 'parmesan cheese': 4.49,
    'butter unsalted': 4.29, 'butter': 4.29, 'greek yogurt': 4.99, 'plain yogurt': 3.99,
    'bacon': 5.49, 'salmon fillet': 8.99, 'shrimp': 7.99,
};

function hash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
    return h;
}

function priceInRange(name, lo, hi) {
    const frac = (hash(name) % 1000) / 1000;
    return Math.round((lo + frac * (hi - lo)) * 100) / 100;
}

function unitPriceFor(name, unit) {
    const key = name.trim().toLowerCase();
    if (KNOWN_PRICES[key] !== undefined) return KNOWN_PRICES[key];
    const u = unit.trim().toLowerCase();
    if (['lb', 'lbs', 'pound', 'pounds'].includes(u)) return priceInRange(name, 3.5, 7.5);
    if (['tsp', 'tbsp', 'pinch'].includes(u)) return priceInRange(name, 1.99, 3.99);
    if (['clove', 'cloves'].includes(u)) return priceInRange(name, 0.59, 1.29);
    if (['whole', 'ct', 'each'].includes(u)) return priceInRange(name, 0.59, 2.49);
    if (['cups', 'cup'].includes(u)) return priceInRange(name, 2.49, 5.49);
    if (['slices', 'strips'].includes(u)) return priceInRange(name, 2.49, 4.99);
    return priceInRange(name, 1.99, 4.99);
}

function sizeStrFor(unit) {
    const u = unit.trim().toLowerCase();
    if (['lb', 'lbs', 'pound', 'pounds'].includes(u)) return '1 lb';
    if (['tsp', 'tbsp', 'pinch'].includes(u)) return '2.5 oz';
    if (['clove', 'cloves'].includes(u)) return '3 oz';
    if (['whole', 'ct', 'each'].includes(u)) return '6 ct';
    if (['cups', 'cup'].includes(u)) return '32 oz';
    if (['slices'].includes(u)) return '20 ct';
    if (['strips'].includes(u)) return '12 oz';
    return '1 unit';
}

function titleCase(name) {
    return name.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

// ── 6. Build meal_plan (verbatim recipe content, priced ingredients) ────────
const ingredientOccurrences = new Map(); // lower name -> count across all 8 meals

const meal_plan = [];
days.forEach((dayMeals, dayIdx) => {
    const dayName = DAY_NAMES[dayIdx % DAY_NAMES.length];
    dayMeals.forEach((meal) => {
        const ingredients = meal.ingredients.map((ing) => {
            if (isAtHome(ing.name)) {
                return { name: ing.name, qty: ing.qty, unit: ing.unit };
            }
            const key = ing.name.trim().toLowerCase();
            ingredientOccurrences.set(key, (ingredientOccurrences.get(key) || 0) + 1);
            const price = unitPriceFor(ing.name, ing.unit);
            return { name: ing.name, qty: ing.qty, unit: ing.unit, price };
        });
        meal_plan.push({
            day: dayName,
            day_index: dayIdx,
            meal_type: meal.meal_type,
            name: meal.name,
            calories: meal.calories,
            cook_time: `${meal.cook_time_minutes} minutes`,
            cook_time_minutes: meal.cook_time_minutes,
            cuisine: meal.cuisine,
            ingredients,
            instructions: meal.instructions,
        });
    });
});

// ── 7. "Used from Home" list — dedup pantry staples actually used ───────────
const atHomeMap = new Map();
picked.forEach((meal) => {
    meal.ingredients.forEach((ing) => {
        if (isAtHome(ing.name)) {
            const key = ing.name.trim().toLowerCase();
            if (!atHomeMap.has(key)) atHomeMap.set(key, { name: ing.name, qty: ing.qty, unit: ing.unit });
        }
    });
});
const at_home_ingredients = Array.from(atHomeMap.values());

// ── 8. Shopping list — every purchasable ingredient, grouped into 3 stores ──
const storeItems = { Meijer: [], Aldi: [], Target: [] };
for (const [key, count] of ingredientOccurrences.entries()) {
    // Find one original-cased name for this ingredient (first match wins).
    let name = key;
    outer: for (const meal of picked) {
        for (const ing of meal.ingredients) {
            if (ing.name.trim().toLowerCase() === key) { name = ing.name; break outer; }
        }
    }
    let unit = 'whole';
    outer2: for (const meal of picked) {
        for (const ing of meal.ingredients) {
            if (ing.name.trim().toLowerCase() === key) { unit = ing.unit; break outer2; }
        }
    }

    const category = categoryFor(name);
    const store = STORE_FOR_CATEGORY[category] || 'Target';
    const unitPrice = unitPriceFor(name, unit);
    const unitsToBuy = Math.min(3, count); // a package per recipe that needs it, capped
    const price = Math.round(unitPrice * unitsToBuy * 100) / 100;

    storeItems[store].push({
        name,
        qty: unitsToBuy,
        price,
        product_name: titleCase(name),
        size_str: sizeStrFor(unit),
        units_to_buy: unitsToBuy,
    });
}

// Attach one coupon to a protein item if one exists, else the first item found.
let couponTarget = null;
for (const store of STORE_ROUTE_ORDER) {
    const meatItem = storeItems[store].find((it) => categoryFor(it.name) === 'Meat');
    if (meatItem) { couponTarget = meatItem; break; }
}
if (!couponTarget) {
    for (const store of STORE_ROUTE_ORDER) {
        if (storeItems[store].length > 0) { couponTarget = storeItems[store][0]; break; }
    }
}
if (couponTarget) {
    const savings = Math.round(Math.min(2.5, couponTarget.price * 0.25) * 100) / 100;
    couponTarget.original_price = couponTarget.price;
    couponTarget.coupon = {
        type: 'digital',
        label: `$${savings.toFixed(2)} off ${couponTarget.product_name}`,
        savings,
        image_url: 'https://example.com/coupons/demo.png',
        valid_to: '2026-08-31',
    };
}

const route = STORE_ROUTE_ORDER.filter((s) => storeItems[s].length > 0);
const shopping_list = route.map((store, idx) => {
    const info = STORE_INFO[store];
    const entry = {
        store,
        address: info.address,
        coordinates: info.coordinates,
        items: storeItems[store],
    };
    // Give the last store in the route a pricing note, to exercise that
    // render branch — mirrors how Costco-style estimated pricing looks today.
    if (idx === route.length - 1) {
        entry.estimated = true;
        entry.pricing_note = `Prices at this ${store} are typical in-store estimates; exact totals may vary slightly by location.`;
    }
    return entry;
});

// ── 9. Top-level totals ──────────────────────────────────────────────────────
const total_cost = Math.round(
    shopping_list.reduce((sum, s) => sum + s.items.reduce((si, it) => si + it.price, 0), 0) * 100
) / 100;
const budget = 150;
const cheapest_single_store_cost = Math.round(total_cost * 1.18 * 100) / 100;
const cheapestStore = shopping_list.reduce((a, b) => (b.items.length > a.items.length ? b : a), shopping_list[0]);
const total_time_minutes = 30 + route.length * 35;

const slowestMeal = meal_plan.reduce((a, b) => (b.cook_time_minutes > a.cook_time_minutes ? b : a), meal_plan[0]);
const warnings = [
    'Dietary restriction "Vegetarian" was PARTLY ENFORCED — this demo plan mixes vegetarian and non-vegetarian recipes for variety.',
    `Max cook time preference of 30 minutes was relaxed for 1 recipe (${slowestMeal.name}, ${slowestMeal.cook_time_minutes} min) to preserve meal variety.`,
];

// ── 10. A small pool of fabricated Indianapolis-area addresses. One is the
//        "home" address; all of them double as the demo autocomplete list. ──
const ADDRESS_POOL = [
    '4821 N Pennsylvania St, Indianapolis, IN 46205',
    '5350 E 86th St, Indianapolis, IN 46250',
    '3902 N Illinois St, Indianapolis, IN 46208',
    '8210 Craig St, Indianapolis, IN 46250',
    '620 N College Ave, Indianapolis, IN 46202',
    '7255 N Keystone Ave, Indianapolis, IN 46240',
];
const HOME_ADDRESS_COORDS = { lat: 39.8283, lng: -86.1480 }; // matches ADDRESS_POOL[0]

const plan = {
    meal_plan,
    route,
    total_cost,
    cheapest_single_store_cost,
    cheapest_single_store_name: cheapestStore.store,
    total_time_minutes,
    user_location: HOME_ADDRESS_COORDS,
    at_home_ingredients,
    warnings,
    budget,
    over_budget: total_cost > budget,
    shopping_list,
};

// ── 11. Write output files ───────────────────────────────────────────────────
const planHeader = `// AUTO-GENERATED by developerFrontEnd/scripts/build-demo-plan.js — do not hand-edit.
// Re-run \`node developerFrontEnd/scripts/build-demo-plan.js\` from the repo root
// to roll a fresh random set of 8 meals from backend/meals.json.
import type { ShoppingPlanResponse } from '@/services/api';

export const DEMO_MEAL_PLAN: ShoppingPlanResponse = `;
fs.mkdirSync(path.dirname(MEAL_PLAN_OUT), { recursive: true });
fs.writeFileSync(MEAL_PLAN_OUT, planHeader + JSON.stringify(plan, null, 2) + ';\n');

const addressesHeader = `// AUTO-GENERATED by developerFrontEnd/scripts/build-demo-plan.js — do not hand-edit.
// Fixed pool of fabricated addresses used by the demo /location autocomplete.
// ADDRESS_POOL[0] is the "home" address baked into demoMealPlan.ts's user_location.

export const DEMO_ADDRESS_POOL: string[] = `;
fs.writeFileSync(ADDRESSES_OUT, addressesHeader + JSON.stringify(ADDRESS_POOL, null, 2) + ';\n');

console.log(`Wrote ${MEAL_PLAN_OUT}`);
console.log(`Wrote ${ADDRESSES_OUT}`);
console.log(`Picked meals: ${picked.map((m) => m.name).join(', ')}`);
console.log(`Total cost: $${total_cost.toFixed(2)} across ${route.join(' -> ')}`);
