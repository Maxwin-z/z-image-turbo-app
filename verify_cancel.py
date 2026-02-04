import asyncio
import websockets
import json
import time

import uuid

async def test_cancellation():
    client_id = str(uuid.uuid4())
    uri = f"ws://localhost:8004/api/ws?client_id={client_id}"
    async with websockets.connect(uri) as websocket:
        # 1. Create a job with many steps so we have time to cancel
        create_msg = {
            "type": "create_job",
            "task_type": "text_to_image",
            "params": {
                "prompt": "a beautiful landscape, cinematic lighting, 8k",
                "steps": 25,
                "seed": 12345
            },
            "request_id": "test_req_001"
        }
        print(f"Sending: {json.dumps(create_msg)}")
        await websocket.send(json.dumps(create_msg))
        
        job_id = None
        
        # 2. Wait for job_status and get job_id
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            print(f"Received: {data}")
            
            if data.get("type") == "job_status":
                job_id = data.get("job_id")
                if data.get("status") == "processing" or data.get("status") == "pending":
                    break
            
            if data.get("type") == "job_progress":
                # If we get progress, we definitely have a job_id
                job_id = data.get("job_id")
                break

        if not job_id:
            print("Failed to get job_id")
            return

        # 3. Wait for some progress (e.g., 2 steps)
        print("Waiting for some progress...")
        steps_seen = 0
        while steps_seen < 2:
            response = await websocket.recv()
            data = json.loads(response)
            if data.get("type") == "job_progress":
                steps_seen = data["progress"].get("current_step", 0)
                print(f"Progress: {steps_seen} steps")

        # 4. Send cancellation
        cancel_msg = {
            "type": "cancel_job",
            "job_id": job_id,
            "request_id": "cancel_req_001"
        }
        print(f"Sending Cancellation: {json.dumps(cancel_msg)}")
        await websocket.send(json.dumps(cancel_msg))
        
        # 5. Verify we get a 'cancelled' status
        # Note: Each diffusion step can take 20+ seconds on MPS, so we need to wait longer
        start_wait = time.time()
        cancelled_received = False
        while time.time() - start_wait < 60: # Wait up to 60 seconds for slow diffusion
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                data = json.loads(response)
                print(f"Received after cancel: {data}")
                
                if data.get("type") == "job_status" and data.get("status") == "cancelled":
                    print("SUCCESS: Received cancelled status!")
                    cancelled_received = True
                    break
            except asyncio.TimeoutError:
                continue

        if not cancelled_received:
            print("FAILED: Did not receive cancelled status within timeout")

if __name__ == "__main__":
    try:
        asyncio.run(test_cancellation())
    except Exception as e:
        print(f"Error: {e}")
