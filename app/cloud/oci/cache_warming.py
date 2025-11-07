"""Cache warming utilities for OCI data.

Pre-fetches commonly accessed data to improve initial query performance.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import asyncio

from app.cloud.oci.usage_api_client import UsageApiClient
from app.cloud.oci.compartment import CompartmentClient

logger = logging.getLogger(__name__)


async def warm_user_cache(user_id: int) -> dict:
    """Pre-fetch common OCI data for a user to warm the cache.
    
    This runs in the background after user uploads OCI config or logs in.
    Silently fails if any operation fails (best effort).
    
    Args:
        user_id: User ID to warm cache for
    
    Returns:
        Dictionary with warming results
    """
    results = {
        "compartments": False,
        "last_month_costs": False,
        "current_month_costs": False
    }
    
    try:
        # Run cache warming in executor to avoid blocking
        logger.info(f"Starting cache warming for user_id={user_id}")
        
        # Create clients once and reuse
        comp_client = None
        usage_client = None
        
        # 1. Fetch compartments list (quick, commonly used)
        try:
            comp_client = CompartmentClient(user_id)
            await asyncio.to_thread(comp_client.list_compartments)
            results["compartments"] = True
            logger.debug(f"Warmed compartments cache for user_id={user_id}")
        except Exception as e:
            logger.warning(f"Failed to warm compartments cache: {str(e)}")
        
        # 2. Fetch last month's costs (historical data, cached for 1 hour)
        try:
            if not usage_client:
                usage_client = UsageApiClient(user_id)
            tenancy_id = usage_client.config["tenancy"]
            
            # Calculate last month dates
            today = datetime.now()
            first_of_this_month = today.replace(day=1)
            last_month_end = first_of_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            
            start_date = last_month_start.strftime("%Y-%m-%d")
            end_date = last_month_end.strftime("%Y-%m-%d")
            
            await asyncio.to_thread(
                usage_client.get_cost_data,
                tenancy_id,
                start_date,
                end_date
            )
            results["last_month_costs"] = True
            logger.debug(f"Warmed last month costs cache for user_id={user_id}")
        except Exception as e:
            logger.warning(f"Failed to warm last month costs cache: {str(e)}")
        
        # 3. Fetch current month costs (recent data, cached for 5 min)
        try:
            if not usage_client:
                usage_client = UsageApiClient(user_id)
            tenancy_id = usage_client.config["tenancy"]
            
            # Calculate current month dates
            today = datetime.now()
            first_of_month = today.replace(day=1)
            
            start_date = first_of_month.strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")
            
            await asyncio.to_thread(
                usage_client.get_cost_data,
                tenancy_id,
                start_date,
                end_date
            )
            results["current_month_costs"] = True
            logger.debug(f"Warmed current month costs cache for user_id={user_id}")
        except Exception as e:
            logger.warning(f"Failed to warm current month costs cache: {str(e)}")
        
        warmed_count = sum(results.values())
        logger.info(f"Cache warming completed for user_id={user_id}: {warmed_count}/3 successful")
        
    except Exception as e:
        logger.error(f"Cache warming failed for user_id={user_id}: {str(e)}")
    
    return results


def start_cache_warming_background(user_id: int):
    """Start cache warming in background (fire and forget).
    
    Args:
        user_id: User ID to warm cache for
    """
    try:
        asyncio.create_task(warm_user_cache(user_id))
        logger.info(f"Started background cache warming for user_id={user_id}")
    except Exception as e:
        logger.warning(f"Failed to start cache warming: {str(e)}")

