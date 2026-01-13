
import os
from dotenv import load_dotenv
from typing import Dict, Tuple

# Load environment variables from the config.env file
load_dotenv('config.env') 

# --- 1. API KEY SETUP AND CONFIGURATION ---
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    print("FATAL ERROR: ORS_API_KEY missing in 'config.env'.")
    exit(1)

# OpenRouteService Endpoints
ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
ORS_ISOCHRONE_URL = "https://api.openrouteservice.org/v2/isochrones/driving-car"

# Overpass API Endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter" 

# --- API LIMIT CONSTANT ---
MAX_MATRIX_LOCATIONS = 50 
MAX_STORES_TO_USE = MAX_MATRIX_LOCATIONS - 1  # One spot for "Start" location

# --- PRICE VARIANCE RANGE ---
MIN_PRICE_FACTOR = 0.6
MAX_PRICE_FACTOR = 1.4

# --- NUTRITION CONSTANTS ---
DAILY_CALORIE_TARGET = 2000
DAYS_PER_WEEK = 7
MEALS_PER_DAY = 3
TOTAL_WEEKLY_CALORIES = DAILY_CALORIE_TARGET * DAYS_PER_WEEK
TOTAL_MEALS = DAYS_PER_WEEK * MEALS_PER_DAY

# Target macronutrient distribution (as percentages)
CARB_PERCENT = 0.55  # 55% carbs
PROTEIN_PERCENT = 0.15  # 15% protein
FAT_PERCENT = 0.30  # 30% fat

# Calories per gram of each macronutrient
CALORIES_PER_GRAM_CARB = 4
CALORIES_PER_GRAM_PROTEIN = 4
CALORIES_PER_GRAM_FAT = 9

# --- 2. DYNAMIC SEARCH CONFIG & CONSTANTS ---
# User input for location and shopping time
USER_START_LOCATION: Tuple[float, float] = (40.0033, -86.1366)  # Near Indianapolis
SHOPPING_TIME_HOURS = 3.0  # User's available shopping time
MAX_TIME_SECONDS = SHOPPING_TIME_HOURS * 3600 * 1.1  # 10% buffer

# --- STORE TIME MULTIPLIERS ---
STORE_TIME_MULTIPLIERS: Dict[str, float] = {
    "Aldi": 0.8,         
    "Trader Joe's": 0.9, 
    "Kroger": 1.0,       
    "Meijer": 1.1,       
    "Whole Foods": 1.2,  
    "Walmart": 1.2,      
    "Costco": 1.5         
}

# --- TIME MODEL CONSTANTS ---
BASE_CHECKOUT_TIME_MINUTES = 7 
BASE_PARK_ENTRANCE_TIME_MINUTES = 5
TIME_PER_ITEM_MINUTES = 0.5  # Reduced since we're buying in bulk for a week

BASE_FIXOUT_OVERHEAD = (BASE_CHECKOUT_TIME_MINUTES + BASE_PARK_ENTRANCE_TIME_MINUTES) * 60 
TIME_PER_UNIT_SECONDS = TIME_PER_ITEM_MINUTES * 60 

# --- DATA FILES ---
VEGGIES_CSV = "alanVeggies.csv"
RECIPES_CSV = "RAW_recipes.csv"

# --- CITY-TO-STATE MAPPING ---
STORE_CITY_MAPPING = {
    "Kroger": "Indianapolis", "Walmart": "Indianapolis", "Meijer": "Indianapolis",
    "Target": "Indianapolis", "Aldi": "Indianapolis", "Whole Foods": "Indianapolis",
    "Trader Joe's": "Indianapolis", "Costco": "Indianapolis", "Safeway": "Indianapolis",
    "Publix": "Indianapolis", "Giant": "Indianapolis", "Food Lion": "Indianapolis",
    "Harris Teeter": "Indianapolis", "Hy-Vee": "Indianapolis", "H-E-B": "Indianapolis",
    "Wegmans": "Indianapolis", "Stop & Shop": "Indianapolis", "ShopRite": "Indianapolis"
}
