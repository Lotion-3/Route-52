
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict

# Load config.env from THIS file's directory, not the process CWD.
# `load_dotenv('config.env')` resolved relative to wherever the server was
# launched from, so `python backend/server.py` (rather than `cd backend &&
# python server.py`) found nothing and died at the ORS_API_KEY check below.
load_dotenv(Path(__file__).resolve().parent / "config.env")

# --- 1. API KEY SETUP AND CONFIGURATION ---
ORS_API_KEY = os.getenv("ORS_API_KEY")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not ORS_API_KEY:
    print("FATAL ERROR: ORS_API_KEY missing in 'config.env'.")
    exit(1)

# No hardcoded fallback key. There used to be a literal Google Maps API key
# here as a convenience default — which meant it lived in git history, readable
# by anyone with repo access, and was billed to this project by whoever found
# it. Missing config must fail loudly, never fall back to a committed secret.
if not GOOGLE_MAPS_API_KEY:
    print("FATAL ERROR: GOOGLE_MAPS_API_KEY missing in 'config.env'. "
          "Address autocomplete, geocoding and store search all require it.")
    exit(1)

# OpenRouteService Endpoints
ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
ORS_ISOCHRONE_URL = "https://api.openrouteservice.org/v2/isochrones/driving-car"

# --- STORE SEARCH CONFIG ---
STORE_KEYWORDS = [
    'Walmart', 'Aldi', 'Kroger', 'Target', 'Meijer', 'Trader Joe\'s', 'Trader Joes', 'Costco', 'Jewel Osco',
    # Australia — Google Places is location-scoped, so mixing these in with the
    # US keywords is harmless (an AU address just won't return Walmart/Kroger
    # results, and vice versa).
    'Coles', 'Woolworths', 'IGA',
]

# Keywords to exclude from store results. There used to be TWO assignments to
# this name; the first (which contained bare 'market', 'gas', 'auto', ...) was
# silently overwritten by the second and never took effect. Only this list is
# real — keep it that way.
EXCLUDED_STORE_TERMS = [
    'gas station', 'fuel center', 'fuel station',
    'tire center', 'tire shop', 'auto center',
    'optical', 'vision center',
    'hearing aid', 'hearing center',
    'pharmacy',
    'liquor store',
    # professional services — catches "William S Kroger Attorney", "Karim Meijer MD", etc.
    'attorney', 'law firm', ' law ', 'criminal defense', 'legal',
    ', md', ', do', ', pa', ', dds', ' m.d.', ' d.o.',
    'clinic', 'hospital', 'urgent care', 'medical center',
    'dentist', 'dental', 'orthodont',
    'insurance', 'financial', 'accounting', 'realtor', 'realty',
    'health:', 'health center',  # "Kroger Health:" is a clinic brand
]

# --- API LIMIT CONSTANT ---
# Upper bound on stores carried into pricing + optimisation. The optimiser
# considers routes of at most MAX_STORES_PER_ROUTE stops, so anything beyond
# that is priced (a full network fan-out per store) only to be used as a
# cheaper-single-item source. Keep the two in sight of each other.
MAX_STORES_TO_USE = 10
MAX_STORES_PER_ROUTE = int(os.getenv("MAX_STORES_PER_ROUTE", "3"))

# --- 2. TIME BUDGET ---
# Default only. Per-request budgets are passed explicitly to
# optimizer.find_optimal_store(max_time_seconds=...) — never assigned here at
# request time, which used to let concurrent requests overwrite each other.
SHOPPING_TIME_HOURS = 3.0
MAX_TIME_SECONDS = SHOPPING_TIME_HOURS * 3600

# --- STORE TIME MULTIPLIERS ---
STORE_TIME_MULTIPLIERS: Dict[str, float] = {
    "Aldi": 0.8,
    "Trader Joe's": 0.9,
    "Kroger": 1.0,
    "Meijer": 1.1,
    "Walmart": 1.2,
    "Costco": 1.5,
    "IGA": 0.9,
    "Coles": 1.1,
    "Woolworths": 1.1,
}

# --- AU STORE ID DEFAULTS ---
# Fallback only — coles_pricing.find_nearest_coles_store and
# iga_pricing.find_nearest_iga_store resolve a real store from lat/lon first.
COLES_DEFAULT_STORE_ID = os.getenv("COLES_DEFAULT_STORE_ID", "7674")
IGA_DEFAULT_STORE_ID = os.getenv("IGA_DEFAULT_STORE_ID", "32600")

# --- TIME MODEL CONSTANTS ---
BASE_CHECKOUT_TIME_MINUTES = 7
BASE_PARK_ENTRANCE_TIME_MINUTES = 5
TIME_PER_ITEM_MINUTES = 0  # Reduced since we're buying in bulk for a week

BASE_FIXOUT_OVERHEAD = (BASE_CHECKOUT_TIME_MINUTES + BASE_PARK_ENTRANCE_TIME_MINUTES) * 60
TIME_PER_UNIT_SECONDS = TIME_PER_ITEM_MINUTES * 60
