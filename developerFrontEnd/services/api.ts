// DEVELOPER FRONTEND — fully static, wired into nothing. Every export below
// used to call the real basketBuddy backend (see frontend/services/api.ts for
// that version); here they all resolve from baked-in mock data instead, so
// this whole app can run and be restyled with zero backend, zero API keys,
// and zero network calls. The exported types are kept identical so every
// screen's imports work unchanged.
import { DEMO_MEAL_PLAN } from '@/mocks/demoMealPlan';
import { DEMO_ADDRESS_POOL } from '@/mocks/demoAddresses';

// ── Auth token (kept as inert local state — nothing in this demo build reads
// or sets it, but the exports are kept so screens ported over from the real
// app compile unchanged) ─────────────────────────────────────────────────────
let authToken: string | null = null;

export const setAuthToken = (token: string | null): void => {
    authToken = token;
};

export const getAuthToken = (): string | null => authToken;

export interface ShoppingPlanRequest {
    location: string;
    budget: number;
    time: number;
    calories?: number;
    household_size?: number;
    days?: number;
    meals_per_day?: number;
    dietary_restrictions?: string;
    allergies?: string;
    avoid_ingredients?: string;
    health_issues?: string;
    cuisines?: string;
    experiment?: boolean;
    cook_time?: string;
    fridge_items?: string;
    has_costco_card?: boolean;
}

export interface MealPlanItem {
    day: string;
    /** Stable ordering key. `day` is a display label and repeats across weeks. */
    day_index?: number;
    meal_type: string;
    name: string;
    calories: number;
    cook_time: string;
    cook_time_minutes?: number;
    cuisine?: string;
    ingredients: { name: string; qty: number; unit: string; price?: number }[];
    instructions: string[];
}

export interface ShoppingPlanResponse {
    meal_plan: MealPlanItem[];
    route: string[];
    total_cost: number;
    cheapest_single_store_cost: number;
    cheapest_single_store_name: string;
    total_time_minutes: number;
    user_location: { lat: number; lng: number };
    at_home_ingredients: { name: string; qty: number; unit: string }[];
    warnings?: string[];
    budget?: number;
    over_budget?: boolean;
    shopping_list: {
        store: string;
        address: string;
        coordinates: { lat: number; lng: number };
        estimated?: boolean;
        pricing_note?: string;
        items: {
            name: string;
            qty: number;
            price: number;
            product_name?: string;
            size_str?: string;
            units_to_buy?: number;
            original_price?: number;
            coupon?: {
                type: string;
                label: string;
                savings: number;
                image_url: string;
                valid_to: string;
            };
        }[];
    }[];
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Real version fires a background "warm the store sessions" request. There's
// nothing to warm here — no-op.
export const prewarm = (_location: string, _timeHours?: string | number): void => {};

// Real version calls the backend's Google Places proxy. Here: filter the
// fixed demo address pool by substring, but never return an empty list just
// because the typed text doesn't match — an empty dropdown would make the
// autocomplete feature look broken while clicking through the app.
export const autocompleteAddress = async (q: string, _signal?: AbortSignal): Promise<string[]> => {
    if (!q?.trim() || q.trim().length < 3) return [];
    await delay(150);
    const needle = q.trim().toLowerCase();
    const filtered = DEMO_ADDRESS_POOL.filter((a) => a.toLowerCase().includes(needle));
    return (filtered.length > 0 ? filtered : DEMO_ADDRESS_POOL).slice(0, 4);
};

// Real version POSTs the user's preferences and gets back a priced,
// optimized shopping plan. Here: ignore whatever was entered on /location
// and /search entirely and always return the same fixed demo plan (built by
// scripts/build-demo-plan.js from 8 random real meals.json entries) — so no
// matter what's typed in while clicking through the app, the same realistic
// plan comes up. The short delay keeps the existing "Optimizing your
// shopping trip" loading screen visible, same as it would look for real.
export const generatePlan = async (_params: ShoppingPlanRequest): Promise<ShoppingPlanResponse> => {
    await delay(700);
    // Deep-clone so nothing downstream can mutate the shared fixture.
    return JSON.parse(JSON.stringify(DEMO_MEAL_PLAN));
};
