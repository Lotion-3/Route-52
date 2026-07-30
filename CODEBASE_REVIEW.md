# basketBuddy — Codebase Review & State

_Last updated: 2026-07-30_

Dense reference doc, not a narrative — written to minimize tokens spent
re-deriving things in a future session. Trust this over a code comment that
contradicts it (some comments are stale — noted below where that's known).

---

## Empirically-verified facts (do not re-derive)

- **Target is PerimeterX-protected, not Imperva.** Every comment in
  `target_pricing.py` says "Imperva" — that predates verification and is
  wrong. A real warm's cookie jar is `_px2/_px3/_pxhd/_pxvid/pxcts`, the same
  PerimeterX family as Walmart. The exception class `_ImpervaBlocked` is
  misnamed but was kept (too many call sites to rename for a label change).
  **Cookie to poll for on Target is `_px3`**, not `reese84` (`reese84` belongs
  to Coles — a different, now-deleted retailer module — and never appears in
  a real Target session).
- **Both chains' WAF returns HTTP 200 on a block**, not 403/429, for the HTML
  search page. Status code alone is useless there. The reliable signal:
  literal `px-captcha` in the response body (Walmart) — present in every
  blocked response tested, absent from every good one (confirmed via
  curl_cffi replay of a good session vs. a deliberately-weak one). Generic
  words ("captcha"/"blocked"/"human") appear in BOTH good and bad pages
  (the real page legitimately references PerimeterX) — not usable alone.
- Target's RedSky (JSON API) block shape differs from Walmart's HTML page:
  `403` + literal `"captchaRelativeURL"` in the JSON body.
- `__NEXT_DATA__` is server-rendered into the initial HTML — it does NOT fill
  in asynchronously. Whatever's in the DOM at `domcontentloaded` is final; a
  "wait longer after the page loads" fix would do nothing (already considered
  and rejected).
- **Request velocity from one IP is an independent block factor**, separate
  from session/cookie quality. Reproduced live: identical warm code run
  back-to-back with other test traffic from the same IP → blocked repeatedly;
  same code, clean isolated run → succeeded cleanly. Not currently captured as
  a variable anywhere (see Open TODOs).
- **Two navigations (home → search) are required, not just best practice.**
  A homepage-only warm gets a 0/N replay rate. A **direct-to-search-only**
  warm ALSO fails (tested) — mints a `_px3` cookie but returns an empty
  `__NEXT_DATA__` (0 chars vs. 908,266 in the working case). Referrer chain
  and navigation count both matter.
- **The proxy (`CLOAK_PROXY`) only ever backs the browser-warm step**
  (`kwargs["proxy"]` into `browser_gate.launch`). The curl_cffi REPLAY calls —
  the bulk of request volume — run unproxied, from whatever IP the process is
  on. **This was tested directly and found to be fine, not a gap** — see Open
  TODOs #1.
- **Target retired `redsky.target.com/redsky_aggregations/v1/web/plp_search_v2`
  (2026-07-28 discovery).** A real browser navigating `target.com/s?searchTerm=...`
  never calls it anymore — search results now come from
  `https://cdui-orchestrations.target.com/cdui_orchestrations/v1/pages/slp`.
  Calling the retired endpoint 403s with `captchaRelativeURL` regardless of
  cookie validity, proxy, or IP — confirmed by replaying a fresh, healthy
  cookie against it from the SAME browser session that minted it (in-page
  `fetch()`, Playwright's own `ctx.request`, AND external curl_cffi all 403).
  `target_pricing.py` migrated to the new endpoint (`_slp_url`/
  `_extract_slp_products`); `_to_kroger_format`/`_price_value` needed zero
  changes — the new response's `item.product_description.title`/
  `item.primary_brand.name`/`price.current_retail` fields are identical
  paths. New endpoint's required params are lighter than the old one:
  `zip`/`state`/`latitude`/`longitude`/`timezone` are all NOT required —
  `store_id`/`store_ids`/`scheduled_delivery_store_id` alone scope location.
  This was very likely why GitHub Actions' mint job kept failing (Target
  mint always failed; the old un-rewritten `mint_sessions.py` only tried
  Walmart+Target with no other chain to fall back on, and returned failure
  unless at least one succeeded).
- **Cross-IP cookie replay works, tested directly, not just assumed.**
  Minted a Target cookie locally (laptop, no proxy), saved it raw, and
  replayed it from a GitHub Actions runner (`.github/workflows/
  test-cookie-replay.yml` + `backend/test_cookie_replay.py`, workflow_dispatch
  only) — genuinely different IP, not just a different device on the same
  home network (confirmed: devices on the same home WiFi share one public
  IP via NAT, so "test on another laptop at home" is NOT a different-IP
  test). Result: 200 OK, real products, both a single request and a 100-item
  concurrent batch. So a cookie minted on one network is NOT bound to that
  network for replay purposes, at least in this one-off test.
- **A single static IP CAN get volume-flagged — chain-dependent, and it
  happened within one day.** Same home laptop IP: Target tolerated 8 repeated
  full-25-item-basket runs plus a 20-way and a 104-way concurrent burst with
  zero degradation. Walmart flipped from 7/7 clean warms to 100%-blocked
  (fast path AND the 5-attempt CloakBrowser-pool fallback, all IPs) within
  the same day, from ordinary testing volume — not even real multi-user
  scale. Two different WAF vendors, very different per-IP tolerance. Whether
  Walmart's block is a temporary cooldown or durable is unresolved (would
  need a retest days later, deliberately not done same-day to avoid
  compounding it).
- **A minted Target cookie survived at least 150 minutes with zero re-warm**
  (replayed unchanged at t+0/5/15/30/45/60/75/90/120/150min, one lightweight
  search each time, all succeeded) — well past the `TARGET_COOKIE_TTL`
  default of 3600s (60min) that `_load_http_session()`/`mint_sessions.py`'s
  skip-if-fresh logic currently assumes. That assumed TTL is conservative;
  never pushed to actual failure (test was stopped at 150min to mint a
  fresh, savable cookie instead — see below). Not yet re-verified after the
  2026-07-28 endpoint migration landed.
- **5 Target cookies minted 2026-07-28 all still worked 2026-07-29**
  (tested via `test_saved_target_cookies.py`). All returned 8 products,
  response times 0.3–1.7s. So Target cookies can survive at least ~24h,
  not just the 150min window tested earlier. Not tested to failure.
- **`saved_target_cookies.json` is now wired into production** (2026-07-30,
  `target_pricing.py`). `_ensure_http_session()` tries this pool FIRST —
  confirmed live at 27+ hours old during this session, dramatically past
  `TARGET_COOKIE_TTL`'s 3600s assumption — and only falls through to the
  Supabase/disk-cache/CloakBrowser-mint chain once every pool entry is
  individually confirmed dead (`_next_pool_session`, `_pool_idx`,
  `_session_source`). A block on a pool-sourced session just advances to the
  next pool cookie (no IP rotation, no re-mint cost); a working pool session
  is no longer dropped between requests (was previously dropped
  unconditionally every call via `price_all_target`'s `finally` block).
  `TARGET_COOKIE_POOL_FILE` env var overrides the pool path (`""` disables
  it).
- **New: `backend/build_target_store_directory.py`** (2026-07-30). RedSky's
  `nearby_stores_v1` (dynamic nearest-store lookup) was confirmed dead —
  403 + `captchaRelativeURL` via curl_cffi for ANY cookie, including zero
  cookies, for ANY postal code, even the cookie's own home location. Every
  Target pricing call was silently falling back to a hardcoded default store
  (Indianapolis) regardless of the requesting user's actual location. This
  script geocodes every store in Target's public sitemap
  (`target.com/sl/sitemap_0001.xml.gz`, ~2019 stores, no WAF exposure) by
  its URL slug via Nominatim, producing `target_store_directory.json`
  (`{store_id, slug, lat, lon}`). `target_pricing._resolve_store_id` now
  tries a local haversine nearest-neighbor lookup against this directory
  first (instant, zero network calls, zero WAF risk); the legacy
  `nearby_stores_v1` call is kept only as a fallback in case Target ever
  un-blocks it. Heuristic accuracy (slug-based, not exact street address)
  but a large improvement over "everyone gets Indianapolis."
- **Walmart PerimeterX cookie minting works locally via standalone script**
  (`mint_walmart_cookies.py`). Tested 2026-07-29: CloakBrowser warm produced
  39 cookies including `_px3`, with `__NEXT_DATA__` ≥ 1000 chars. This is the
  same warm logic as `walmart_pricing._warm_http_session()` but extracted into
  a reusable, configurable CLI tool. No proxy required for a clean mint from
  a home IP (though home-IP mint reliability fluctuates — see below).
- **Walmart's per-cookie concurrency limit is a hard, instant wall at exactly
  20 simultaneous requests — confirmed empirically, not a total-item-count or
  cumulative-volume limit** (2026-07-30, `test_walmart_concurrency_matrix.py`,
  8 trials across 8 fresh cookies). 20 concurrent always succeeded, including
  40 total items split across two 20-wide waves 12s apart, and 30 total items
  trickled through at concurrency 5. 21, 22, 23, 25, and 30 concurrent ALL
  failed completely and instantly — every request in the burst blocked,
  including the very first one submitted (not a gradual "queued tail"
  degradation). This resolved a real ambiguity: the user's own manual testing
  via `test-walmart-cookie-replay.yml` (`item_count` input) saw success at 20
  but failure at 31 — but that script hardcodes
  `ThreadPoolExecutor(max_workers=20)`, so `item_count=31` was secretly still
  only a 20-wide burst with 11 items queued behind it, conflating "item
  count" with "concurrency." The matrix script separates the two explicitly.
  **Side effect discovered**: deliberately repeating over-the-wall bursts
  (21-30 concurrent, several times in a few minutes) escalated into a
  longer-lived IP-level block — confirmed by testing a brand-new, never-used
  cookie, which failed from the same machine but worked immediately when
  replayed through a different (proxied) exit IP. Production must never
  intentionally cross the 20-wall, not just because that one burst fails, but
  because repeating it risks a broader penalty.
- **Walmart pricing has no accessible store-selection mechanism** (2026-07-30).
  Investigated the same way the Target `nearby_stores_v1` endpoint map was
  found (fetching a live page's embedded bootstrap data with a valid cookie):
  Walmart's `robots.txt` lists `sitemap_store_main.xml` → 4 shards (other/
  discount/supercenter/neighborhood, 4629 stores total,
  `walmart.com/store/<id>-<city>-<state>`), and individual store pages embed
  precise `geoPoint: {latitude, longitude}` in their `__NEXT_DATA__` — a
  store directory built the same way as Target's is feasible if ever needed.
  But overriding the `assortmentStoreId` cookie (present in some minted
  sessions, e.g. `"1601"`) to different real store IDs (3106 = San Antonio,
  1196 = New Roads LA) against the search endpoint produced **byte-for-byte
  identical product listings and order** every time, with no store-echo field
  anywhere in the response — confirming search is genuinely national as
  `_STORE_ID = "national"` already assumed, not just "unconfigured." Pricing
  accuracy is governed by whatever assortment Walmart's backend defaults a
  session to (not obviously geoip-driven either — a JP-exit-proxied mint
  still returned normal US-priced products).
- **`.minted_walmart_cookies.json` is now wired into production** (2026-07-30,
  `walmart_pricing.py`), mirroring Target's pool exactly:
  `_ensure_http_session()` tries the pool first (`_next_pool_session`,
  `_pool_idx`, `_session_source`), only falling through to the Supabase/
  disk-cache/CloakBrowser-mint chain once every pool entry is individually
  confirmed dead. A block on a pool-sourced session just advances the cursor
  (no IP rotation — confirmed the proxy pool only ever affects a future
  *browser warm*'s exit IP, and swapping pool cookies never triggers one); a
  working pool session is no longer dropped between requests.
  `WALMART_COOKIE_POOL_FILE` env var overrides the pool path (`""` disables
  it). `WALMART_HTTP_CONCURRENCY` default raised from 8 to 18 (a small safety
  margin below the confirmed-clean 20-wall, not the wall itself) per the
  concurrency finding above.

## Cookie properties — Target vs Walmart (2026-07-30)

Everything below is from direct empirical testing this session (mint →
replay from this machine, sometimes via `CLOAK_PROXY`), not assumption.
Consolidated here since the findings are scattered across dated bullets
above. **As of 2026-07-30 this machine's IP is fully blocked by Walmart**
(zero-cookie AND every pool cookie fail identically, direct — see
concurrency note below for why) — re-check with one lightweight request
before trusting anything Walmart-related live from here again; don't probe
it repeatedly in the meantime (see rolling-window note).

| Property | Target | Walmart |
|---|---|---|
| WAF vendor | PerimeterX (not Imperva, despite code comments) | PerimeterX |
| **Cookie TTL** | Alive at 27+ hours post-mint (5/5 pool cookies); dead by the ~30h mark (all 5 found dead in a later check). Far past the code's assumed 3600s. Not pinned down to an exact death time. | Not rigorously characterized (deprioritized this session). One data point: alive at mint, dead ~11.6h later. Assumed-safe TTL in code (3600s) is unverified either way. |
| **Concurrency limit** | Not isolated this session — only tested inside a 20-worker-capped harness (101/101 succeeded, but the harness itself caps at 20 concurrent, so the *true* per-cookie wall is still unknown for Target). | **Confirmed hard wall at exactly 20 simultaneous requests** (8 controlled trials, independently-configurable-concurrency harness). 20 always succeeds; 21/22/23/25/30 all fail *instantly and completely* — not a gradual/queued-tail failure. |
| **Cumulative request volume** (staying under the concurrency wall) | Not tested. | **Not a limiting factor** — 700 sequential/low-concurrency requests against one cookie, zero failures, as long as concurrency stayed ≤15. |
| **Over-limit → IP escalation risk** | Not tested (never intentionally exceeded a concurrency limit for Target). | **Confirmed real.** Repeating over-the-wall bursts (21-30 concurrent, several times in a few minutes) escalated into a durable IP-level block — a brand-new, never-used cookie failed from this IP afterward but worked immediately via a different exit. Production must never cross the wall, not just because that burst fails but because repeating it risks the broader penalty. Unknown whether continued *light* diagnostic requests also extend the block (rolling-window vs fixed-timer WAF behavior — not established either way; treat as a real risk and don't probe repeatedly). |
| **Cross-location / cross-store** | **Works.** An explicit `store_id` URL param is fully decoupled from cookie identity — any pool cookie prices any store (verified: LA/Chicago/Miami/Seattle/Carmel all returned genuinely different prices from the same cookies). Only the *dynamic* nearest-store lookup (`nearby_stores_v1`) is broken (403 even with zero cookies) — replaced with an offline sitemap+geocoded directory (1893 stores, `build_target_store_directory.py`). | **No mechanism found.** Overriding the `assortmentStoreId` cookie to different real store IDs produced byte-for-byte identical search results. Pricing is genuinely national (`_STORE_ID = "national"`), not just "unconfigured" — confirmed, not assumed. A store directory *could* be built the same way as Target's (Walmart's sitemap + per-store `geoPoint` lat/lon is even higher-precision than Target's), but there's currently nothing for it to feed into. |
| **Mint → replay reliability** | Not specifically stress-tested this session. | **~1/3 to 2/3 of mints don't survive a subsequent curl_cffi replay check**, despite passing `_warm_http_session()`'s own in-browser validation (captcha-marker + `__NEXT_DATA__` length check on the live page). "Mint succeeded" ≠ "cookie will actually replay" — always validate with a real post-mint replay call before trusting a freshly minted cookie, don't rely on the warm's own success signal alone. |
| **Portability across proxy/IP** | Confirmed: cookies aren't IP-pinned — work fine from a different IP than they were minted on. | Confirmed same way (a fresh cookie failed from our blocked local IP but worked immediately via a different exit) — also not IP-pinned. |
| **Production wiring status** | Pool-first (`saved_target_cookies.json`, 5 entries) wired into `target_pricing.py` — tried before any mint. | Pool-first (`.minted_walmart_cookies.json`, 12 entries) wired into `walmart_pricing.py` the same way. `WALMART_HTTP_CONCURRENCY` raised 8→18 (safety margin below the confirmed 20-wall). |

## Chain mechanism map (US chains)

| Chain | Mechanism | WAF vendor | Proxy/IP rotation | Categorized block detection |
|---|---|---|---|---|
| Walmart | pool cookie first (2026-07-30) → curl_cffi replay; browser warm only once pool exhausted | PerimeterX | yes on fallback path only — 5-IP no-repeat cap; pool blocks just advance the pool cursor, no rotation | yes: explicit/soft/transport |
| Target | pool cookie first (2026-07-30) → curl_cffi replay; browser warm only once pool exhausted | PerimeterX (not Imperva) | yes on fallback path only — 5-IP no-repeat cap; pool blocks just advance the pool cursor, no rotation | yes |
| ALDI | one session, valid ~30d, GraphQL via Instacart's own backend | effectively none (401/403 just invalidates) | no pool, no rotation | yes, logged only — no retry loop |
| Instacart | same shape as ALDI (ALDI rides on this backend) | same | no | yes, logged only |
| Meijer | Constructor.io API, API-key auth | none (docstring: "no WAF protection, just an API key") | proxy support in code, nothing to react to | no |
| Kroger | official partner API | none | no | no |
| Trader Joe's | Magento GraphQL, Akamai **rate-limit** (not a bot-challenge) | rate-limit, not anti-bot | no | no — different mechanism, out of scope |

AU: Coles/Woolworths removed entirely (commit `08125080`). IGA remains,
AU-only, not covered above.

## WAF block categorization

Lives in `walmart_pricing.py`, `target_pricing.py`, `aldi/aldi_pricing.py`,
`instacart_pricing.py`. `_Blocked`/`_ImpervaBlocked` carry `.category`:

- `"explicit"` — confirmed marker: `px-captcha` in body, 403+`captchaRelativeURL`,
  or a plain 401/403 (ALDI/Instacart). Trust this.
- `"soft"` — response is wrong but no explicit marker. Ambiguous — validated
  against only ONE failure shape (missing content), not proven generally.
- `"transport"` — no HTTP response ever received. Structurally distinct, not
  a WAF signal.

**Retry policy — Walmart/Target only.** ALDI/Instacart have no retry loop:
explicit/soft → rotate to a not-yet-tried IP, capped at
`min(MAX_IP_REFRESHES, len(_PROXIES))` (default 5) via
`_rotate_to_unused_proxy(tried_idxs)`. transport-only → retry the SAME
IP/session, capped separately at `_TRANSPORT_RETRIES` (default 2).

All four publish to Supabase `chain_block_events` (chain, category, detail,
created_at) via `session_store.log_block_event`, one row per retry round.
**No data has accumulated there yet** — new instrumentation, unobserved
against real production traffic.

## GitHub Actions offload (`mint_sessions.py` + `session_store.py`)

Mints Walmart/Target/ALDI/Instacart sessions on a 7GB GH Actions runner (not
Render, 512MB), publishes to Supabase `chain_sessions`; Render reads that
first, falls back to a local browser warm only on a cache miss. Also
pre-fetches Walmart/Target's static JS/CSS (`chain_assets`) so Render never
re-downloads those either. Skips re-minting a chain younger than half its TTL.

**Verified 2026-07-28 (previously unverified):**
- `chain_sessions` DOES exist live, but was missing the `extra` column this
  rewrite's `save()`/`load()` write/read — needs
  `ALTER TABLE chain_sessions ADD COLUMN IF NOT EXISTS extra JSONB DEFAULT '{}'::jsonb;`.
  `chain_assets` and `chain_block_events` did NOT exist at all (confirmed via
  a direct Supabase query, not inference) — every `save_assets()`/
  `log_block_event()` call had been failing silently since this code was
  written, which is exactly why nothing surfaced the Target endpoint
  breakage sooner. Both need the `CREATE TABLE` statements in `schema.sql`
  run against the live project.
- **New: `test-cookie-replay.yml` + `backend/test_cookie_replay.py`** (2026-07-28).
  Manual-only (`workflow_dispatch`), not on the cron, not related to the actual
  mint pipeline. Diagnostic tool: paste a saved cookie's `cookies` object +
  optional `item_count` (fires that many concurrent requests instead of one)
  to test whether a cookie minted elsewhere still works replayed from a GH
  runner's IP. Standalone script (curl_cffi only, no browser, no `import
  target_pricing`) so the job stays fast. This is what produced the
  cross-IP-replay-works finding above.
  **Updated 2026-07-29:** now auto-detects `backend/.target_http_session.json`
  if `COOKIE_JSON` env var is not set, so you can just run it with no inputs
  after a local mint. Also reads `ua` from the session file if `UA` env var
  is not set. "200 OK but no products" message replaced with dynamic status
  code reporting.
- **New: `test-walmart-cookie-replay.yml` + `backend/test_walmart_cookie_replay.py`**
  (2026-07-29). Same shape as the Target version but for Walmart. Standalone
  curl_cffi replay test that checks for `px-captcha` (explicit block), missing
  `__NEXT_DATA__` (soft block), and validates `itemStacks[].items[]` from the
  embedded JSON. Also auto-detects `backend/.walmart_http_session.json` if
  `COOKIE_JSON` is unset. This is the file that makes cross-IP Walmart replay
  testing possible on CI without ever launching a browser.
- **New: `backend/mint_walmart_cookies.py`** (2026-07-29). Standalone Walmart
  PerimeterX cookie minter. Launches CloakBrowser, warms via home → search
  (two navigations, verified required), waits for `_px3` to settle, validates
  `__NEXT_DATA__` ≥ 1000 chars, and saves to
  `backend/.minted_walmart_cookies.json` (JSON array, appended per run).
  Supports `--count N` for batch minting, `--proxy URL` for proxy rotation,
  `--headed` for debug visibility. No dependency on `walmart_pricing.py` or
  any other backend module — only `cloakbrowser` and stdlib.
- **New: `backend/test_saved_target_cookies.py`** (2026-07-29). Batch diagnostic
  that reads all 5 entries from `backend/saved_target_cookies.json` and fires
  a Target SLP search for each, printing per-cookie results + summary. Used
  to produce the 24h cookie-durability finding above.
- **Updated: `backend/walmart_cloak_scraper.py`** (2026-07-29). Added
  `_save_cookies(page, filepath)` — prints every cookie name+value to terminal
  and persists them as a JSON dict. Called at two points: after the location
  pin and after the search page loads (when PerimeterX `_px3` gets set).
- `CLOAK_PROXY` IS set as a working GH Actions secret (used successfully
  pre-2026-07-28 for Walmart mints going by `chain_sessions.walmart.updated_at`
  being fresh).
- This whole rewrite (session_store.py's asset/block-event additions,
  mint_sessions.py's ALDI/Instacart rotation + skip-if-fresh + fallback-
  tolerant exit code, the schema migrations) was sitting **uncommitted** in
  the working tree as of 2026-07-28 — not yet deployed, despite being what
  every local test in this doc was actually run against. Committed + pushed
  to `main` 2026-07-28 alongside the Target endpoint fix (see facts above).
  Still needs: the two Supabase migrations above (not yet confirmed run).

## Prewarm (frontend + `/prewarm`)

Fixed: no more eager/unconditional warm. `warmStores()` used to fire on
address-suggestion-tap (`location.tsx`) AND the home screen's "Start New"
(`(tabs)/index.tsx`), warming Walmart+Target regardless of proximity — both
call sites and the function are removed. Only remaining trigger:
`prewarm(location, time)` on Continue, which resolves the isochrone + real
nearby stores first and only warms chains actually in range.

---

## Meal planning (`meal_planner.py` + friends)

- **Data source is dual**: `server.py` fetches Supabase `meals` table
  (`db.get_meals()`) per request; on any failure, falls back to
  `meal_planner._load_meals()` reading `backend/meals.json` (cached
  process-wide). **`meals.json` currently has only 102 hand-written meals.**
- Entry point `create_weekly_meal_plan()` (`meal_planner.py`): resolves user
  constraints → hard filters (diet/allergen tags, ingredient exclusions) +
  soft preferences (cuisine, health tags, cook-time, calorie proximity) →
  `_filter_meals` (raises `NoSafeMealsError` if empty — **no silent
  fallback**, by design) → `_select_meals` (randomized-window sampling if
  `experiment=True`) → scales qty by household size, marks `is_at_home`
  against fridge tokens, aggregates shopping list.
- **Health tags (`prefer_health_tags`) are ranking-only, never a hard
  filter** — documented intentionally in `MEALS_TAGGING.md`, not a bug, but a
  real product gap: a listed health condition gets a soft nudge, not
  enforcement.
- **A large offline tagging pipeline exists but was never merged into
  production.** `import_kaggle_recipes.py` → `tag_recipes.py` →
  `normalize_quantities.py` → `curate_meals.py` → `validate_meals.py`
  processed a Kaggle Food.com dump (83,781 raw recipes) into **66,428 curated,
  tagged, QA'd recipes** (`meals_curated.jsonl`, ~132MB, dated Jul 25) — but
  there is no merge script and no evidence this ever reached `meals.json` or
  the Supabase `meals` table. Production still runs on the original 102
  meals. This is recent, well-documented, apparently-still-wanted work with
  its last mile missing, not dead code — worth finishing or explicitly
  shelving.
- **Allergen keyword drift risk**: `meal_planner._ALLERGEN_INGREDIENT_KEYWORDS`
  and `tag_recipes.ALLERGEN_KEYWORDS` are two independently-maintained lists
  with slightly different contents. `validate_meals.py` imports `tag_recipes`
  directly for its own QA, so at least that pairing stays in sync; the
  `meal_planner.py` copy doesn't.

## Optimizer (`optimizer.py`, 335 lines) + geo/store search (`geo_utils.py`, 291 lines)

- **Algorithm**: brute-force phased search, not a heuristic solver. Phase 1
  prices every store, tracks the cheapest time-feasible single stop. Phase 2
  prunes multi-store candidates to ones that beat the k=1 winner on ≥1 item.
  Phase 3 enumerates `combinations()` for k=2..`MAX_STORES_PER_ROUTE` (config
  default 3), `permutations()` per subset for fastest visit order, with a
  frozenset memo skipping supersets of already-time-infeasible subsets. A
  multi-store route only wins if it beats the k=1 winner by ≥ $0.01.
  `MAX_STORES_TO_USE` (hardcoded 10, `config.py`) caps how many stores get
  priced at all, enforced in `server.py` before the optimizer runs.
- **Coverage-fix (`calculate_split_shopping_price`) confirmed correct**: an
  unpriced item is now skipped (not `inf`-poisoning the route), with a route
  rejected only if `priced_items/len(shopping_list) < OPTIMIZER_MIN_COVERAGE`
  (default 0.5). Empty-list edge case guarded.
- **Still open**: `location_names.index(store_id)` — O(n) — is called inside
  BOTH k-loops (once per k=1 store, and once per store per k>1 subset), never
  fixed despite being flagged in the 2026-07-05 pass. Real cost given Phase 3
  is already combinatorial; cheap fix (build an index dict once).
- **geo_utils.py**: store discovery is one Google Places `places_nearby` call
  per chain keyword (`rank_by=distance`, first valid in-isochrone non-dupe
  result), not one broad search — scales linearly with chain count on a
  cache miss. Isochrone via OpenRouteService, 7-day cache; `server.py` (not
  geo_utils.py) has a 15km bounding-box fallback if ORS returns nothing.
  Nominatim/OSM is NOT used in geo_utils.py at all — it's a fallback
  geocoder only in `server.py:_geocode_address` (after Google fails) and
  independently the primary geocoder in `main.py` (CLI path).
- **New finding, not in the 2026-07-05 pass**: `/generate_plan` and
  `/price_list` in `server.py` (1425 lines total) independently reimplement
  nearly the same isochrone → Places → filter-chains → matrix → optimizer
  wiring — the code itself has a comment noting the duplication. This is most
  of why `server.py` is large; extracting a shared "plan pipeline" helper
  would cut it substantially. Neither `optimizer.py` nor `geo_utils.py`
  individually needs splitting.

## Coupons

- `coupon_scraper.py` scrapes the **Flipp flyer API** for a postal code,
  filters to known grocery chains, upserts into Supabase `coupons`
  (`schema.sql`, RLS: public read / service_role write). **Actively wired
  into the live pricing path** — called inline on every `/generate_plan`
  request (not a scheduled job), budget-bounded (`_FETCH_BUDGET` 20s,
  per-call timeout 8s) so a hung Flipp call can't stall a plan. Read back via
  `_overlay_coupon_prices` in `server.py`. Not dead weight.
- `scraper_worker.py` (a separate, standalone/crontab-style script) also
  calls the coupon fetch, gated by `COUPON_ZIPCODES` — **that env var isn't
  set anywhere in the repo**, so this path is effectively inert. Not wired
  into `.github/workflows/mint-sessions.yml` (the only scheduled GH Action;
  it only runs `mint_sessions.py`, nothing coupon-related).
- **`flippscrape/`** (untracked, repo root) is an orphaned prototype with its
  own nested `.git` (cloned from a different GitHub repo, `Kiizon/flippscrape`)
  — writes to local CSVs via pandas, not Supabase, and is not referenced
  anywhere in `backend/`. `coupon_scraper.py` was clearly adapted from it.
  Candidate for deletion — a nested `.git` inside the repo is also a real risk
  (accidental submodule confusion, `git add -A` behaving unexpectedly near it).

## Frontend

- **Screen flow**: home (`(tabs)/index.tsx`, start new / saved plans list) →
  `location.tsx` (address + time, fires prewarm) → `search.tsx` (plan-detail
  form, 5s `LoadingGate` masks backend prewarm) → `results.tsx` → optionally
  `recipe_details.tsx` or `barcode.tsx`. Saved plans replay via `results.tsx`
  with a `savedId` param.
- **`planStore.ts` is pure in-memory** (max 5 saved plans, stable `id`
  lookup) — no AsyncStorage, no Supabase read, explicitly documented as
  session-only in the file. **Notable disconnect**: the backend DOES persist
  completed plans server-side (`server.py:_save_results` → Supabase
  `meal_plans`/`shopping_routes`), but the frontend's "saved plans" list never
  reads that — it's a separate, local-only, reload-losing cache. Whether
  that's intentional (privacy? simplicity?) or a gap worth closing is an open
  question, not something the code answers.
- **`ShoppingMap.tsx` (native) vs. `.web.tsx`**: meaningful divergence, not a
  stub. Native renders a real `react-native-maps` `MapView` with
  markers/polyline/auto-fit. Web renders a styled placeholder card (store
  list text + an outbound "View Full Route on Google Maps" link) — no map
  library on web at all.
- **`(tabs)/explore.tsx`** is unmodified Expo template boilerplate — dead
  code, safe to delete.

## Known stubs / non-functional features (things that look implemented but aren't)

- **Fridge-photo scanning** (`fridge_manager.analyze_fridge_image`) — always
  returns `""`. Wired into `server.py` (fires when `fridge_image_path` is
  set) but the code itself substitutes a user-facing warning instead of
  pretending to have scanned anything. An abandoned vision prototype exists
  at `archive/fridge_scanner_prototype/` (Gemini/vision client code) but
  isn't imported anywhere — this was tried, then dropped for manual text
  entry.
- **`barcode.tsx`** — a demo screen with a hardcoded fake coupon code
  (`R52-DEMO-2024-X99`), reached from `results.tsx`'s `onUseCoupon` as if it
  were a real redemption flow. Not functional.

## Diagnostic scripts (cookie minting & replay testing)

A family of standalone scripts in `backend/` for manual cookie diagnostics.
All deliberately avoid importing the production pricing modules so they stay
lightweight and CI-friendly.

| Script | Chain | Purpose | Deps |
|---|---|---|---|
| `test_cookie_replay.py` | Target | Replay a saved Target PerimeterX cookie from GH runner's IP (or local) — single or N concurrent. Auto-reads `.target_http_session.json`. | curl_cffi only |
| `test_walmart_cookie_replay.py` | Walmart | Same as above for Walmart. Checks `px-captcha` + `__NEXT_DATA__`. Auto-reads `.walmart_http_session.json`. | curl_cffi only |
| `test_saved_target_cookies.py` | Target | Batch-test all cookies in `saved_target_cookies.json` (5 as of 2026-07-28). Prints per-cookie status + summary. | curl_cffi only |
| `mint_walmart_cookies.py` | Walmart | Mint fresh PerimeterX cookies via CloakBrowser home→search warm. Supports `--count N`, `--proxy`, `--headed`. Saves to `.minted_walmart_cookies.json`. | cloakbrowser + stdlib |
| `monitor_walmart_cookie_ttl.py` | Walmart | Health/TTL monitor: pings ONE cookie at a fixed interval until it dies (N consecutive fails) or hits a runtime cap, logging latency + JSONL to `.walmart_cookie_ttl_log.jsonl`. Not yet run to a real death (deprioritized 2026-07-30 in favor of the concurrency investigation). | curl_cffi only |
| `test_walmart_concurrency_matrix.py` | Walmart | Independently configurable item-count/concurrency/wave-count burst tester (unlike `test_walmart_cookie_replay.py`, whose `max_workers=20` is hardcoded and conflates the two). Used to find the exact 20-request concurrency wall — see findings above. | curl_cffi only |

CI workflows (`.github/workflows/`):
- `test-cookie-replay.yml` — manual `workflow_dispatch`, runs `test_cookie_replay.py` on ubuntu-latest, 5min timeout.
- `test-walmart-cookie-replay.yml` — same for Walmart, runs `test_walmart_cookie_replay.py`.

`backend/build_target_store_directory.py` (2026-07-30, not a cookie script)
geocodes Target's public store sitemap into `target_store_directory.json`
(`{store_id, slug, lat, lon}`) so `target_pricing._resolve_store_id` can do
an offline nearest-neighbor lookup instead of calling the confirmed-dead
`nearby_stores_v1`. One-time/occasional re-run (~30-35min, Nominatim-rate-
limited), not on any schedule. Deps: `curl_cffi`, `geopy`.

Usage examples:
```bash
# Mint 3 Walmart cookies in sequence
python backend/mint_walmart_cookies.py --count 3

# Test the most recently minted Walmart cookie from CI
# → paste the "cookies" object into the GH Actions workflow_dispatch input

# Test all 5 saved Target cookies locally
python backend/test_saved_target_cookies.py

# Auto-detect a fresh local Target cookie (no env vars needed)
python backend/test_cookie_replay.py
```

## Open TODOs (known gaps, not fixed)

**WAF/pricing:**
1. ~~Replay-path proxy mismatch~~ — **tested directly 2026-07-28, not an
   issue**: a Target cookie minted with no proxy replayed successfully from
   a completely different IP (a GitHub Actions runner), single request and a
   100-item concurrent batch. See facts above.
2. Walmart's fallback content-check (`_fetch_items_browser`) accepts any
   non-empty `__NEXT_DATA__`; the primary path requires length ≥ 1000.
   Inconsistent, never aligned.
3. `"soft"` category unproven beyond the one failure mode tested.
4. Request-velocity **is now partially captured as a real observation**
   (not yet as logged data — `chain_block_events` still needs the schema
   migration run): Walmart went from 7/7 clean warms to 100%-blocked within
   one day of ordinary test volume from one IP; Target showed zero
   degradation under materially higher volume (104-way concurrent burst, 8x
   repeated full-basket runs). Chain-dependent, not a single "IP reputation"
   knob. `chain_block_events` (once the table exists) would make this
   queryable instead of inferred from test notes.
5. Trader Joe's has no categorized detection (different mechanism).
6. No proxy pool purchased/configured yet for Walmart specifically — Target
   looks safe to self-host proxy-free (item 1), Walmart does not yet (item
   4). Recommendation unchanged for Walmart: a proxy or rotating-residential
   line until its block (2026-07-28) is confirmed either temporary (retest
   days later) or durable.

**Rest of the app:**
7. Meal-tagging pipeline (66k recipes) never merged into production data.
8. Allergen keyword lists drift between `meal_planner.py` and `tag_recipes.py`.
9. `location_names.index()` O(n) in optimizer k-loops, still unfixed.
10. `server.py`'s `/generate_plan` and `/price_list` duplicate the
    geo/optimizer wiring — candidate for extraction.
11. Frontend saved-plans (`planStore.ts`) vs. backend-persisted plans
    (Supabase `meal_plans`) are disconnected — reload loses the UI list even
    though the backend has the data.
12. `flippscrape/` (orphaned, nested `.git`) and `(tabs)/explore.tsx`
    (unmodified boilerplate) are safe-to-delete clutter.

---

## Shipped 2026-07-05 pass (background, unchanged since)

- **Store-integration test pipeline** — [`backend/tests_integration/`](backend/tests_integration/).
  Scores every pricing backend on resolution/coverage/sanity/latency/reliability.
  `PYTHONPATH=. python -m tests_integration.run --tag kroger` etc. from `backend/`.
  Adding a store = one `StoreCase` in `registry.py`.
- **Cache speedup** — [`backend/cache_manager.py`](backend/cache_manager.py):
  in-memory LRU tier over the disk cache, atomic writes + lock. Interface
  unchanged (`cache.get`/`cache.set`). **Disk-tier unbounded-growth issue
  (originally finding #7) is now resolved** — `DISK_MAX_FILES`/
  `DISK_MAX_AGE_SECONDS` with a periodic sweep were added since.

## Modularization findings still open

| # | Finding | Current state | Action |
|---|---|---|---|
| 1 | Repo clutter | Root-level `probe_costco*.py`/`test_*.py` cleaned up (moved into `costco/`). `archive/` grew 19→27 files. Add: `flippscrape/`, `explore.tsx` (see above) | delete/relocate; `.gitignore` a `scratch/` dir |
| 3 | Store dispatch not formalized — `server.py` if-ladders, separate fetchers, scattered `is_X_store` matchers | unchanged | a `StoreAdapter` registry, shape of `tests_integration/registry.py` |
| 4 | `kroger_pricing.py` (1328 lines) is actually the generic product-matching engine, not Kroger-specific | unchanged, not renamed | rename → `product_matching.py` + re-export shim |
| 6 | Inconsistent pricer return shapes | narrower than originally stated: only Trader Joe's (2-tuple) and Costco (4-tuple) differ from the 3-tuple everyone else uses | normalize to a `PricingResult` dataclass |
| 8 | `optimizer.py` O(n) `.index()` in k-loops | confirmed still present, precise locations known (see Optimizer section) | build an index dict once |
