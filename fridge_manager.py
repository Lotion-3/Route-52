import os
from typing import List
from google import genai
from google.genai import types
from PIL import Image

def analyze_fridge_image(image_path: str) -> str:
    """
    Analyzes an image of a fridge and returns a list of detected ingredients.
    """
    if not os.path.exists(image_path):
        print(f"❌ Image not found at {image_path}. Skipping fridge analysis.")
        return ""

    print(f"\n🔍 Analyzing fridge contents from '{image_path}'...")
    
    try:
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_V"))
        
        # Read image
        try:
            pil_image = Image.open(image_path)
        except Exception as e:
            print(f"❌ Error opening image: {e}")
            return ""

        prompt = (
            "Analyze this image of a fridge or pantry. "
            "List all the distinct food ingredients you can identify. "
            "Return ONLY a comma-separated list of items (e.g. 'eggs, milk, carrots'). "
            "Do not include quantities or explanatory text."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, pil_image],
            config=types.GenerateContentConfig(
                response_mime_type="text/plain",
            )
        )
        
        ingredients = response.text.strip()
        print(f"✅ Found in fridge: {ingredients}")
        return ingredients

    except Exception as e:
        print(f"❌ Error analyzing fridge image: {e}")
        return ""
