import { Platform } from 'react-native';

// Production backend URL (deployed on Render)
const PRODUCTION_API_URL = 'https://route52.onrender.com';

// Local development URL
const LOCAL_API_URL = 'http://localhost:8000';
const LAN_IP = '10.35.22.118'; // Found via ipconfig

const getApiUrl = () => {
    // Check if running in web on Firebase (production)
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
        // If NOT on localhost, use production backend
        if (!window.location.hostname.includes('localhost') && !window.location.hostname.includes('127.0.0.1')) {
            return PRODUCTION_API_URL;
        }
        return LOCAL_API_URL;
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
    cheapest_single_store_cost: number;
    cheapest_single_store_name: string;
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
