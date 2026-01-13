
import csv
import pandas as pd
from typing import Dict, List, Any
import config

# --- HELPER FUNCTION: Load Available Vegetables ---
def load_available_vegetables() -> Dict[str, List[str]]:
    """
    Load available vegetables from alanVeggies.csv and return a dictionary
    of vegetable -> list of cities where it's available
    """
    print(f"Loading available vegetables from {config.VEGGIES_CSV}...")
    
    veggie_data = {}
    
    try:
        with open(config.VEGGIES_CSV, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            required_columns = ['Vegetable', 'Form', 'RetailPrice', 'RetailPriceUnit']
            if not all(col in reader.fieldnames for col in required_columns):
                print(f"Error: CSV file must have columns: {required_columns}")
                return {}
            
            # Get all city columns
            city_columns = [col for col in reader.fieldnames if col not in required_columns]
            
            for row in reader:
                vegetable = row['Vegetable'].strip().lower()
                form = row['Form'].strip().lower()
                
                # Only consider fresh/raw vegetables
                if form not in ['fresh', 'raw', '']:
                    continue
                
                available_cities = []
                for city in city_columns:
                    price_str = row[city].strip()
                    if price_str and price_str.lower() not in ['', 'na', 'n/a']:
                        try:
                            float(price_str)
                            available_cities.append(city)
                        except ValueError:
                            continue
                
                if available_cities:
                    veggie_data[vegetable] = available_cities
        
        print(f"Loaded {len(veggie_data)} available vegetables.")
        return veggie_data
        
    except FileNotFoundError:
        print(f"Error: CSV file '{config.VEGGIES_CSV}' not found.")
        return {}
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return {}

# --- HELPER FUNCTION: Load Recipes ---
def load_recipes() -> List[Dict[str, Any]]:
    """
    Load recipes from RAW_recipes.csv and parse nutrition data
    """
    print(f"Loading recipes from {config.RECIPES_CSV}...")
    
    recipes = []
    
    try:
        df = pd.read_csv(config.RECIPES_CSV)
        
        # Parse nutrition column (it's a string like '[192.0, 8.0, 22.0, 1.0, 2.0, 0.0]')
        for _, row in df.iterrows():
            try:
                # Parse nutrition string to list
                nutrition_str = str(row['nutrition']).strip('[]')
                nutrition_values = [float(x.strip()) for x in nutrition_str.split(',')]
                
                # Based on common format: [calories, total fat, sugar, sodium, protein, saturated fat]
                if len(nutrition_values) >= 6:
                    recipe = {
                        'name': str(row['name']),
                        'id': str(row['id']),
                        'minutes': int(row['minutes']),
                        'nutrition': {
                            'calories': nutrition_values[0],
                            'total_fat': nutrition_values[1],
                            'sugar': nutrition_values[2],
                            'sodium': nutrition_values[3],
                            'protein': nutrition_values[4],
                            'saturated_fat': nutrition_values[5]
                        },
                        'ingredients': eval(row['ingredients']) if isinstance(row['ingredients'], str) else row['ingredients'],
                        'n_ingredients': int(row['n_ingredients']),
                        'tags': eval(row['tags']) if isinstance(row['ingredients'], str) else row['tags'],
                        'description': str(row['description'])
                    }
                    recipes.append(recipe)
            except Exception as e:
                continue
        
        print(f"Loaded {len(recipes)} recipes with nutrition data.")
        return recipes
        
    except FileNotFoundError:
        print(f"Error: CSV file '{config.RECIPES_CSV}' not found.")
        return []
    except Exception as e:
        print(f"Error reading recipes CSV: {e}")
        return []

# --- PRICE DATABASE FUNCTIONS ---
def load_city_prices_from_csv() -> Dict[str, Dict[str, float]]:
    """Load price data from alanVeggies.csv."""
    city_price_data: Dict[str, Dict[str, float]] = {}
    
    try:
        with open(config.VEGGIES_CSV, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            required_columns = ['Vegetable', 'Form', 'RetailPrice', 'RetailPriceUnit']
            
            if not all(col in reader.fieldnames for col in required_columns):
                print(f"Error: Missing required columns in {config.VEGGIES_CSV}")
                return {}
            
            city_columns = [col for col in reader.fieldnames if col not in required_columns]
            
            for row in reader:
                vegetable = row['Vegetable'].strip().lower()
                form = row['Form'].strip().lower()
                
                if form not in ['fresh', 'raw', '']:
                    continue
                
                for city in city_columns:
                    price_str = row[city].strip()
                    if price_str:
                        try:
                            price = float(price_str)
                            if city not in city_price_data:
                                city_price_data[city] = {}
                            city_price_data[city][vegetable] = price
                        except ValueError:
                            continue
        
        return city_price_data
        
    except Exception as e:
        print(f"Error loading city prices: {e}")
        return {}
