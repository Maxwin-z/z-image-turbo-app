
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch
from PIL import Image

# Add current directory to path
sys.path.append(os.getcwd())

# Mock t2i_model before importing the job
sys.modules["t2i_model"] = MagicMock()
from t2i_model import t2i_model

# Setup the mock to return a small image that NEEDS upscaling
def mock_generate_image(*args, **kwargs):
    print("Mock generating image (256x256)...")
    return Image.new("RGB", (256, 256), color="green")

t2i_model.generate_image = mock_generate_image
t2i_model.unload_model = MagicMock()

# Now import the job class
from job_system.jobs.text_to_image_job import TextToImageJob

async def test_job_flow():
    print("Testing TextToImageJob integration with Upscaler...")
    
    # Create a job instance
    params = {
        "prompt": "test prompt for upscaling",
        "width": 256,
        "height": 256
    }
    job = TextToImageJob(params)
    
    # Execute
    print("Executing job...")
    result = await job.execute()
    
    print("Job Result:", result)
    
    # Verify content
    if "upscaled_url" in result and result["upscaled_url"]:
        print("SUCCESS: upscaled_url is present.")
        print(f"Original: {result['url']}")
        print(f"Upscaled: {result['upscaled_url']}")
        
        # Check files exist
        if os.path.exists(result["path"]):
            print(f"Original file exists: {result['path']}")
        else:
            print("FAILURE: Original file missing.")
            
        # We need to construct the absolute path for upscaled to check
        # The result only gives URL for upscaled (in my implementation logic), 
        # but let's check the directory based on the logic.
        output_dir = "outputs"
        upscaled_filename = result["upscaled_url"].split("/")[-1]
        upscaled_path = os.path.join(output_dir, upscaled_filename)
        
        if os.path.exists(upscaled_path):
            print(f"Upscaled file exists: {upscaled_path}")
            # Verify size
            img = Image.open(upscaled_path)
            print(f"Upscaled image size: {img.size}")
            if img.size[0] >= 1024:
                print("SUCCESS: Image size is correct.")
            else:
                print("FAILURE: Image size is too small.")
        else:
            print(f"FAILURE: Upscaled file missing at {upscaled_path}")
            
    else:
        print("FAILURE: upscaled_url is missing or empty.")

    # Verify unload_model was called
    if t2i_model.unload_model.called:
        print("SUCCESS: t2i_model.unload_model() was called.")
    else:
        print("FAILURE: t2i_model.unload_model() was NOT called.")

if __name__ == "__main__":
    asyncio.run(test_job_flow())
