from PIL import Image
import numpy as np
import os

output_path = "outputs/result.png"

if not os.path.exists(output_path):
    print(f"FAILURE: File {output_path} does not exist")
    exit(1)

img = Image.open(output_path)
if np.array(img).max() == 0:
    print("FAILURE: Image is all black")
else:
    print("SUCCESS: Image contains content")
