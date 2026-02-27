import requests, json, random
import pandas as pd
import urllib3
from datetime import datetime

# Suppress insecure request warnings due to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_URL = 'https://flyers-ng.flippback.com/api/flipp/data?locale=en&postal_code={}&sid={}'
FLYER_ITEMS_URL = 'https://flyers-ng.flippback.com/api/flipp/flyers/{}/flyer_items?locale=en&sid={}'

# Stores defined in backend/config.py
STORE_KEYWORDS = ['Walmart', 'Aldi', 'Kroger', 'Target', 'Meijer', 'Whole Foods', "Trader Joe's", 'Trader Joes', 'Costco', 'Jewel Osco']

def generate_sid():
    """Generate a session ID for the Flipp API."""
    return ''.join(str(random.randint(0,9)) for _ in range(16))

def get_flipp_data(postal_code: str):
    """Fetch root flyer and coupon data for a given postal code."""
    sid = generate_sid()
    url = DATA_URL.format(postal_code, sid)
    response = requests.get(url, verify=False)
    response.raise_for_status()
    return response.json()

def get_flyer_items(flyer_id: int):
    """Fetch specific items for a given flyer id."""
    sid = generate_sid()
    url = FLYER_ITEMS_URL.format(flyer_id, sid)
    # verify=False is often helpful for some local python environments when hitting these APIs
    response = requests.get(url, verify=False)
    response.raise_for_status()
    return response.json()

def is_date_active(valid_from_str, valid_to_str):
    """Check if the current time is within the validity period."""
    now = datetime.now()
    try:
        if valid_from_str:
            # Simplify ISO format for naive comparison
            valid_from = datetime.fromisoformat(valid_from_str.split('.')[0])
            if now < valid_from:
                return False
        if valid_to_str:
            valid_to = datetime.fromisoformat(valid_to_str.split('.')[0])
            if now > valid_to:
                return False
    except Exception:
        return True # Fallback to active if parsing fails
    return True

def filter_grocery_flyers(flyers):
    """Filter flyers based on merchant keywords, 'Groceries' category, and active dates."""
    grocery_flyers = []
    for flyer in flyers:
        merchant = flyer.get('merchant', '')
        categories = flyer.get('categories', [])
        if isinstance(categories, str):
            categories = [cat.strip() for cat in categories.split(',')]
        
        # 1. Store Keyword Check
        is_approved_store = any(kw.lower() in merchant.lower() for kw in STORE_KEYWORDS)
        
        # 2. Grocery Category Check
        is_grocery = 'Groceries' in categories
        
        # 3. Active Date Check
        is_active = is_date_active(flyer.get('valid_from'), flyer.get('valid_to'))
        
        if is_approved_store and is_grocery and is_active:
            grocery_flyers.append({
                'id': flyer['id'],
                'merchant': merchant
            })
    return grocery_flyers

def filter_grocery_coupons(coupons):
    """Filter digital coupons tagged with 'Grocery' and currently active."""
    grocery_coupons = []
    for coupon in coupons:
        categories = coupon.get('categories', [])
        
        # Grocery Check
        is_grocery = 'Grocery' in categories
        
        # Active Date Check
        is_active = is_date_active(coupon.get('valid_from'), coupon.get('valid_to'))

        if is_grocery and is_active:
            grocery_coupons.append({
                'brand': coupon.get('brand', ''),
                'savings': coupon.get('sale_story', ''),
                'description': coupon.get('promotion_text', ''),
                'valid_from': coupon.get('valid_from', ''),
                'valid_to': coupon.get('valid_to', ''),
                'image_url': coupon.get('coupon_image_url', '')
            })
    return grocery_coupons

def main():
    while True:
        postal_code = input('Enter your Zip/Postal code (e.g., 46033 or M5V3L9): ').strip().upper()
        if (len(postal_code) == 5 and postal_code.isdigit()) or len(postal_code) == 6:
            break
        print('Invalid format. Please enter a 5-digit Zip Code or A1A1A1 Postal Code.')

    print(f'\nFetching data for postal code: {postal_code}')
    try:
        data = get_flipp_data(postal_code)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    # 1. Process Flyers
    flyers = data.get('flyers', [])
    grocery_flyers = filter_grocery_flyers(flyers)
    print(f'Found {len(grocery_flyers)} approved grocery flyers')

    flyer_csv_data = []
    for flyer in grocery_flyers:
        print(f'Processing {flyer["merchant"]} flyer...')
        try:
            items = get_flyer_items(flyer['id'])
            for item in items:
                flyer_csv_data.append({
                    'merchant': flyer['merchant'],
                    'flyer_id': flyer['id'],
                    'name': item.get('name', ''),
                    'price': item.get('price', ''),
                    'valid_from': item.get('valid_from', ''),
                    'valid_to': item.get('valid_to', '')
                })
        except Exception as e:
            print(f"  Warning: Could not fetch items for {flyer['merchant']}. {e}")

    if flyer_csv_data:
        filename = f'flyer_items_{postal_code}.csv'
        pd.DataFrame(flyer_csv_data).to_csv(filename, index=False)
        print(f'Successfully saved {len(flyer_csv_data)} flyer items to {filename}')
    else:
        print('No flyer items found matching your criteria.')

    # 2. Process Digital Coupons
    coupons = data.get('coupons', [])
    grocery_coupons = filter_grocery_coupons(coupons)
    print(f'Found {len(grocery_coupons)} digital grocery coupons')

    if grocery_coupons:
        filename = f'digital_coupons_{postal_code}.csv'
        pd.DataFrame(grocery_coupons).to_csv(filename, index=False)
        print(f'Successfully saved {len(grocery_coupons)} coupons to {filename}')

if __name__ == '__main__':
    main()
