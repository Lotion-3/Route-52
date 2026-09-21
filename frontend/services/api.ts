import { Platform } from 'react-native';
import Constants from 'expo-constants';
import { priceWalmartAutoDevice } from './walmartDirect';

// Backend port — must match localrun.bat → PORT=8002
const BACKEND_PORT = 8002;

// Production backend URL (deployed on Render)
const PRODUCTION_API_URL = 'https://route52.onrender.com';

// Local development URL (for the browser running on the same machine)
const LOCAL_API_URL = `http://localhost:${BACKEND_PORT}`;

// Last-resort LAN IP if the dev-server host can't be read (rarely hit).
const FALLBACK_LAN_IP = '192.168.1.138';

// Auto-detect the dev machine's LAN IP from the Expo dev-server host. A physical
// device already connected to that IP to download the JS bundle, so it's the
// correct, reachable address for the backend on ANY network — no per-network
// hardcoding needed.
const devServerLanIp = (): string => {
    const hostUri =
        Constants.expoConfig?.hostUri ??
        (Constants.expoGoConfig as any)?.debuggerHost ??
        (Constants.manifest2 as any)?.extra?.expoGo?.debuggerHost ??
        (Constants.manifest as any)?.debuggerHost ??
        '';
    // hostUri looks like "192.168.1.138:8081" — keep the host, drop the port.
    const host = String(hostUri).split(':')[0];
    return host || FALLBACK_LAN_IP;
};

const lanApiUrl = () => `http://${devServerLanIp()}:${BACKEND_PORT}`;

// Which backend to talk to is chosen by the launch script:
//   localrun.bat → EXPO_PUBLIC_API_TARGET=local  (this machine's backend on :8002)
//   liverun.bat  → EXPO_PUBLIC_API_TARGET=live   (deployed Render backend)
// When unset, fall back to auto-detection (localhost web → local, else production).
const API_TARGET = process.env.EXPO_PUBLIC_API_TARGET;

// Resolve the correct LOCAL url: localhost web can reach localhost, but physical
// devices / LAN-served web must use the machine's LAN IP instead.
const localUrl = () => {
    if (
        Platform.OS === 'web' &&
        typeof window !== 'undefined' &&
        (window.location.hostname.includes('localhost') ||
            window.location.hostname.includes('127.0.0.1'))
    ) {
        return LOCAL_API_URL;
    }
    return lanApiUrl();
};

const getApiUrl = () => {
    // Explicit target from the launch script always wins.
    if (API_TARGET === 'live') return PRODUCTION_API_URL;
    if (API_TARGET === 'local') return localUrl();

    // No override → legacy auto-detection.
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
        // If NOT on localhost, use production backend
        if (!window.location.hostname.includes('localhost') && !window.location.hostname.includes('127.0.0.1')) {
            return PRODUCTION_API_URL;
        }
        return LOCAL_API_URL;
    }
    // Default for Android / iOS / physical devices
    return lanApiUrl();
};

export const DEV_API_URL = getApiUrl();
// Surfaces which backend is in use so it's obvious in the Expo / browser console.
console.log(`[api] target=${API_TARGET ?? 'auto'} → ${DEV_API_URL}`);

// ── Auth token ───────────────────────────────────────────────────────────────
// The backend already verifies a Supabase JWT (get_current_user) and persists
// finished plans for the authenticated user — but nothing ever sent an
// Authorization header, so user_id was always null and that whole path was
// dead. Requests now carry the token when one has been set. NOTE: there is no
// sign-in screen yet, so until one calls setAuthToken() this still resolves to
// anonymous; the plumbing just no longer has to change when it lands.
let authToken: string | null = null;

export const setAuthToken = (token: string | null): void => {
    authToken = token;
};

export const getAuthToken = (): string | null => authToken;

const authHeaders = (): Record<string, string> =>
    authToken ? { Authorization: `Bearer ${authToken}` } : {};

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
    /**
     * Constraints the backend could NOT fully honour (unsupported diet chips,
     * allergens it can't detect, relaxed cook-time limits, clamped inputs).
     * These must be shown to the user — silently dropping them is what let a
     * "Kosher" plan contain pork.
     */
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

