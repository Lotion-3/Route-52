# developerFrontEnd — static, edit-easy copy of basketBuddy's frontend

This is a full copy of `../frontend`, wired into **nothing**: no backend, no API keys, no scrapers,
no network calls of any kind. Every screen renders from one baked-in mock shopping plan
(`mocks/demoMealPlan.ts`) built from 8 real, randomly-picked meals out of `../backend/meals.json`,
plus a fabricated 3-store route/address. No matter what you type into the location or search
forms, the same plan comes up — the point is a stable, realistic surface you can restyle freely
without breaking anything real or needing any of the app's live integrations running.

A small **"DEMO — static data"** badge (top-right, added in `app/_layout.tsx`) marks this build so
it's never confused with the real app while you're working in it.

## Running it

From the repo root:

```
devfrontendrun.bat
```

Or manually:

```bash
cd developerFrontEnd
npm install   # first run only
npx expo start -c --port 8090
```

It runs on its own port (8090) so it can be open side-by-side with the real `frontend/` (which
defaults to 8081) without conflicting.

## What's different from `frontend/`

Only four things were changed after copying:

| File | Change |
|---|---|
| `services/api.ts` | Real `fetch` calls replaced with mock resolvers reading from `mocks/`. Same exported types/function signatures, so every screen works unmodified. |
| `app/_layout.tsx` | Removed the backend health-check network call; added the DEMO badge. |
| `mocks/demoMealPlan.ts`, `mocks/demoAddresses.ts` | New — generated fixture data, not present in `frontend/`. |
| `scripts/build-demo-plan.js` | New — the one-off generator that produced the two files above. |

Everything else — `app/`, `components/`, `constants/`, `hooks/`, `assets/` — is an unmodified copy.

## Rolling a fresh set of meals

The 8 meals are picked randomly but committed as a static fixture (so styling work has a stable
target). To re-roll with a different random set:

```bash
node scripts/build-demo-plan.js
```

This overwrites `mocks/demoMealPlan.ts` and `mocks/demoAddresses.ts` from the current
`../backend/meals.json`.

## Porting aesthetic changes back to the real frontend

Once you're happy with a restyle here, promote it to production by copying the edited files
(`app/`, `components/`, `constants/`, `assets/`, etc.) back over their counterparts in
`../frontend/`. **Never copy `services/api.ts` or the DEMO-badge block in `app/_layout.tsx`** —
those are this copy's mock wiring, not something the real, backend-connected app should have.
