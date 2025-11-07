"""
Monthly Cost Rollover Job

Moves completed month data from Redis → PostgreSQL.
Should be run on the 1st of each month.
"""

import logging
from datetime import datetime, timedelta
from typing import List

from app.cache.cost_cache_manager import get_cost_cache
from app.db import crud

logger = logging.getLogger(__name__)


def rollover_previous_month_for_user(user_id: int) -> bool:
    """
    Rollover previous month's cost data from Redis to PostgreSQL for a specific user.
    
    Args:
        user_id: User ID
    
    Returns:
        True if rollover successful, False otherwise
    """
    # Get previous month (e.g., if today is 2025-11-01, prev month is 2025-10)
    today = datetime.now()
    
    # Calculate first day of previous month
    first_of_current_month = today.replace(day=1)
    last_day_prev_month = first_of_current_month - timedelta(days=1)
    prev_month = last_day_prev_month.strftime("%Y-%m")
    
    logger.info(f"🔄 Starting rollover for user={user_id}, month={prev_month}")
    
    try:
        cache = get_cost_cache()
        success = cache.rollover_month(prev_month, user_id)
        
        if success:
            logger.info(f"✅ Rollover successful for user={user_id}, month={prev_month}")
        else:
            logger.warning(f"⚠️ No data to rollover for user={user_id}, month={prev_month}")
        
        return success
    
    except Exception as e:
        logger.error(f"❌ Rollover failed for user={user_id}, month={prev_month}: {str(e)}", exc_info=True)
        return False


def rollover_all_users() -> dict:
    """
    Rollover previous month's cost data for all users.
    
    This should be scheduled to run on the 1st of each month.
    
    Returns:
        Dictionary with rollover statistics
    """
    today = datetime.now()
    first_of_current_month = today.replace(day=1)
    last_day_prev_month = first_of_current_month - timedelta(days=1)
    prev_month = last_day_prev_month.strftime("%Y-%m")
    
    logger.info("=" * 70)
    logger.info(f"🔄 MONTHLY COST ROLLOVER JOB STARTED")
    logger.info(f"   Month: {prev_month}")
    logger.info(f"   Date: {today.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    # Get all users with OCI configs
    users = crud.get_all_users_with_configs()
    
    if not users:
        logger.warning("⚠️ No users with OCI configs found")
        return {
            'total_users': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
    
    stats = {
        'total_users': len(users),
        'successful': 0,
        'failed': 0,
        'skipped': 0
    }
    
    for user in users:
        user_id = user['id']
        email = user.get('email', 'unknown')
        
        logger.info(f"📦 Processing user {user_id} ({email})...")
        
        try:
            success = rollover_previous_month_for_user(user_id)
            
            if success:
                stats['successful'] += 1
            else:
                stats['skipped'] += 1
        
        except Exception as e:
            logger.error(f"❌ Error processing user {user_id}: {str(e)}")
            stats['failed'] += 1
    
    logger.info("=" * 70)
    logger.info(f"✅ MONTHLY COST ROLLOVER JOB COMPLETED")
    logger.info(f"   Total Users: {stats['total_users']}")
    logger.info(f"   Successful: {stats['successful']}")
    logger.info(f"   Skipped: {stats['skipped']}")
    logger.info(f"   Failed: {stats['failed']}")
    logger.info("=" * 70)
    
    return stats


def get_all_users_with_configs_helper():
    """Helper to get all users with OCI configs."""
    # This is a placeholder - implement based on your DB structure
    from app.db.database import get_db_connection
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT DISTINCT u.id, u.email
            FROM users u
            JOIN oci_configs oc ON u.id = oc.user_id
            ORDER BY u.id
        """)
        
        rows = cursor.fetchall()
        users = [dict(row) for row in rows]
        
        return users
    
    finally:
        conn.close()


# Temporary override for crud function
def _get_all_users_with_configs():
    """Get all users with OCI configs."""
    try:
        return crud.get_all_users_with_configs()
    except AttributeError:
        # If function doesn't exist in crud, use helper
        return get_all_users_with_configs_helper()