// Pricing scrapes several stores (incl. headless-browser stores like Walmart),
// so a plan can take a while. Budget, worst case: geocode + isochrone + Places,
// then the server's 75s pricing budget, then up to 20s of coupon fetching, then
// the optimiser — on top of a Render free-tier cold start of ~50s. 3 minutes cut
// that too close and aborted valid requests; 4 leaves real headroom.
const PLAN_TIMEOUT_MS = 240000; // 4 minutes

/**
 * Turn a failed Response into a useful Error.
 *
 * `await response.json()` used to be called unconditionally on the error path.
 * Render's 502/504 pages and any proxy error are HTML, so the parse threw and
 * the user saw a JSON syntax error instead of the backend's actual message
 * (e.g. "No stores with real pricing found in your area").
 */
const errorFromResponse = async (response: Response): Promise<Error> => {
    const fallback: Record<number, string> = {
        422: 'No recipes match your restrictions. Try removing one and searching again.',
        429: 'Too many plan requests. Please wait a few minutes and try again.',
        502: 'The server is starting up. Please try again in a moment.',
        503: 'No stores with live pricing were found near you.',
        504: 'The server took too long to respond. Please try again.',
    };
    let body = '';
    try {
        body = await response.text();
    } catch {
        /* body unreadable — fall through to the status-based message */
    }
    if (body) {
        try {
            const data = JSON.parse(body);
            const detail = data?.detail ?? data?.error;
            if (typeof detail === 'string' && detail) return new Error(detail);
        } catch {
            // Not JSON (HTML error page, plain text, truncated body).
        }
    }
    return new Error(fallback[response.status] ?? `Request failed (${response.status}).`);
};

// Fire-and-forget: the moment the user submits address + shopping time, tell the
// backend to (1) resolve the nearby stores and (2) warm ONLY the chains actually
// found in range — never speculatively, never before an address is known. Never
// throws — a failed prewarm just means no speedup, the plan request does the
// work itself. timeHours is passed so the store-isochrone cache key matches generate.
export const prewarm = (location: string, timeHours?: string | number): void => {
    if (!location?.trim()) return;
    const t = typeof timeHours === 'string' ? parseFloat(timeHours) : timeHours;
    fetch(`${DEV_API_URL}/api/prewarm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            address: location,
            shopping_time_hours: Number.isFinite(t as number) ? t : 3,
        }),
    }).catch((e) => console.log('[api] prewarm failed (non-fatal):', e));
};

// Address type-ahead for the /location screen. Returns up to 5 suggestion strings
// from Google Places (via our backend, which holds the key). Never throws.
//
// Accepts an AbortSignal: without cancellation a slow earlier keystroke could
// resolve AFTER a later one and overwrite the newer suggestions with stale ones.
export const autocompleteAddress = async (q: string, signal?: AbortSignal): Promise<string[]> => {
    if (!q?.trim() || q.trim().length < 3) return [];
    try {
        const res = await fetch(
            `${DEV_API_URL}/api/autocomplete?q=${encodeURIComponent(q.trim())}`,
            { signal },
        );
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data?.suggestions) ? data.suggestions : [];
    } catch {
        // Includes AbortError when a newer keystroke superseded this request.
        return [];
    }
};

// The backend clamps these too; keeping the client in step means the user sees
// a sane value rather than a 422 from Pydantic.
const clampInt = (v: unknown, lo: number, hi: number, dflt: number): number => {
    const n = Math.floor(Number(v));
    if (!Number.isFinite(n)) return dflt;
    return Math.min(hi, Math.max(lo, n));
};

const buildPreferences = (params: ShoppingPlanRequest) => ({
    address: params.location,
    budget: Number.isFinite(Number(params.budget)) ? Number(params.budget) : 150,
    shopping_time_hours: Number(params.time) || 3,
    calorie_target: clampInt(params.calories, 800, 8000, 2000),
    household_size: clampInt(params.household_size, 1, 12, 1),
    days_plan: clampInt(params.days, 1, 30, 7),
    meals_per_day: clampInt(params.meals_per_day, 1, 6, 3),
    dietary_restrictions: params.dietary_restrictions || "",
    // Allergens and the avoid-list were collected by the search screen and
    // then dropped — they never reached the server, so a plan could contain
    // something the user is allergic to.
    allergies: params.allergies || "",
    avoid_ingredients: params.avoid_ingredients || "",
    health_issues: params.health_issues || "",
    cuisines: params.cuisines || "",
    experiment: params.experiment !== undefined ? params.experiment : true,
    cook_time: params.cook_time || "30-45 minutes",
    fridge_items: params.fridge_items || "",
    has_costco_card: params.has_costco_card !== undefined ? params.has_costco_card : false,
});

// Legacy single-shot path: server prices every store including Walmart
// itself (usually fails there — Render's shared egress IP keeps getting
// rate-limited by Walmart's WAF, so Walmart just comes back excluded, same
// as it always has). Used directly on web (no device-pricing option exists
// there — see walmartDirect.ts) and as the native path's fallback if the
// two-phase flow below fails for any reason.
const generatePlanLegacy = async (params: ShoppingPlanRequest, signal: AbortSignal): Promise<ShoppingPlanResponse> => {
    const response = await fetch(`${DEV_API_URL}/api/generate_plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ preferences: buildPreferences(params) }),
        signal,
    });
    if (!response.ok) throw await errorFromResponse(response);
    return response.json();
};

