
import os
from google.cloud import vision
import io

class VisionClient:
    def __init__(self, credentials_path=None):
        """
        Initialize the Cloud Vision client.
        
        Args:
            credentials_path (str, optional): Path to the service account JSON file.
                                            If None, relies on GOOGLE_APPLICATION_CREDENTIALS env var.
        """
        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        
        # We wrap the client creation in a try-except to give a helpful error 
        # if authentication credentials are missing.
        try:
            self.client = vision.ImageAnnotatorClient()
        except Exception as e:
            print(f"Error initializing Cloud Vision client: {e}")
            print("Ensure GOOGLE_APPLICATION_CREDENTIALS is set or passed to the constructor.")
            raise

    def detect_labels(self, image_path: str) -> list[str]:
        """
        Detects labels in the file located in local image_path.
        
        Args:
            image_path (str): The path to the image file.
            
        Returns:
            list[str]: A list of detected label descriptions.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found at {image_path}")

        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()

        image = vision.Image(content=content)

        # different generic features: label_detection, object_localization, etc.
        # The user mentioned "Cloud Vision API returns generic tags like 'vegetable'"
        # so label_detection is the most appropriate mapping.
        response = self.client.label_detection(image=image)
        labels = response.label_annotations

        if response.error.message:
            raise Exception(
                '{}\nFor more info on error messages, check: '
                'https://cloud.google.com/apis/design/errors'.format(
                    response.error.message))

        # Extract just the descriptions (e.g., "Vegetable", "Fruit", "Wood", "Bottle")
        return [label.description for label in labels]

    def detect_objects(self, image_path: str) -> list[str]:
        """
        Detects objects (localized) in the file. 
        This might be more specific than labels but labels usually cover general conceptual tags better.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found at {image_path}")

        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()
        
        image = vision.Image(content=content)
        objects = self.client.object_localization(image=image).localized_object_annotations

        return [obj.name for obj in objects]
