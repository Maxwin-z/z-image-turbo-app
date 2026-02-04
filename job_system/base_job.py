"""
Base Job Abstract Class

Defines the interface that all job implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable


class BaseJob(ABC):
    """
    Abstract base class for all job implementations.
    
    Subclasses must implement:
    - generate_job_id(): Generate a unique ID based on job parameters
    - execute(): Perform the actual job work
    
    Optional overrides:
    - get_cache_suffix(): Cache file extension (default: ".cache")
    - should_use_cache(): Whether to use caching (default: True)
    - get_cache_dir(): Directory for cache files (default: "./cache")
    """
    
    def __init__(self, params: Dict[str, Any]):
        """
        Initialize job with parameters.
        
        Args:
            params: Job parameters dictionary
        """
        self.params = params
        self._job_id: Optional[str] = None
        self.on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_status_update: Optional[Callable[[str, Optional[Dict[str, Any]]], None]] = None
    
    @property
    def job_id(self) -> str:
        """Get the job ID, generating it if necessary."""
        if self._job_id is None:
            self._job_id = self.generate_job_id(self.params)
        return self._job_id
    
    @abstractmethod
    def generate_job_id(self, params: Dict[str, Any]) -> str:
        """
        Generate a unique job ID based on parameters.
        
        This ID is used for:
        - Job deduplication
        - Cache file naming
        - Client subscriptions
        
        Args:
            params: Job parameters
            
        Returns:
            Unique job ID string
        """
        pass
    
    @abstractmethod
    async def execute(self) -> Dict[str, Any]:
        """
        Execute the job.
        
        This method should perform the actual work and return results.
        
        Returns:
            Result dictionary that will be sent to subscribers
            
        Raises:
            Exception: Any exception will cause the job to fail
        """
        pass
    
    def update_status(self, status: str, extra_data: Optional[Dict[str, Any]] = None):
        """
        Update the job status.
        
        Args:
            status: New status string
            extra_data: Optional dictionary with extra data to broadcast
        """
        if self.on_status_update:
            self.on_status_update(status, extra_data)
    
    def get_cache_suffix(self) -> str:
        """
        Return the cache file suffix/extension.
        
        Override this to use a different file extension for cached results.
        
        Returns:
            File extension including the dot (e.g., ".cache", ".wav")
        """
        return ".cache"
    
    def should_use_cache(self) -> bool:
        """
        Whether this job should use file-based caching.
        
        Override this to disable caching for certain job types.
        
        Returns:
            True if caching should be used
        """
        return True
    
    def get_cache_dir(self) -> str:
        """
        Return the directory for cache files.
        
        Override this to customize the cache location.
        
        Returns:
            Path to cache directory
        """
        return "./cache"
    
    def serialize_result(self, result: Dict[str, Any]) -> bytes:
        """
        Serialize result for caching.
        
        Override this for custom serialization (e.g., binary files).
        Default implementation uses JSON.
        
        Args:
            result: Result dictionary from execute()
            
        Returns:
            Bytes to write to cache file
        """
        import json
        return json.dumps(result).encode('utf-8')
    
    def deserialize_result(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize cached result.
        
        Override this for custom deserialization.
        Default implementation uses JSON.
        
        Args:
            data: Bytes read from cache file
            
        Returns:
            Result dictionary
        """
        import json
        return json.loads(data.decode('utf-8'))