// Real Walmart pricing, sourced from the user's own device, WITH Walmart
// genuinely competing for a spot in the optimized route (2026-09-20) — not
// just listed alongside it. Two round trips to the server:
//   phase1: prices every store EXCEPT Walmart, returns a token + the
//           ingredient list Walmart needs prices for.
//   (here): light-scan the cached cookie pool from THIS device (native
//           only — a browser can't do this at all, see walmartDirect.ts),
//           price the real list with whichever cookie works, falling back
//           to a server-side live mint only as priceWalmartAutoDevice's own
//           last resort.
//   phase2: server merges those prices into the SAME price data phase1
//           built and runs the SAME optimizer the legacy path uses —
//           Walmart can now actually win a spot in the route.
// See server.py's generate_plan_phase1/phase2 for the other half of this.
const generatePlanDeviceWalmart = async (params: ShoppingPlanRequest, signal: AbortSignal): Promise<ShoppingPlanResponse> => {
    const phase1 = await fetch(`${DEV_API_URL}/api/generate_plan/phase1`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ preferences: buildPreferences(params) }),
        signal,
    });
    if (!phase1.ok) throw await errorFromResponse(phase1);
    const { token, ingredients } = await phase1.json();

    let walmartPrices: Record<string, { unit_price: number; description: string; brand: string; size_str: string }> = {};
    let sessionSource = '';
    try {
        const { prices, sessionSource: src } = await priceWalmartAutoDevice(ingredients, (phase, done, total) =>
            console.log(`[walmartDirect] ${phase} ${done}/${total}`),
        );
        sessionSource = src;
        walmartPrices = Object.fromEntries(
            Object.entries(prices).map(([name, it]) => [
                name,
                { unit_price: it.price, description: it.name, brand: it.brand, size_str: it.size },
            ]),
        );
    } catch (e) {
        // Device pricing failed entirely (pool scan AND server live-mint
        // fallback both came up empty) — phase2 with empty walmart_prices
        // just excludes Walmart, same as the legacy path when it fails.
        console.log('[walmartDirect] device pricing failed entirely, continuing without Walmart:', e);
    }

    const phase2 = await fetch(`${DEV_API_URL}/api/generate_plan/phase2`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, walmart_prices: walmartPrices, session_source: sessionSource }),
        signal,
    });
    if (!phase2.ok) throw await errorFromResponse(phase2);
    return phase2.json();
};

export const generatePlan = async (params: ShoppingPlanRequest): Promise<ShoppingPlanResponse> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PLAN_TIMEOUT_MS);
    try {
        if (Platform.OS === 'web') {
            return await generatePlanLegacy(params, controller.signal);
        }
        try {
            return await generatePlanDeviceWalmart(params, controller.signal);
        } catch (e) {
            console.log('[api] two-phase plan failed, falling back to legacy single-shot:', e);
            return await generatePlanLegacy(params, controller.signal);
        }
    } catch (error: any) {
        if (error?.name === 'AbortError') {
            console.error('API Error: plan request timed out');
            throw new Error('Generating your plan took too long. Please try again.');
        }
        console.error('API Error:', error);
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }
};
