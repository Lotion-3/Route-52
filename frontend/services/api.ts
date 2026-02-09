import { Platform } from 'react-native';

// Use localhost for web/iOS simulator, 10.0.2.2 for Android Emulator
// For physical devices, you must use your computer's LAN IP (e.g., http://192.168.1.5:8000)
const LAN_IP = '10.35.22.118'; // Found via ipconfig

const getApiUrl = () => {
    if (Platform.OS === 'web') {
        return 'http://localhost:8000';
    }
    if (Platform.OS === 'android') {
        // Check if we are in an emulator (usually) or physical device
        // 10.0.2.2 is the special alias for the host machine in Android Emulator
        // However, using the LAN IP is often more reliable if the device is on the same network.
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
    days?: number;
    meals_per_day?: number;
    dietary_restrictions?: string;
    cuisines?: string;
    experiment?: boolean;
    cook_time?: string;
    fake_data?: boolean;
}

export interface MealPlanItem {
    day: string;
    meal_type: string;
    recipe: string;
    calories: number;
    cook_time: string;
    ingredients: string[];
}

export interface ShoppingPlanResponse {
    meal_plan: MealPlanItem[];
    route: string[];
    total_cost: number;
    total_time_minutes: number;
    user_location: { lat: number; lng: number };
    shopping_list: {
        store: string;
        address: string;
        coordinates: { lat: number; lng: number };
        items: { name: string; price: number }[];
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
                    shopping_time_hours: Number(params.time) || 1,
                    calorie_target: Number(params.calories) || 2000,
                    days_plan: Number(params.days) || 7,
                    meals_per_day: Number(params.meals_per_day) || 3,
                    dietary_restrictions: params.dietary_restrictions || "",
                    cuisines: params.cuisines || "",
                    experiment: params.experiment !== undefined ? params.experiment : true,
                    cook_time: params.cook_time || "30-45 minutes"
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
