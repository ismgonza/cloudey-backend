"""
Background job scheduler for resource synchronization.

Handles:
- Initial sync on application startup
- Periodic sync every 12 hours
- Manual sync triggers
"""

import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta

from app.cloud.oci.resource_sync import sync_all_users

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def sync_all_users_job():
    """
    Background job to sync resources for all users.
    Runs on startup and every 12 hours.
    """
    logger.info("🔄 Starting scheduled resource sync for all users")
    start_time = datetime.now()
    
    try:
        results = await sync_all_users()
        
        # Log summary
        success_count = sum(1 for r in results.values() if 'error' not in r)
        error_count = len(results) - success_count
        
        duration = (datetime.now() - start_time).total_seconds()
        
        logger.info(
            f"✅ Scheduled sync complete: "
            f"{success_count} users synced successfully, "
            f"{error_count} errors, "
            f"duration: {duration:.2f}s"
        )
        
        return results
    
    except Exception as e:
        logger.error(f"❌ Error in scheduled sync job: {str(e)}", exc_info=True)
        raise


def start_scheduler():
    """
    Start the background scheduler.
    
    Jobs:
    - Sync all users' resources every 12 hours
    - Initial sync on startup (after 30 seconds delay)
    """
    scheduler = get_scheduler()
    
    if scheduler.running:
        logger.warning("⚠️ Scheduler is already running")
        return
    
    try:
        # Add job: Sync every 12 hours
        scheduler.add_job(
            sync_all_users_job,
            trigger=IntervalTrigger(hours=12),
            id='sync_all_users_12h',
            name='Sync all users resources (every 12 hours)',
            replace_existing=True,
            max_instances=1,  # Only one instance running at a time
            coalesce=True,    # Combine missed runs
        )
        
        # Add job: Initial sync on startup (after 30 seconds)
        scheduler.add_job(
            sync_all_users_job,
            trigger='date',
            run_date=datetime.now() + timedelta(seconds=30),  # Run after 30 seconds
            id='sync_all_users_startup',
            name='Initial resource sync on startup',
            replace_existing=True,
        )
        
        scheduler.start()
        logger.info("✅ Background scheduler started")
        logger.info("📅 Resource sync will run:")
        logger.info("   - On startup (in 30 seconds)")
        logger.info("   - Every 12 hours thereafter")
        
    except Exception as e:
        logger.error(f"❌ Error starting scheduler: {str(e)}", exc_info=True)
        raise


def stop_scheduler():
    """Stop the background scheduler."""
    scheduler = get_scheduler()
    
    if not scheduler.running:
        logger.warning("⚠️ Scheduler is not running")
        return
    
    try:
        scheduler.shutdown(wait=True)
        logger.info("✅ Background scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping scheduler: {str(e)}", exc_info=True)
        raise


def get_scheduler_status() -> dict:
    """
    Get current scheduler status and job information.
    
    Returns:
        Dictionary with scheduler status
    """
    scheduler = get_scheduler()
    
    jobs_info = []
    for job in scheduler.get_jobs():
        jobs_info.append({
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger),
        })
    
    return {
        'running': scheduler.running,
        'jobs': jobs_info,
        'state': scheduler.state
    }

