"""Simple in-memory cache for cloud provider API responses.

This reduces redundant API calls for data that doesn't change frequently.
Works with any cloud provider (OCI, AWS, Azure, etc.).
"""

import time
from typing import Dict, Any, Optional, Tuple
from threading import Lock


class ResponseCache:
    """Thread-safe cache for API responses with TTL."""
    
    def __init__(self, default_ttl: int = 300):
        """Initialize cache.
        
        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}  # {key: (data, expiry_time)}
        self._lock = Lock()
    
    def _make_key(self, user_id: int, method: str, **kwargs) -> str:
        """Create a cache key from method and parameters."""
        # Sort kwargs for consistent key generation
        params = "&".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{user_id}:{method}:{params}"
    
    def get(self, user_id: int, method: str, **kwargs) -> Optional[Any]:
        """Get cached response if available and not expired.
        
        Args:
            user_id: User ID
            method: Method name (e.g., 'get_cost_data')
            **kwargs: Method parameters
        
        Returns:
            Cached data if available and fresh, None otherwise
        """
        key = self._make_key(user_id, method, **kwargs)
        
        with self._lock:
            if key in self._cache:
                data, expiry = self._cache[key]
                if time.time() < expiry:
                    return data
                else:
                    # Expired, remove it
                    del self._cache[key]
        
        return None
    
    def set(self, user_id: int, method: str, data: Any, ttl: Optional[int] = None, **kwargs):
        """Store response in cache.
        
        Args:
            user_id: User ID
            method: Method name
            data: Data to cache
            ttl: Time-to-live in seconds (uses default if None)
            **kwargs: Method parameters
        """
        key = self._make_key(user_id, method, **kwargs)
        ttl = ttl or self.default_ttl
        expiry = time.time() + ttl
        
        with self._lock:
            self._cache[key] = (data, expiry)
    
    def clear(self, user_id: Optional[int] = None):
        """Clear cache entries.
        
        Args:
            user_id: If provided, only clear entries for this user.
                    If None, clear all entries.
        """
        with self._lock:
            if user_id is None:
                self._cache.clear()
            else:
                # Remove entries for specific user
                prefix = f"{user_id}:"
                keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
                for key in keys_to_remove:
                    del self._cache[key]
    
    def cleanup_expired(self):
        """Remove all expired entries from cache."""
        current_time = time.time()
        with self._lock:
            expired_keys = [k for k, (_, expiry) in self._cache.items() if expiry < current_time]
            for key in expired_keys:
                del self._cache[key]


# Global cache instance (shared across all cloud providers)
_global_cache = ResponseCache(default_ttl=300)  # 5 minutes


def get_cache() -> ResponseCache:
    """Get the global cache instance."""
    return _global_cache

