"""
Job Registry and Queue Management

Manages job registration, creation, execution, and state tracking.
Uses asyncio.Semaphore for concurrency control.
"""

import asyncio
from enum import Enum
from typing import Dict, Type, Any, Optional, Callable, Set
from threading import Lock
import time

from job_system.base_job import BaseJob
from job_system.cache import get_cache_path, cache_exists, read_cache, write_cache


class JobStatus(Enum):
    """Job status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRegistry:
    """
    Singleton registry for job types and active jobs.
    
    Manages:
    - Job type registration
    - Job creation with deduplication
    - Async job execution queue
    - Concurrency control via semaphore
    """
    
    # Class-level storage (singleton pattern)
    _job_types: Dict[str, Type[BaseJob]] = {}
    _jobs: Dict[str, Dict[str, Any]] = {}
    _lock = Lock()
    _semaphore: Optional[asyncio.Semaphore] = None
    _max_concurrency: int = 1
    _broadcast_callback: Optional[Callable[[str, dict], None]] = None
    _cancelled_jobs: Set[str] = set()
    _client_jobs: Dict[str, Set[str]] = {}  # client_id -> set of job_ids
    _initialized = False
    
    @classmethod
    def initialize(cls, max_concurrency: int = 1):
        """Initialize the registry with concurrency settings."""
        cls._max_concurrency = max_concurrency
        cls._initialized = True
    
    @classmethod
    def set_max_concurrency(cls, max_concurrency: int):
        """Set the maximum concurrent job count."""
        cls._max_concurrency = max_concurrency
        # Reset semaphore to apply new limit
        cls._semaphore = None
    
    @classmethod
    def set_broadcast_callback(cls, callback: Callable[[str, dict], None]):
        """
        Set the callback for broadcasting job status updates.
        
        Args:
            callback: Function that takes (job_id, message_dict)
        """
        cls._broadcast_callback = callback
    
    @classmethod
    def register(cls, task_type: str, job_class: Type[BaseJob]):
        """
        Register a job class for a task type.
        
        Args:
            task_type: String identifier for this job type
            job_class: Class that extends BaseJob
        """
        cls._job_types[task_type] = job_class
    
    @classmethod
    def is_registered(cls, task_type: str) -> bool:
        """Check if a task type is registered."""
        return task_type in cls._job_types
    
    @classmethod
    def get_job(cls, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job information by ID."""
        return cls._jobs.get(job_id)

    @classmethod
    def cancel_job(cls, job_id: str) -> bool:
        """
        Mark a job as cancelled.
        
        Returns:
            True if job was found and marked for cancellation
        """
        with cls._lock:
            if job_id in cls._jobs:
                status = cls._jobs[job_id]["status"]
                if status in (JobStatus.PENDING.value, JobStatus.PROCESSING.value):
                    cls._cancelled_jobs.add(job_id)
                    # We can also update status immediately if it's pending (not yet processing)
                    if status == JobStatus.PENDING.value:
                         cls._jobs[job_id]["status"] = JobStatus.CANCELLED.value
                    return True
        return False

    @classmethod
    def is_cancelled(cls, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        return job_id in cls._cancelled_jobs
    
    @classmethod
    async def create_job(cls, task_type: str, params: Dict[str, Any], client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a new job or return existing one.
        
        Handles:
        - Job deduplication (returns existing pending/processing jobs)
        - Cache hits (returns completed immediately)
        - Failed job retry (creates new job)
        
        Args:
            task_type: Registered task type
            params: Job parameters
            client_id: Optional client identifier for ownership tracking
            
        Returns:
            Job info dictionary or None if task_type not found
        """
        if task_type not in cls._job_types:
            return None
        
        job_class = cls._job_types[task_type]
        job_instance = job_class(params)
        job_id = job_instance.job_id
        
        with cls._lock:
            # Check if job already exists
            if job_id in cls._jobs:
                existing_job = cls._jobs[job_id]
                status = existing_job["status"]
                
                # If pending or processing, return existing
                if status in (JobStatus.PENDING.value, JobStatus.PROCESSING.value):
                    print(f"Job {job_id} already exists ({status}), returning existing")
                    return existing_job
                
                # If completed, return cached result
                if status == JobStatus.COMPLETED.value:
                    print(f"Job {job_id} already completed, returning cached")
                    return existing_job
                
                # If failed, allow re-creation (fall through)
                print(f"Job {job_id} previously failed, allowing retry")
            
            # Check file cache if enabled
            if job_instance.should_use_cache():
                cache_path = get_cache_path(
                    job_id,
                    job_instance.get_cache_suffix(),
                    job_instance.get_cache_dir()
                )
                if cache_exists(job_id, job_instance.get_cache_suffix(), job_instance.get_cache_dir()):
                    print(f"Job {job_id} found in file cache")
                    try:
                        cached_data = read_cache(cache_path)
                        if cached_data:
                            result = job_instance.deserialize_result(cached_data)
                            job_entry = {
                                "id": job_id,
                                "task_type": task_type,
                                "params": params,
                                "status": JobStatus.COMPLETED.value,
                                "result": result,
                                "created_at": time.time(),
                                "completed_at": time.time(),
                            }
                            cls._jobs[job_id] = job_entry
                            return job_entry
                    except Exception as e:
                        print(f"Error reading cache for {job_id}: {e}")
            
            # Create new job entry
            job_entry = {
                "id": job_id,
                "task_type": task_type,
                "params": params,
                "status": JobStatus.PENDING.value,
                "result": None,
                "error": None,
                "created_at": time.time(),
                "completed_at": None,
                "client_id": client_id,
            }
            cls._jobs[job_id] = job_entry
            
            # Track job ownership by client_id
            if client_id:
                if client_id not in cls._client_jobs:
                    cls._client_jobs[client_id] = set()
                cls._client_jobs[client_id].add(job_id)
        
        # Schedule execution
        asyncio.create_task(cls._execute_job(job_instance, task_type))
        
        return cls._jobs[job_id]
    
    @classmethod
    async def _execute_job(cls, job: BaseJob, task_type: str):
        """Execute a job with concurrency control."""
        job_id = job.job_id
        
        # Initialize semaphore if needed
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(cls._max_concurrency)
        
        async with cls._semaphore:
            # Update status to processing
            with cls._lock:
                if job_id in cls._jobs:
                    cls._jobs[job_id]["status"] = JobStatus.PROCESSING.value
            
            # Broadcast processing status
            cls._broadcast_status(job_id, JobStatus.PROCESSING.value)
            

            # Set progress callback
            job.on_progress = lambda progress: cls._broadcast_progress(job_id, progress)
            # Set status update callback
            job.on_status_update = lambda s, d: cls._update_job_status(job_id, s, d)
            
            try:
                # Execute the job
                result = await job.execute()
                
                # Check final cancellation state (in case it was cancelled just as it finished)
                if cls.is_cancelled(job_id):
                    raise Exception("Job cancelled by user")

                # Update status to completed
                with cls._lock:
                    if job_id in cls._jobs:
                        cls._jobs[job_id]["status"] = JobStatus.COMPLETED.value
                        cls._jobs[job_id]["result"] = result
                        cls._jobs[job_id]["completed_at"] = time.time()
                
                # Write to cache if enabled
                if job.should_use_cache():
                    try:
                        cache_path = get_cache_path(
                            job_id,
                            job.get_cache_suffix(),
                            job.get_cache_dir()
                        )
                        cache_data = job.serialize_result(result)
                        write_cache(cache_path, cache_data)
                    except Exception as e:
                        print(f"Error writing cache for {job_id}: {e}")
                
                # Broadcast completed status
                cls._broadcast_status(job_id, JobStatus.COMPLETED.value, result=result)
                
            except Exception as e:
                error_msg = str(e)
                print(f"DEBUG: Job {job_id} caught exception: {error_msg}")
                
                # Update status to failed
                with cls._lock:
                    print(f"DEBUG: Updating status in lock for {job_id}")
                    if job_id in cls._jobs:
                        is_cancelled = job_id in cls._cancelled_jobs
                        status = JobStatus.CANCELLED.value if is_cancelled else JobStatus.FAILED.value
                        print(f"DEBUG: Determined status for {job_id}: {status}")
                        
                        cls._jobs[job_id]["status"] = status
                        cls._jobs[job_id]["error"] = error_msg
                        cls._jobs[job_id]["completed_at"] = time.time()
                
                # Broadcast status
                is_cancelled = False
                with cls._lock:
                    is_cancelled = job_id in cls._cancelled_jobs
                
                status = JobStatus.CANCELLED.value if is_cancelled else JobStatus.FAILED.value
                print(f"DEBUG: Final broadcast status for {job_id}: {status}")
                cls._broadcast_status(job_id, status, error=error_msg)
            finally:
                # Cleanup cancellation set
                with cls._lock:
                    if job_id in cls._cancelled_jobs:
                        cls._cancelled_jobs.remove(job_id)
    
    @classmethod
    def _update_job_status(cls, job_id: str, status: str, extra_data: Dict[str, Any] = None):
        """
        Update job status and broadcast update.
        Called by jobs via on_status_update callback.
        """
        with cls._lock:
            if job_id in cls._jobs:
                # Only update if job is not completed/failed/cancelled
                current_status = cls._jobs[job_id]["status"]
                final_statuses = (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)
                
                if current_status not in final_statuses:
                    cls._jobs[job_id]["status"] = status
                    
                    # Merge extra data into the job entry if needed, or just broadcast it
                    # Here we just keep the status updated in the registry
        
        # Broadcast the new status
        cls._broadcast_status(job_id, status, result=extra_data)

    @classmethod
    def _broadcast_status(cls, job_id: str, status: str, result: Dict[str, Any] = None, error: str = None):
        """Broadcast job status update via callback."""
        print(f"DEBUG: Broadcasting status for {job_id}: {status}")
        if cls._broadcast_callback is None:
            print(f"DEBUG: No broadcast callback set!")
            return
        
        message = {
            "type": "job_status",
            "job_id": job_id,
            "status": status,
        }
        
        if result is not None:
            message["result"] = result
        if error is not None:
            message["error"] = error
        
        try:
            cls._broadcast_callback(job_id, message)
        except Exception as e:
            print(f"Error in broadcast callback: {e}")
    
    @classmethod
    def _broadcast_progress(cls, job_id: str, progress: Dict[str, Any]):
        """Broadcast job progress update via callback."""
        if cls._broadcast_callback is None:
            return
        
        message = {
            "type": "job_progress",
            "job_id": job_id,
            "progress": progress,
        }
        
        try:
            cls._broadcast_callback(job_id, message)
        except Exception as e:
            print(f"Error in broadcast callback: {e}")
    
    @classmethod
    def get_client_jobs(cls, client_id: str) -> list:
        """
        Get all jobs for a specific client.
        
        Args:
            client_id: Client identifier
            
        Returns:
            List of job info dictionaries for this client
        """
        with cls._lock:
            job_ids = cls._client_jobs.get(client_id, set())
            return [cls._jobs[job_id].copy() for job_id in job_ids if job_id in cls._jobs]
    
    @classmethod
    def clear_jobs(cls):
        """Clear all jobs (useful for testing)."""
        with cls._lock:
            cls._jobs.clear()
            cls._client_jobs.clear()
    
    @classmethod
    def clear_registrations(cls):
        """Clear all job type registrations (useful for testing)."""
        cls._job_types.clear()
