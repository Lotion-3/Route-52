from PIL import Image
import numpy as np

# Load logo3.png
img = Image.open('frontend/assets/images/logo3.png').convert('RGBA')
img_array = np.array(img)

height, width = img_array.shape[:2]

# Create output image
output_array = img_array.copy()

# For each pixel, check if it touches a black pixel
for y in range(height):
    for x in range(width):
        # Skip if pixel is transparent
        if img_array[y, x, 3] == 0:  # alpha channel is 0
            continue

        # Check 8 neighbors (including diagonals)
        is_touching_black = False
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                # Check bounds
                if 0 <= ny < height and 0 <= nx < width:
                    neighbor = img_array[ny, nx]
                    # Check if neighbor is black (RGB close to 0,0,0)
                    if neighbor[0] == 0 and neighbor[1] == 0 and neighbor[2] == 0 and neighbor[3] > 0:
                        is_touching_black = True
                        break
            if is_touching_black:
                break

        # If touching black, turn to black
        if is_touching_black:
            output_array[y, x] = [0, 0, 0, 255]

result = Image.fromarray(output_array)
result.save('frontend/assets/images/logo3.png')
print("Black expansion complete")
