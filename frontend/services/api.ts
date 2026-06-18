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

export const generatePlan = async (params: ShoppingPlanRequest): Promise<ShoppingPlanResponse> => {
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
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to generate plan');
        }

        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
};
