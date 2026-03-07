from PIL import Image
import numpy as np

# Load the image
img = Image.open('frontend/assets/images/logo.png').convert('RGB')
img_array = np.array(img)

# Define the three target colors
colors = {
    'black': np.array([0, 0, 0]),           # #000000
    'white': np.array([255, 255, 255]),     # #FFFFFF
    'orange': np.array([238, 116, 34])      # #ee7422
}

# Create output image with alpha channel
output = Image.new('RGBA', img.size)
output_array = np.array(output)

# For each pixel, find the closest color
for y in range(img_array.shape[0]):
    for x in range(img_array.shape[1]):
        pixel = img_array[y, x]

        # Calculate distance to each color
        dist_black = np.sum((pixel.astype(float) - colors['black'].astype(float)) ** 2)
        dist_white = np.sum((pixel.astype(float) - colors['white'].astype(float)) ** 2)
        dist_orange = np.sum((pixel.astype(float) - colors['orange'].astype(float)) ** 2)

        # Step 1: Check if pixel is closer to white than to both black and orange
        if dist_white < dist_black and dist_white < dist_orange:
            # Make white transparent
            output_array[y, x] = [255, 255, 255, 0]
        # Step 2: For remaining pixels, choose between orange and black
        elif dist_orange < dist_black:
            output_array[y, x] = [238, 116, 34, 255]
        else:
            output_array[y, x] = [0, 0, 0, 255]

output = Image.fromarray(output_array)
output.save('frontend/assets/images/logo3.png')
print("Logo processed and saved as logo3.png")
