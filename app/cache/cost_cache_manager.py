"""
Hybrid Cost Cache Manager

Manages cost data caching with a two-tier strategy:
- Current month: Redis (fast, in-memory updates)
- Historical months: PostgreSQL (permanent storage)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from app.cache.redis_cache import get_cache
from app.db.cost_cache_crud import (
    get_cached_costs, 
    save_cost_data, 
    is_month_complete
)

logger = logging.getLogger(__name__)


class HybridCostCache:
    """
    Hybrid cost caching strategy:
    - Historical months → PostgreSQL (immutable)
    - Current month → Redis (frequently updated)
    """
    
    def __init__(self):
        self.redis = get_cache()
    
    def _get_redis_key(self, month: str, user_id: int) -> str:
        """Generate Redis key for cost data."""
        return f"cost:month:{month}:user:{user_id}"
    
    def _is_current_month(self, month: str) -> bool:
        """Check if month is the current month."""
        current_month = datetime.now().strftime("%Y-%m")
        return month == current_month
    
    def get_costs(self, month: str, user_id: int) -> Optional[List[Dict[str, Any]]]:
        """
        Get cost data for a specific month.
        
        Strategy:
        - Current month: Check Redis first, fallback to PostgreSQL
        - Historical month: Check PostgreSQL only
        
        Args:
            month: Month in 'YYYY-MM' format
            user_id: User ID for Redis namespacing
        
        Returns:
            List of cost records or None if not cached
        """
        is_current = self._is_current_month(month)
        
        if is_current:
            # Current month - try Redis first
            logger.debug(f"📊 Checking Redis for current month {month}")
            redis_key = self._get_redis_key(month, user_id)
            cached_data = self.redis.get(redis_key)
            
            if cached_data:
                logger.info(f"✅ Redis HIT for current month {month} (user={user_id})")
                # Parse JSON string back to list of dicts
                return json.loads(cached_data)
            
            logger.debug(f"❌ Redis MISS for current month {month}")
        
        # Historical month OR Redis miss - check PostgreSQL
        logger.debug(f"📊 Checking PostgreSQL for month {month}")
        db_data = get_cached_costs(month)
        
        if db_data:
            logger.info(f"✅ PostgreSQL HIT for month {month}")
            return db_data
        
        logger.debug(f"❌ PostgreSQL MISS for month {month}")
        return None
    
    def save_costs(self, month: str, user_id: int, cost_records: List[Dict[str, Any]]) -> int:
        """
        Save cost data for a specific month.
        
        Strategy:
        - Current month: Save to Redis (with TTL until month end)
        - Historical month: Save to PostgreSQL (permanent, mark complete)
        
        Args:
            month: Month in 'YYYY-MM' format
            user_id: User ID for Redis namespacing
            cost_records: List of cost records
        
        Returns:
            Number of records saved
        """
        is_current = self._is_current_month(month)
        record_count = len(cost_records)
        
        if is_current:
            # Current month - save to Redis
            logger.info(f"💾 Saving {record_count} records to Redis for current month {month}")
            
            # Calculate TTL: days until month ends + 1 day buffer
            today = datetime.now()
            # Get first day of next month
            if today.month == 12:
                next_month_first = datetime(today.year + 1, 1, 1)
            else:
                next_month_first = datetime(today.year, today.month + 1, 1)
            
            days_until_month_end = (next_month_first - today).days + 1
            ttl_seconds = days_until_month_end * 86400  # Convert to seconds
            
            redis_key = self._get_redis_key(month, user_id)
            # Store as JSON string
            self.redis.set(redis_key, json.dumps(cost_records), ttl=ttl_seconds)
            
            logger.info(f"✅ Saved to Redis with TTL={days_until_month_end} days")
            return record_count
        
        else:
            # Historical month - save to PostgreSQL (permanent)
            logger.info(f"💾 Saving {record_count} records to PostgreSQL for historical month {month}")
            saved = save_cost_data(month, cost_records, is_complete=True)
            logger.info(f"✅ Saved to PostgreSQL (marked complete)")
            return saved
    
    def rollover_month(self, month: str, user_id: int) -> bool:
        """
        Move a month's data from Redis to PostgreSQL (called at month end).
        
        This is typically called on the 1st of each month to move
        the previous month from Redis → PostgreSQL.
        
        Args:
            month: Month to rollover (e.g., "2025-10")
            user_id: User ID
        
        Returns:
            True if rollover successful, False if no data in Redis
        """
        logger.info(f"🔄 Rolling over month {month} from Redis → PostgreSQL")
        
        # Get data from Redis
        redis_key = self._get_redis_key(month, user_id)
        cached_data = self.redis.get(redis_key)
        
        if not cached_data:
            logger.warning(f"⚠️ No Redis data found for {month}, skipping rollover")
            return False
        
        # Parse data
        cost_records = json.loads(cached_data)
        logger.info(f"📦 Found {len(cost_records)} records in Redis for {month}")
        
        # Save to PostgreSQL (mark as complete)
        saved = save_cost_data(month, cost_records, is_complete=True)
        
        # Delete from Redis
        self.redis.delete(redis_key)
        
        logger.info(f"✅ Rollover complete: {saved} records moved from Redis → PostgreSQL")
        logger.info(f"🗑️ Deleted Redis key: {redis_key}")
        
        return True
    
    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get cache statistics."""
        from app.db.cost_cache_crud import get_cache_stats
        
        db_stats = get_cache_stats()
        
        # Check if current month is in Redis
        current_month = datetime.now().strftime("%Y-%m")
        redis_key = self._get_redis_key(current_month, user_id)
        redis_data = self.redis.get(redis_key)
        
        return {
            'postgresql': db_stats,
            'redis': {
                'current_month': current_month,
                'has_data': redis_data is not None,
                'records': len(json.loads(redis_data)) if redis_data else 0
            }
        }


# Singleton instance
_cache_manager = None

def get_cost_cache() -> HybridCostCache:
    """Get singleton instance of hybrid cost cache."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = HybridCostCache()
    return _cache_manager

