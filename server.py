import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from ws_manager import websocket_router, WebSocketManager, ws_manager
from job_system import JobRegistry
from job_system.jobs.text_to_image_job import TextToImageJob
from env_utils import IS_MACOS
from t2i_model import t2i_model

# --- Pydantic Models for Documentation ---

class HealthResponse(BaseModel):
    status: str = Field(..., example="ok")

class JobStatusResponse(BaseModel):
    type: str = Field(..., example="job_status")
    job_id: str = Field(..., example="hash_of_params")
    status: str = Field(..., example="completed")
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None

# Lifecycle manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Server starting up...")
    
    # Initialize/Warmup Model
    print("Warming up T2I model...")
    t2i_model.get_instance()
    
    # Initialize JobRegistry with desired concurrency
    # We allow multiple concurrent jobs because GPU jobs are locked via gpu_lock,
    # but IObound parts (uploading) can run in parallel.
    JobRegistry.initialize(max_concurrency=4)
    
    # Register jobs
    JobRegistry.register("text_to_image", TextToImageJob)
    
    # Set up broadcast callback
    def broadcast_update(job_id, message):
        # We need to bridge the sync callback to the async websocket manager
        ws_manager.broadcast_to_job_threadsafe(job_id, message)

    JobRegistry.set_broadcast_callback(broadcast_update)
    
    # Set event loop for WebSocketManager to enable thread-safe broadcasts
    loop = asyncio.get_running_loop()
    ws_manager.set_event_loop(loop)
    
    yield
    
    # Shutdown
    print("Server shutting down...")

app = FastAPI(
    title="Z-Image-Turbo Server",
    description="""
A high-performance Text-to-Image generation server using Stable Diffusion and WebSocket-based job management.

### Features:
* **Text-to-Image**: Generate images from text prompts.
* **WebSocket API**: Asynchronous job handling and real-time status updates.
* **Image Delivery**: Static file serving for generated images.
""",
    version="1.0.0",
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include WebSocket router
app.include_router(websocket_router, prefix="/api", tags=["WebSocket"])

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Check the health status of the server.
    Returns 'ok' if the server is running.
    """
    return {"status": "ok"}

# --- API Endpoints ---

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.get(
    "/api/image/{filename}", 
    responses={
        200: {"content": {"image/png": {}}},
        404: {"description": "File not found"}
    },
    tags=["Images"]
)
async def get_image(filename: str):
    """
    Retrieve a generated image by its filename.
    """
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path, media_type="image/png")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8004, reload=IS_MACOS)
