"""
Cache Utilities

Helper functions for reading and writing job cache files.
"""

import os
from typing import Optional


def get_cache_path(job_id: str, suffix: str, cache_dir: str) -> str:
    """
    Generate the full cache file path.
    
    Args:
        job_id: The job ID
        suffix: File suffix (e.g., ".cache", ".wav")
        cache_dir: Directory for cache files
        
    Returns:
        Full path to cache file
    """
    return os.path.join(cache_dir, f"{job_id}{suffix}")


def cache_exists(job_id: str, suffix: str, cache_dir: str) -> bool:
    """
    Check if a cache file exists for the given job.
    
    Args:
        job_id: The job ID
        suffix: File suffix
        cache_dir: Directory for cache files
        
    Returns:
        True if cache file exists
    """
    path = get_cache_path(job_id, suffix, cache_dir)
    return os.path.exists(path)


def read_cache(path: str) -> Optional[bytes]:
    """
    Read cache file contents.
    
    Args:
        path: Path to cache file
        
    Returns:
        File contents as bytes, or None if file doesn't exist
    """
    if not os.path.exists(path):
        return None
    
    with open(path, 'rb') as f:
        return f.read()


def write_cache(path: str, data: bytes) -> None:
    """
    Write data to cache file.
    
    Creates parent directories if they don't exist.
    
    Args:
        path: Path to cache file
        data: Data to write
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def delete_cache(path: str) -> bool:
    """
    Delete a cache file.
    
    Args:
        path: Path to cache file
        
    Returns:
        True if file was deleted, False if it didn't exist
    """
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
