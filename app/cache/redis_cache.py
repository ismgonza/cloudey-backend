"""Generic Redis caching utility for Cloudey.

Provides a reusable caching layer for dashboard data and other expensive operations.
"""

import json
import logging
import hashlib
from typing import Any, Optional, Callable
from functools import wraps
from datetime import datetime, timedelta

try:
    import redis
    from redis.exceptions import RedisError
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CacheKeyPrefixes:
    """Cache key prefixes for organizing cached data."""
    
    PREFIX_DASHBOARD = "dashboard"
    PREFIX_COST = "cost"
    PREFIX_RESOURCE = "resource"
    PREFIX_OPTIMIZATION = "optimization"
    PREFIX_PRICING = "pricing"
    PREFIX_COMPARTMENT = "compartment"


class RedisCache:
    """Redis-based cache with connection pooling and fallback to no-cache."""
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        """Initialize Redis cache.
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
        """
        self.enabled = False
        self.client = None
        
        if not REDIS_AVAILABLE:
            logger.warning("Redis library not installed. Caching disabled. Install with: pip install redis")
            return
        
        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
                health_check_interval=30
            )
            # Test connection
            self.client.ping()
            self.enabled = True
            logger.info(f"✅ Redis cache connected: {host}:{port}")
        except (RedisError, Exception) as e:
            logger.warning(f"Redis connection failed: {str(e)}. Caching disabled.")
            self.client = None
            self.enabled = False
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate a unique cache key.
        
        Args:
            prefix: Key prefix (e.g., 'dashboard', 'cost')
            *args: Positional arguments to include in key
            **kwargs: Keyword arguments to include in key
        
        Returns:
            Cache key string
        """
        # Create a deterministic string from args and kwargs
        key_parts = [str(arg) for arg in args]
        key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
        key_string = ":".join(key_parts)
        
        # Hash long keys to keep them manageable
        if len(key_string) > 100:
            key_hash = hashlib.md5(key_string.encode()).hexdigest()[:16]
            return f"cloudey:{prefix}:{key_hash}"
        
        return f"cloudey:{prefix}:{key_string}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        """
        if not self.enabled:
            return None
        
        try:
            value = self.client.get(key)
            if value:
                logger.debug(f"🎯 Cache HIT: {key}")
                return json.loads(value)
            logger.debug(f"❌ Cache MISS: {key}")
            return None
        except (RedisError, json.JSONDecodeError) as e:
            logger.error(f"Cache get error for {key}: {str(e)}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        
        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            json_value = json.dumps(value)
            self.client.setex(key, ttl, json_value)
            logger.debug(f"💾 Cache SET: {key} (TTL: {ttl}s)")
            return True
        except (RedisError, TypeError, json.JSONEncodeError) as e:
            logger.error(f"Cache set error for {key}: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if deleted
        """
        if not self.enabled:
            return False
        
        try:
            result = self.client.delete(key)
            logger.debug(f"🗑️ Cache DELETE: {key}")
            return bool(result)
        except RedisError as e:
            logger.error(f"Cache delete error for {key}: {str(e)}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern.
        
        Args:
            pattern: Key pattern (e.g., 'cloudey:dashboard:*')
        
        Returns:
            Number of keys deleted
        """
        if not self.enabled:
            return 0
        
        try:
            keys = self.client.keys(pattern)
            if keys:
                deleted = self.client.delete(*keys)
                logger.info(f"🗑️ Cache DELETE PATTERN: {pattern} ({deleted} keys)")
                return deleted
            return 0
        except RedisError as e:
            logger.error(f"Cache delete pattern error for {pattern}: {str(e)}")
            return 0
    
    def clear_user_cache(self, user_id: int) -> int:
        """Clear all cache for a specific user.
        
        Args:
            user_id: User ID
        
        Returns:
            Number of keys deleted
        """
        pattern = f"cloudey:*:*user_id={user_id}*"
        return self.delete_pattern(pattern)
    
    def clear_dashboard_cache(self, user_id: Optional[int] = None) -> int:
        """Clear dashboard cache for a user or all users.
        
        Args:
            user_id: User ID (if None, clears all dashboard caches)
        
        Returns:
            Number of keys deleted
        """
        if user_id:
            pattern = f"cloudey:{CacheKeyPrefixes.PREFIX_DASHBOARD}:*user_id={user_id}*"
        else:
            pattern = f"cloudey:{CacheKeyPrefixes.PREFIX_DASHBOARD}:*"
        return self.delete_pattern(pattern)
    
    def get_stats(self) -> dict:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        if not self.enabled:
            return {"enabled": False}
        
        try:
            info = self.client.info("stats")
            memory = self.client.info("memory")
            return {
                "enabled": True,
                "total_keys": self.client.dbsize(),
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "memory_used_mb": round(memory.get("used_memory", 0) / 1024 / 1024, 2),
                "hit_rate": round(
                    info.get("keyspace_hits", 0) / 
                    (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1)) * 100,
                    2
                )
            }
        except RedisError as e:
            logger.error(f"Error getting cache stats: {str(e)}")
            return {"enabled": True, "error": str(e)}


# Global cache instance
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get or create the global cache instance.
    
    Returns:
        RedisCache instance
    """
    global _cache_instance
    if _cache_instance is None:
        from app.sysconfig import CacheConfig as Config
        _cache_instance = RedisCache(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB
        )
    return _cache_instance


def cached(prefix: str, ttl: int = 300):
    """Decorator for caching function results.
    
    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
    
    Example:
        @cached(prefix="dashboard", ttl=300)
        def get_dashboard_data(user_id: int):
            # expensive operation
            return data
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, force_refresh: bool = False, **kwargs):
            cache = get_cache()
            
            # Generate cache key from function args (excluding force_refresh from key)
            func_kwargs = {k: v for k, v in kwargs.items() if k != 'force_refresh'}
            cache_key = cache._generate_key(prefix, func.__name__, *args, **func_kwargs)
            
            logger.debug(f"🔑 Cache key: {cache_key}")
            logger.debug(f"🔄 Force refresh: {force_refresh}")
            
            # Check cache unless force_refresh
            if not force_refresh:
                cached_value = cache.get(cache_key)
                if cached_value is not None:
                    logger.info(f"⚡ Using cached result (TTL: {ttl}s)")
                    return cached_value
            else:
                logger.info(f"🔄 Force refresh requested, bypassing cache")
            
            # Call function and cache result
            logger.info(f"💾 Generating fresh data and caching (TTL: {ttl}s)")
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, force_refresh: bool = False, **kwargs):
            cache = get_cache()
            
            # Generate cache key from function args
            cache_key = cache._generate_key(prefix, func.__name__, *args, **kwargs)
            
            # Check cache unless force_refresh
            if not force_refresh:
                cached_value = cache.get(cache_key)
                if cached_value is not None:
                    return cached_value
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        
        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator

