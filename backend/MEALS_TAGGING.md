# Meal Tagging Reference

Working reference for tagging entries in `meals.json` (and the Kaggle
recipe import at `recipes_raw.jsonl`). Read this before writing or reviewing
any tagging code — it's the source of truth for which tags exist, what they
mean, and how each one is supposed to be derived.

## Why this exists

`meal_planner.py`'s `_filter_meals()` treats `allergen_tags` as a **hard
safety exclusion** and `dietary_tags` as a **hard requirement** (every
requested restriction must be present). `health_tags` are currently
descriptive only — nothing in the codebase filters on them yet. That means
allergen tags in particular have to be right, not just present. A missing
allergen tag isn't a cosmetic gap, it's a wrong answer to "can I eat this."

## Schema (unchanged)

```json
{
  "id": "kebab-case-slug",
  "name": "Display Name",
  "meal_type": "Breakfast | Lunch | Dinner | Snack",
  "cuisine": "American | Italian | Mexican | ...",
  "calories": 380,
  "cook_time_minutes": 10,
  "dietary_tags": ["Vegetarian", "Gluten-Free"],
  "allergen_tags": ["Eggs", "Milk / Dairy"],
  "health_tags": ["High-Protein"],
  "ingredients": [{"name": "...", "qty": 1, "unit": "..."}],
  "instructions": ["..."]
}
```

## Derivation-method legend

Every tag below is marked with how it should be produced:

- **KEYWORD** — scan `ingredients[].name` (and recipe `name`/`description`
  where useful) against a keyword list. Free, deterministic, runs on all
  83k+ rows in seconds. This is the bulk of the mechanical tagging pass.
- **NUTRITION** — threshold on Food.com's `nutrition` object
  (`calories, total_fat_pdv, sugar_pdv, sodium_pdv, protein_pdv,
  saturated_fat_pdv, carbohydrates_pdv` — all as %DV except calories).
  Free, deterministic, same speed as KEYWORD.
  **Caveat**: it's a per-recipe %DV, not per-serving-normalized against a
  fixed calorie target — treat thresholds as directional, not clinical.
- **LLM** — needs actual semantic/nutritional judgment Food.com's 7-field
  nutrition array can't give us (no cholesterol, no potassium, no purine
  content, no fiber grams, etc.). Do **not** fake these with a keyword
  guess — leave the tag off until the planned LLM pass runs. A missing tag
  is safer than a wrong one for anything health/allergy-adjacent.
- **MANUAL** — inherently unverifiable from ingredient text alone (e.g.
  certification-based tags). Approximate at best; say so wherever surfaced.

---

## Allergens (`allergen_tags`) — safety-critical, KEYWORD-derived

Covers the FDA "Big 9" (all present) plus the EU's additional majors, since
the ask was full coverage. Bias keyword lists toward **over-flagging**: a
false positive just means an ingredient gets treated as containing an
allergen it might not (annoying); a false negative means someone with a real
allergy gets served it (harmful). When in doubt, tag it.

| Tag | Trigger keywords (non-exhaustive, extend as you find gaps) |
|---|---|
| `Milk / Dairy` | milk, cream, butter, cheese, yogurt, whey, casein, ghee, buttermilk, custard |
| `Eggs` | egg, mayonnaise, meringue, albumin |
| `Fish` | fish, anchovy, salmon, tuna, cod, tilapia, bass, trout, sardine, fish sauce, worcestershire (often anchovy-based) |
| `Shellfish` | shrimp, crab, lobster, prawn, crawfish |
| `Molluscs` | clam, mussel, oyster, scallop, squid, calamari, octopus, snail, escargot |
| `Tree Nuts` | almond, walnut, pecan, cashew, pistachio, hazelnut, macadamia, brazil nut, pine nut, nut butter (non-peanut), marzipan, nutella, praline |
| `Peanuts` | peanut, groundnut |
| `Wheat / Gluten` | wheat, flour (unless specified gluten-free), bread, pasta, barley, rye, malt, semolina, couscous, panko, breadcrumb, soy sauce (traditional, contains wheat) |
| `Soy` | soy, tofu, edamame, miso, tempeh, tamari, soybean |
| `Sesame` | sesame, tahini, halva |
| `Corn` | corn, cornstarch, corn syrup, cornmeal, masa, hominy |
| `Mustard` | mustard (seed/powder/prepared) |
| `Sulfites` | wine, dried apricot, raisin, dried fruit (sulfite-treated), molasses |
| `Celery` | celery, celeriac, celery salt/seed |
| `Coconut` | coconut, coconut milk/oil/cream — **note**: medically distinct from tree-nut allergy; keep it a separate tag, don't fold into `Tree Nuts` |
| `Lupin` | lupin, lupini bean — rare in US recipes but cheap to catch |

## Dietary preferences (`dietary_tags`)

