import asyncio
import websockets
import json
import time
import httpx
import os
import uuid

async def verify_service():
    # Use ngrok base URL
    base_url = "https://violably-rotund-ouida.ngrok-free.dev/z-image-turbo/"
    # Convert https to wss for websocket
    client_id = str(uuid.uuid4())
    uri = base_url.replace("https://", "wss://") + f"api/ws?client_id={client_id}"
    
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected!")
            
            # 1. Create Job
            prompt = "可爱的泡泡玛特的星星人"
            request_id = f"req_{int(time.time())}"
            
            create_msg = {
                "type": "create_job",
                "task_type": "text_to_image",
                "request_id": request_id,
                "params": {
                    "prompt": prompt,
                    "width": 512, # Smaller for faster test
                    "height": 512,
                    "steps": 4 # Minimal steps for speed
                }
            }
            
            print(f"Sending create_job: {json.dumps(create_msg)}")
            await websocket.send(json.dumps(create_msg))
            
            # 2. Wait for completion
            job_id = None
            result = None
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                print(f"Received: {data}")
                
                if data.get("type") == "job_status":
                     # Check request_id if present
                    if "request_id" in data:
                        assert data["request_id"] == request_id
                    
                    status = data.get("status")
                    if status == "processing":
                        print("Job is processing...")
                    elif status == "completed":
                        print("Job completed!")
                        job_id = data.get("job_id")
                        result = data.get("result")
                        print(f"Result: {result}")
                        break
                    elif status == "failed":
                        print(f"Job failed: {data.get('error')}")
                        break
            
            if job_id and result:
                print("\nVerification Successful!")
                print(f"Generated Job ID: {job_id}")
                
                # 3. Download Image
                download_url_path = result.get("url")
                filename = result.get("filename")
                
                if download_url_path and filename:
                    # Construct full URL (ensuring no double slashes)
                    full_download_url = base_url.rstrip("/") + "/" + download_url_path.lstrip("/")
                    print(f"\nDownloading image from: {full_download_url}")
                    
                    output_dir = "outputs"
                    os.makedirs(output_dir, exist_ok=True)
                    save_path = os.path.join(output_dir, filename)
                    
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(full_download_url)
                        if resp.status_code == 200:
                            with open(save_path, "wb") as f:
                                f.write(resp.content)
                            print(f"Image saved to: {save_path}")
                        else:
                            print(f"Failed to download image: {resp.status_code}")
                else:
                    print("Could not find download URL or filename in result.")
            else:
                 print("\nVerification Failed: Job did not complete successfully.")
                 
    except Exception as e:
        print(f"Connection failed or error occurred: {e}")
        print("Ensure the server is running and accessible at the specified URL.")

if __name__ == "__main__":
    asyncio.run(verify_service())
