"""
WebSocket Router

FastAPI WebSocket endpoint for job management.
Handles create_job, get_status, and cancel_job messages.
Supports client_id for reconnection with subscription persistence.
"""

from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ws_manager.manager import ws_manager
from job_system import JobRegistry, JobStatus
import json

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: Optional[str] = Query(None, description="Client identifier for reconnection support")
):
    """
    WebSocket endpoint for job management.
    
    Args:
        client_id: Optional client identifier. If provided, subscriptions persist
                   across reconnections with the same client_id.
    
    Supported message types:
    - create_job: Create a new job
    - get_status: Get status of an existing job
    - cancel_job: Cancel a running job
    """
    await ws_manager.connect(websocket, client_id=client_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            print(f"WS Received from client (client_id={client_id}): {data}")
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "create_job":
                    await handle_create_job(websocket, message, client_id)
                elif msg_type == "get_status":
                    await handle_get_status(websocket, message)
                elif msg_type == "cancel_job":
                    await handle_cancel_job(websocket, message)
                elif msg_type == "get_client_jobs":
                    await handle_get_client_jobs(websocket, message, client_id)
                else:
                    await ws_manager.send_to_connection(websocket, {
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    })
            
            except json.JSONDecodeError:
                await ws_manager.send_to_connection(websocket, {
                    "type": "error",
                    "message": "Invalid JSON"
                })
    
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


async def handle_create_job(websocket: WebSocket, message: dict, client_id: Optional[str] = None):
    """Handle create_job message."""
    task_type = message.get("task_type")
    params = message.get("params", {})
    request_id = message.get("request_id") or params.get("request_id")
    
    # Clean params to ensure deduplication works (remove request_id)
    if "request_id" in params:
        params = params.copy()
        del params["request_id"]
    
    if not task_type:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": "Missing task_type"
        })
        return
    
    # Check if task type is registered
    if not JobRegistry.is_registered(task_type):
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": f"Unknown task_type: {task_type}"
        })
        return
    
    # Create job with client_id for ownership tracking
    job_info = await JobRegistry.create_job(task_type, params, client_id=client_id)
    
    if job_info is None:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": "Failed to create job"
        })
        return
    
    job_id = job_info["id"]
    
    # Subscribe this connection to the job
    ws_manager.subscribe(job_id, websocket, request_id=request_id)
    
    # Send job_created response
    response = {
        "type": "job_status",
        "job_id": job_id,
        "status": job_info["status"],
    }
    
    if job_info["status"] == JobStatus.COMPLETED.value:
        response["result"] = job_info.get("result", {})
    elif job_info["status"] == JobStatus.FAILED.value:
        response["error"] = job_info.get("error")
        
    if request_id:
        response["request_id"] = request_id
    
    await ws_manager.send_to_connection(websocket, response)


async def handle_get_status(websocket: WebSocket, message: dict):
    """Handle get_status message."""
    job_id = message.get("job_id")
    request_id = message.get("request_id")
    
    if not job_id:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": "Missing job_id"
        })
        return
    
    # Subscribe to future updates
    ws_manager.subscribe(job_id, websocket, request_id=request_id)
    
    # Get current status
    job_info = JobRegistry.get_job(job_id)
    
    if job_info is None:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": f"Job not found: {job_id}"
        })
        return
    
    response = {
        "type": "job_status",
        "job_id": job_id,
        "status": job_info["status"],
    }
    
    if job_info["status"] == JobStatus.COMPLETED.value:
        response["result"] = job_info.get("result", {})
    elif job_info["status"] == JobStatus.FAILED.value:
        response["error"] = job_info.get("error")
        
    if request_id:
        response["request_id"] = request_id
    
    await ws_manager.send_to_connection(websocket, response)


async def handle_cancel_job(websocket: WebSocket, message: dict):
    """Handle cancel_job message."""
    job_id = message.get("job_id")
    request_id = message.get("request_id")
    
    if not job_id:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": "Missing job_id"
        })
        return
    
    # Try to cancel the job
    success = JobRegistry.cancel_job(job_id)
    
    if success:
        # If successfully marked for cancellation, we don't send a response here.
        # The broadcast from _execute_job will handle notifying everyone about the 'cancelled' status.
        # But we can send an acknowledgement if we want to confirm the request was received.
        pass
    else:
        # Job not found or already in a terminal state
        job_info = JobRegistry.get_job(job_id)
        if job_info:
            await ws_manager.send_to_connection(websocket, {
                "type": "error",
                "message": f"Job {job_id} cannot be cancelled (current status: {job_info['status']})",
                "request_id": request_id
            })
        else:
            await ws_manager.send_to_connection(websocket, {
                "type": "error",
                "message": f"Job not found: {job_id}",
                "request_id": request_id
            })


async def handle_get_client_jobs(websocket: WebSocket, message: dict, client_id: Optional[str] = None):
    """
    Handle get_client_jobs message.
    Returns all jobs for the connected client.
    """
    request_id = message.get("request_id")
    
    if not client_id:
        await ws_manager.send_to_connection(websocket, {
            "type": "error",
            "message": "No client_id associated with this connection",
            "request_id": request_id
        })
        return
    
    # Get all jobs for this client
    jobs = JobRegistry.get_client_jobs(client_id)
    
    # Format response
    jobs_list = []
    for job in jobs:
        job_info = {
            "job_id": job["id"],
            "task_type": job["task_type"],
            "status": job["status"],
            "created_at": job["created_at"],
        }
        if job["status"] == JobStatus.COMPLETED.value:
            job_info["result"] = job.get("result", {})
        elif job["status"] == JobStatus.FAILED.value:
            job_info["error"] = job.get("error")
        jobs_list.append(job_info)
        
        # Re-subscribe to pending/processing jobs
        if job["status"] in (JobStatus.PENDING.value, JobStatus.PROCESSING.value):
            ws_manager.subscribe(job["id"], websocket)
    
    response = {
        "type": "client_jobs",
        "jobs": jobs_list,
    }
    if request_id:
        response["request_id"] = request_id
    
    await ws_manager.send_to_connection(websocket, response)


# Export router for inclusion in main app
websocket_router = router
