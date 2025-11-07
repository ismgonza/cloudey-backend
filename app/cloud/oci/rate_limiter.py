"""Rate limiting utilities for OCI API calls.

Based on OCI API rate limits: https://docs.oracle.com/en-us/iaas/Content/Identity/sku/api-rate-limiting.htm

For "Others" API group (Identity and Usage APIs):
- Free tier: 20/second, 150/minute
- Premium tier: 90/second, 5000/minute

We'll use conservative limits: 15/second, 120/minute per user to stay safe.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, Tuple


class RateLimiter:
    """Thread-safe rate limiter for API calls per user.
    
    Uses token bucket algorithm with sliding window.
    """
    
    def __init__(self, calls_per_second: int = 15, calls_per_minute: int = 120):
        """Initialize rate limiter.
        
        Args:
            calls_per_second: Maximum API calls per second
            calls_per_minute: Maximum API calls per minute
        """
        self.calls_per_second = calls_per_second
        self.calls_per_minute = calls_per_minute
        
        # Track calls per user: {user_id: [(timestamp, ...), ...]}
        self._user_calls: Dict[int, list] = defaultdict(list)
        self._lock = Lock()
    
    def _cleanup_old_calls(self, user_id: int, current_time: float):
        """Remove calls older than 1 minute from tracking."""
        one_minute_ago = current_time - 60
        self._user_calls[user_id] = [
            ts for ts in self._user_calls[user_id] if ts > one_minute_ago
        ]
    
    def can_make_request(self, user_id: int) -> Tuple[bool, float]:
        """Check if a request can be made, return (allowed, wait_time).
        
        Args:
            user_id: User ID making the request
        
        Returns:
            Tuple of (can_make_request, wait_time_seconds)
        """
        current_time = time.time()
        
        with self._lock:
            # Clean up old calls
            self._cleanup_old_calls(user_id, current_time)
            
            user_calls = self._user_calls[user_id]
            
            # Check per-second limit
            one_second_ago = current_time - 1
            calls_in_last_second = sum(1 for ts in user_calls if ts > one_second_ago)
            
            if calls_in_last_second >= self.calls_per_second:
                # Calculate wait time until oldest call in last second expires
                if user_calls:
                    oldest_in_window = min(ts for ts in user_calls if ts > one_second_ago)
                    wait_time = 1.0 - (current_time - oldest_in_window)
                    return False, max(0.01, wait_time)
                return False, 0.1
            
            # Check per-minute limit
            calls_in_last_minute = len(user_calls)
            if calls_in_last_minute >= self.calls_per_minute:
                # Calculate wait time until oldest call expires
                if user_calls:
                    oldest_call = min(user_calls)
                    wait_time = 60.0 - (current_time - oldest_call)
                    return False, max(0.01, wait_time)
                return False, 1.0
            
            # Can make request
            return True, 0.0
    
    def record_request(self, user_id: int):
        """Record that a request was made."""
        current_time = time.time()
        with self._lock:
            self._user_calls[user_id].append(current_time)
    
    def wait_if_needed(self, user_id: int):
        """Wait if necessary to respect rate limits.
        
        Args:
            user_id: User ID making the request
        
        Returns:
            Time waited in seconds
        """
        wait_time = 0.0
        while True:
            can_make, remaining_wait = self.can_make_request(user_id)
            if can_make:
                break
            
            # Sleep for the wait time
            time.sleep(remaining_wait)
            wait_time += remaining_wait
        
        # Record the request
        self.record_request(user_id)
        return wait_time


# Global rate limiter instance
# OCI free tier limits: 20/sec, 150/min
# Using 18/sec, 140/min to leave some headroom
_global_rate_limiter = RateLimiter(calls_per_second=18, calls_per_minute=140)


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _global_rate_limiter