| Tag | Method | Rule |
|---|---|---|
| `Vegan` | KEYWORD | no meat/poultry/fish/seafood AND no `Milk / Dairy`/`Eggs` allergen hits AND no honey |
| `Vegetarian` | KEYWORD | no meat/poultry/fish/seafood (dairy/eggs OK) |
| `Pescatarian` | KEYWORD | no meat/poultry, fish/seafood OK |
| `No Beef` / `No Pork` / `No Lamb` / `No Poultry` / `No Seafood` | KEYWORD | absence of that protein's keyword set |
| `No Red Meat` | KEYWORD | = `No Beef` ∩ `No Lamb` (∩ pork if treating pork as red meat — pick one convention and note it in the tagger) |
| `Gluten-Free` | KEYWORD | no `Wheat / Gluten` allergen hit (also check oats — cross-contamination caveat, tag anyway) |
| `Dairy-Free` | KEYWORD | no `Milk / Dairy` allergen hit |
| `Egg-Free` | KEYWORD | no `Eggs` allergen hit |
| `Keto` | NUTRITION | carbohydrates_pdv low relative to fat/protein — directional threshold, tune on real distribution before trusting it |
| `Low-Carb` | NUTRITION | carbohydrates_pdv below threshold |
| `Low-Fat` | NUTRITION | total_fat_pdv below threshold |
| `Halal` | MANUAL | approximate only: no pork, no alcohol, no gelatin (source-ambiguous). **Cannot verify slaughter method from ingredient text** — never present this as certified-halal, only "halal-compatible ingredients" |
| `Kosher` | MANUAL | approximate only: no pork/shellfish, no meat+dairy in the same dish. Same certification caveat as Halal |
| `Paleo` | KEYWORD | no grains, no legumes, no dairy, no refined sugar |
| `Low-FODMAP` | KEYWORD | exclude high-FODMAP triggers: garlic, onion, wheat, most legumes, specific fruits (apple, pear, watermelon) — this is the most failure-prone KEYWORD rule here since FODMAP status is dose- and prep-dependent; treat as a rough filter, not medical advice |

## Health tags (`health_tags`)

| Tag | Method | Rule / Note |
|---|---|---|
| `High-Protein` | NUTRITION | protein_pdv above threshold |
| `Low-Carb` | NUTRITION | (duplicate of dietary tag — same rule, kept in both lists since users filter dietary and health separately in spirit even though only dietary_tags are wired into filtering today) |
| `Low-Sodium` | NUTRITION | sodium_pdv below threshold — genuinely useful, cheap, add it |
| `Low-Sugar` | NUTRITION | sugar_pdv below threshold |
| `High-Fiber` | LLM | Food.com's nutrition array has no fiber field — can't derive mechanically |
| `Heart-Healthy` | LLM | needs judgment across sat-fat + sodium + fiber + ingredient quality together, not one threshold |
| `Diabetes-Friendly` | LLM | needs glycemic-load judgment, not just sugar %DV |
| `Mediterranean` | LLM | a pattern (olive oil, fish, vegetables, whole grains, limited red meat), not a threshold |
| `Anti-Inflammatory` | LLM | ingredient-pattern judgment (turmeric, fatty fish, leafy greens vs. fried/processed) |
| `Gut-Friendly` | LLM | fermented-food/fiber pattern judgment |
| `PCOS-Friendly` | LLM | compound judgment (low glycemic + anti-inflammatory + adequate protein) |
| `Weight-Loss` | LLM | calorie-density + protein/fiber judgment relative to a target, not absolute |
| `Kidney/Renal-Friendly` | LLM (needs external data) | requires potassium/phosphorus data Food.com doesn't provide at all — lowest priority, likely needs a different data source entirely if ever pursued |
| `Pregnancy-Safe` | KEYWORD (partial) | can mechanically flag *unsafe* patterns (raw fish/sushi, deli meat, unpasteurized cheese, high-mercury fish, alcohol) — but "safe" is the absence of red flags, not a positive guarantee. Frame as a warning filter, not a certification |

---

## Tagging pipeline (two passes)

1. **Mechanical pass (now, free, all rows)**: run every KEYWORD and NUTRITION
   rule above across `recipes_raw.jsonl`. This alone gets every allergen,
   every protein-exclusion dietary tag, Gluten/Dairy/Egg-Free, and a few
   NUTRITION-based health tags (`High-Protein`, `Low-Sodium`, `Low-Sugar`).
2. **LLM pass (later, per the existing plan)**: everything marked LLM above.
   Batch it, cache the output — same reasoning as the original "cache ahead
   of time" plan for full recipe generation. Don't run this per-request.

## Known limitations (say this if it ever reaches a user-facing surface)

- Allergen tagging is keyword-based best-effort, not a medical guarantee.
  Hidden/derivative sources (an unlisted anchovy in a sauce, a shared
  fryer, cross-contamination) can't be caught from ingredient text alone.
- Halal/Kosher tags describe ingredient composition only, not
  certification or preparation method.
- `Low-FODMAP`/`Pregnancy-Safe` are directional filters, not clinical or
  medical clearance.
