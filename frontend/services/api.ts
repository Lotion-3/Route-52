import { Platform } from 'react-native';

// Use localhost for web/iOS simulator, 10.0.2.2 for Android Emulator
// For physical devices, you must use your computer's LAN IP (e.g., http://192.168.1.5:8000)
const LAN_IP = '10.35.22.118'; // Found via ipconfig

const getApiUrl = () => {
    if (Platform.OS === 'web') {
        // In production, Firebase Hosting rewrites /api/** to Cloud Run.
        // In local dev (__DEV__ is true), use localhost directly.
        if (typeof __DEV__ !== 'undefined' && __DEV__) {
            return 'http://localhost:8000';
        }
        return ''; // Use relative URLs — /api/... routes via Firebase Hosting rewrite
    }
    if (Platform.OS === 'android') {
        return `http://${LAN_IP}:8000`;
    }
    // Default for iOS / Physical devices
    return `http://${LAN_IP}:8000`;
};

const DEV_API_URL = getApiUrl();

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
    total_time_minutes: number;
    user_location: { lat: number; lng: number };
    at_home_ingredients: { name: string; qty: number; unit: string }[];
    shopping_list: {
        store: string;
        address: string;
        coordinates: { lat: number; lng: number };
        items: { name: string; qty: number; price: number }[];
    }[];
}

export const generatePlan = async (params: ShoppingPlanRequest): Promise<ShoppingPlanResponse> => {
    try {
        const response = await fetch(`${DEV_API_URL}/generate_plan`, {
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
