
import os
from typing import Dict, Any

from .vision_client import VisionClient
from .gemini_client import GeminiClient

class FridgeScanner:
    def __init__(self, gemini_key: str, vision_creds_path: str = None):
        """
        Orchestrates the scanning process.
        """
        print("Initializing Vision Client...")
        self.vision = VisionClient(credentials_path=vision_creds_path)
        
        print("Initializing Gemini Client...")
        self.gemini = GeminiClient(api_key=gemini_key)

    def scan_image(self, image_path: str) -> Dict[str, Any]:
        """
        Full pipeline: Image -> Vision Tags -> Gemini Refinement -> Result
        """
        print(f"--- Step 1: Scanning image '{image_path}' with Cloud Vision ---")
        try:
            # We get both labels and objects for better context
            labels = self.vision.detect_labels(image_path)
            objects = self.vision.detect_objects(image_path)
            
            combined_tags = list(set(labels + objects))
            print(f"Detected Tags: {combined_tags}")
        except Exception as e:
            return {"error": f"Vision API failed: {str(e)}"}

        print(f"--- Step 2: Refining tags with Gemini ---")
        try:
            refined_data = self.gemini.refine_ingredients(combined_tags)
            print("Gemini Refinement Complete.")
            return refined_data
        except Exception as e:
            return {"error": f"Gemini API failed: {str(e)}", "raw_tags": combined_tags}
