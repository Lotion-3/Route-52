
import os
import sys
import argparse
from dotenv import load_dotenv

# Add the parent directory to sys.path so we can import from the prototype package if run from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fridge_scanner_prototype.scanner import FridgeScanner

def main():
    parser = argparse.ArgumentParser(description="Fridge Scanner Prototype Demo")
    parser.add_argument("--image", type=str, required=True, help="Path to the image file to scan")
    parser.add_argument("--env", type=str, default="config.env", help="Path to .env file")
    
    args = parser.parse_args()
    
    # 1. Load Config
    # We look for the env file in the root directory relative to this script
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root_dir, args.env)
    
    print(f"Loading environment from {env_path}")
    load_dotenv(env_path)
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    # For Cloud Vision, usually we check for GOOGLE_APPLICATION_CREDENTIALS in env
    # If the user hasn't set it in config.env, they might have it in their system env
    # but we can try to look for a json file if mentioned in config.env
    
    if not gemini_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    # Check for Vision credentials (optional passed explicitly, or implicitly via env)
    vision_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    # 2. Initialize Scanner
    try:
        scanner = FridgeScanner(gemini_key=gemini_key, vision_creds_path=vision_creds)
    except Exception as e:
        print(f"Failed to initialize scanner: {e}")
        return

    # 3. Run Scan
    if not os.path.exists(args.image):
        print(f"Error: Image file '{args.image}' not found.")
        return

    result = scanner.scan_image(args.image)
    
    # 4. Output Results
    print("\n" + "="*40)
    print("SCAN RESULTS")
    print("="*40)
    import json
    print(json.dumps(result, indent=2))
    print("="*40)

if __name__ == "__main__":
    main()
