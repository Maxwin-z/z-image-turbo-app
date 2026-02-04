import asyncio

# Global lock for GPU resources to ensure only one job uses the GPU at a time
# while allowing other jobs (like uploads) to run concurrently.
gpu_lock = asyncio.Lock()
