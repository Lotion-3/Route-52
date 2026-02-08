import csv
import os
from typing import Dict, Any

def load_city_prices_from_csv(csv_path: str = "alanVeggies.csv") -> Dict[str, Dict[str, float]]:
    """
    Loads price data from the CSV file.
    Returns a dictionary structure:
    {
        "CityName": {
            "item_name": price_float,
            ...
        },
        ...
    }
    """
    city_data = {}
    
    # Check if file exists relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, csv_path)
    
    if not os.path.exists(file_path):
        print(f"Error: CSV file not found at {file_path}")
        return {}

    try:
        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # The fieldnames (headers) will give us the list of cities
            # We need to exclude the metadata columns
            metadata_cols = {'Vegetable', 'Form', 'RetailPrice', 'RetailPriceUnit'}
            cities = [col for col in reader.fieldnames if col not in metadata_cols]
            
            # Initialize city dicts
            for city in cities:
                city_data[city] = {}
            
            for row in reader:
                item_name = row['Vegetable'].lower().strip()
                
                # Check for "Form" if needed, but for now just use name
                # (You might want to combine name + form if duplicates exist)
                
                for city in cities:
                    price_str = row.get(city)
                    if price_str and price_str.strip():
                        try:
                            city_data[city][item_name] = float(price_str)
                        except ValueError:
                            pass # Skip invalid prices
                            
    except Exception as e:
        print(f"Error loading CSV data: {e}")
        return {}
        
    return city_data
