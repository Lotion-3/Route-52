import os
import json
from typing import Dict, List, Tuple, Union
from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict

# Initialize the client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# 1. Define a schema that avoids using a Raw Dict
class ItemPrice(BaseModel):
    item_name: str
    price: float

class StoreInventory(BaseModel):
    store_name: str
    items: List[ItemPrice]

class GroceryPricesResponse(BaseModel):
    stores: List[StoreInventory]

def fetch_grocery_prices(
    ingredient_quantities: Dict[str, int], 
    store_names: List[str]
) -> Tuple[Dict[str, Dict[str, float]], List[str], List[Dict[str, Union[str, int]]]]:
    
    print("\n🔍 Searching Google for real-time prices...")
    
    items_list = list(ingredient_quantities.keys())
    # Note: Search grounding works best with a manageable number of stores
    stores_subset = store_names[:8] 
    
    prompt = f"""
    Find the current local prices for these ingredients: {', '.join(items_list)}.
    Check these specific stores: {', '.join(stores_subset)}.
    If exact prices aren't found, estimate based on current market rates in the Indianapolis area.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json",
                response_schema=GroceryPricesResponse, # Using the new List-based schema
            )
        )
        
        # 2. Convert the List-based response back into the Dictionary format the rest of your app expects
        raw_data = response.parsed # SDK automatically parses into the Pydantic model
        price_database = {}
        
        for store in raw_data.stores:
            price_database[store.store_name] = {
                item.item_name: item.price for item in store.items
            }
        
        print(f"✅ Successfully retrieved prices for {len(price_database)} stores.")
        shopping_list = [{"name": item, "qty": qty} for item, qty in ingredient_quantities.items()]
        return price_database, [], shopping_list

    except Exception as e:
        print(f"❌ Error fetching real prices: {e}")
        return {}, items_list, []