
import os
import json
import google.generativeai as genai
from typing import List, Dict

class GeminiClient:
    def __init__(self, api_key: str):
        """
        Initialize the Gemini client.
        
        Args:
            api_key (str): The Gemini API key.
        """
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required.")
        
        genai.configure(api_key=api_key)
        
        # Using the Flash model as requested by the user ("Gemini 2.0 Flash")
        # Currently the model name is usually 'gemini-2.0-flash-exp' or 'gemini-flash' depending on release.
        # Fallback to 'gemini-pro' if flash isn't available, but let's try a standard flash alias.
        # Note: 'gemini-2.0-flash-exp' is a common target for new apps.
        self.model_name = 'gemini-2.0-flash-exp' 
        self.model = genai.GenerativeModel(self.model_name)

    def refine_ingredients(self, raw_labels: List[str]) -> Dict:
        """
        Takes a list of raw labels (e.g., ['Vegetable', 'Fruit', 'Red']) and uses Gemini
        to infer specific ingredients/items likely in the fridge.
        
        Args:
            raw_labels (List[str]): List of tags from Cloud Vision.
            
        Returns:
            Dict: JSON structure with categorized ingredients.
        """
        prompt = (
            "You are an intelligent kitchen assistant. "
            "I have a list of raw image tags detected from a fridge photo: \n"
            f"{raw_labels}\n\n"
            "Please analyze these tags and return a JSON object with the following structure:\n"
            "{\n"
            "  \"identified_items\": [ list of specific food items inferred ],\n"
            "  \"categories\": {\n"
            "    \"vegetables\": [],\n"
            "    \"dairy\": [],\n"
            "    \"other\": []\n"
            "  }\n"
            "}\n"
            "If the tags are too generic (like just 'Food' or 'Product'), try to guess the most common fridge staples, "
            "but mark them as 'inferred'. Do not output markdown code blocks, just the JSON string."
        )

        try:
            response = self.model.generate_content(prompt)
            # Simple cleanup to ensure we get pure JSON if the model chats a bit
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:-3].strip()
            elif text.startswith("```"):
                text = text[3:-3].strip()
                
            return json.loads(text)
        except Exception as e:
            print(f"Error calling Gemini: {e}")
            return {"error": str(e), "raw_labels": raw_labels}
