"""
Caching utilities for API responses.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from ..config import CACHE_DIR, CACHE_EXPIRY


def get_cache_path(key: str) -> Path:
    """Get cache file path for a key."""
    hash_key = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"{hash_key}.json"


def cache_get(key: str) -> Optional[Any]:
    """
    Get cached data if it exists and hasn't expired.
    
    Args:
        key: Cache key
        
    Returns:
        Cached value or None if not found/expired
    """
    path = get_cache_path(key)
    
    if not path.exists():
        return None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check expiry
        if 'timestamp' in data:
            cached_time = datetime.fromisoformat(data['timestamp'])
            age_seconds = (datetime.now() - cached_time).total_seconds()
            
            if age_seconds < CACHE_EXPIRY:
                return data.get('value')
        
        # Expired - delete the file
        path.unlink(missing_ok=True)
        return None
        
    except (json.JSONDecodeError, KeyError, ValueError):
        # Corrupted cache file
        path.unlink(missing_ok=True)
        return None


def cache_set(key: str, value: Any) -> bool:
    """
    Set cached data.
    
    Args:
        key: Cache key
        value: Value to cache
        
    Returns:
        True if successfully cached
    """
    path = get_cache_path(key)
    
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'value': value
            }, f, ensure_ascii=False)
        return True
    except (IOError, TypeError):
        return False


def cache_clear(key: str = None) -> int:
    """
    Clear cache entries.
    
    Args:
        key: Specific key to clear, or None to clear all
        
    Returns:
        Number of entries cleared
    """
    if key:
        path = get_cache_path(key)
        if path.exists():
            path.unlink()
            return 1
        return 0
    
    # Clear all
    count = 0
    for path in CACHE_DIR.glob("*.json"):
        try:
            path.unlink()
            count += 1
        except IOError:
            pass
    
    return count
