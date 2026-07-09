import { Platform } from 'react-native';
import Constants from 'expo-constants';

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

const DEV_API_URL = getApiUrl();
// Surfaces which backend is in use so it's obvious in the Expo / browser console.
console.log(`[api] target=${API_TARGET ?? 'auto'} → ${DEV_API_URL}`);

export interface ShoppingPlanRequest {
    location: string;
    budget: number;
    time: number;
    calories?: number;
    household_size?: number;
    days?: number;
    meals_per_day?: number;
    dietary_restrictions?: string;
    health_issues?: string;
    cuisines?: string;
    experiment?: boolean;
    cook_time?: string;
    fridge_items?: string;
    fake_data?: boolean;
    has_costco_card?: boolean;
}

export interface MealPlanItem {
    day: string;
    meal_type: string;
    name: string;
    calories: number;
    cook_time: string;
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
    shopping_list: {
        store: string;
        address: string;
        coordinates: { lat: number; lng: number };
        items: {
            name: string;
            qty: number;
            price: number;
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
// so a plan can take a while. Give it a generous ceiling instead of relying on
// React Native's default fetch timeout (~60s), which would abort a valid request.
const PLAN_TIMEOUT_MS = 180000; // 3 minutes

// Fire-and-forget: the moment the user submits address + shopping time, tell the
// backend to (1) resolve the nearby stores and (2) mint the Walmart/Target browser
// cookies, so the eventual generatePlan skips the store search + ~8s-per-store warm.
// Never throws — a failed prewarm just means no speedup, the plan request does the
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

// Eager warm: fired the instant the user taps an address suggestion. Mints BOTH
// the Walmart + Target cookies unconditionally (range isn't known yet) — the
// follow-up prewarm(location, time) on Continue prunes whatever's out of range.
export const warmStores = (location: string): void => {
    fetch(`${DEV_API_URL}/api/prewarm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: location || '', warm_only: true }),
    }).catch((e) => console.log('[api] warmStores failed (non-fatal):', e));
};

// Address type-ahead for the /location screen. Returns up to 5 suggestion strings
// from Google Places (via our backend, which holds the key). Never throws.
export const autocompleteAddress = async (q: string): Promise<string[]> => {
    if (!q?.trim() || q.trim().length < 3) return [];
    try {
        const res = await fetch(`${DEV_API_URL}/api/autocomplete?q=${encodeURIComponent(q.trim())}`);
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data?.suggestions) ? data.suggestions : [];
    } catch {
        return [];
    }
};

export const generatePlan = async (params: ShoppingPlanRequest): Promise<ShoppingPlanResponse> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PLAN_TIMEOUT_MS);
    try {
        const response = await fetch(`${DEV_API_URL}/api/generate_plan`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                preferences: {
                    address: params.location,
                    budget: params.budget,
                    shopping_time_hours: Number(params.time) || 3,
                    calorie_target: Number(params.calories) || 2000,
                    household_size: Number(params.household_size) || 1,
                    days_plan: Number(params.days) || 7,
                    meals_per_day: Number(params.meals_per_day) || 3,
                    dietary_restrictions: params.dietary_restrictions || "",
                    health_issues: params.health_issues || "",
                    cuisines: params.cuisines || "",
                    experiment: params.experiment !== undefined ? params.experiment : true,
                    cook_time: params.cook_time || "30-45 minutes",
                    fridge_items: params.fridge_items || "",
                    has_costco_card: params.has_costco_card !== undefined ? params.has_costco_card : false
                }
            }),
            signal: controller.signal,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to generate plan');
        }

        return await response.json();
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
