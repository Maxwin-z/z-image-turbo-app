
import os
import sys
from PIL import Image

# Ensure current dir is in path to find the upscaler helper
sys.path.append(os.getcwd())

try:
    from upscaler import upscaler
    print("Upscaler module imported successfully.")
except Exception as e:
    print(f"Failed to import upscaler: {e}")
    sys.exit(1)

# Create a dummy image (small rectangular)
img = Image.new('RGB', (512, 1024), color = 'red')
print(f"Created test image: {img.size}")

# Test upscaling
try:
    print("Attempting upscale...")
    upscaled = upscaler.upscale_image(img)
    if upscaled:
        print(f"Upscaled image size: {upscaled.size}")
        # Expecting 1024x2048 (min dim 1024)
        if upscaled.size == (1024, 2048):
            print("SUCCESS: Image upscaled to exactly 1024x2048")
        else:
            print(f"FAILURE: Image size is {upscaled.size}, expected (1024, 2048).")
    else:
        print("FAILURE: Upscaler returned None")

    # Test no upscale needed
    img_large = Image.new('RGB', (1024, 1024), color = 'blue')
    print(f"Created large test image: {img_large.size}")
    result = upscaler.upscale_image(img_large)
    if result is None:
        print("SUCCESS: Large image was not upscaled.")
    else:
        print(f"FAILURE: Large image WAS upscaled to {result.size}")

except Exception as e:
    print(f"Error during execution: {e}")
    import traceback
    traceback.print_exc()
