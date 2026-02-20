import requests
import json

def test_health_integration():
    url = "http://localhost:8000/generate_plan"
    payload = {
        "preferences": {
            "address": "New York, NY",
            "budget": 150.0,
            "calorie_target": 2000,
            "days_plan": 7,
            "meals_per_day": 3,
            "health_issues": "Heart Disease, Hypertension",
            "dietary_restrictions": "None",
            "cuisines": "Any",
            "fridge_items": "eggs",
            "experiment": True,
            "cook_time": "30 minutes"
        }
    }
    
    print("Testing generate_plan with Ingredients-First flow and strict matching...")
    try:
        response = requests.post(url, json=payload, timeout=300)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print("Successfully received meal plan!")
            
            at_home_list = data.get("at_home_ingredients", [])
            at_home_names = [ing["name"] for ing in at_home_list]
            
            print(f"At-home ingredients found: {at_home_names}")
            
            if "Large Brown Eggs" in at_home_names:
                print("✅ Found EXACT at-home ingredient match for 'Large Brown Eggs'!")
            else:
                print(f"⚠️ 'Large Brown Eggs' not found in at-home list. System found: {at_home_names}")
                
            meal_plan = data.get("meal_plan", [])
            if meal_plan:
                # Check for duplication across ingredients in the first meal
                first_meal_ings = [i["name"] for i in meal_plan[0]["ingredients"]]
                print(f"Ingredients in first meal: {first_meal_ings}")
                if "Large Brown Eggs" in first_meal_ings:
                    print("✅ Step 2 used the exact string from Step 1!")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Could not connect to server: {e}")

if __name__ == "__main__":
    test_health_integration()
