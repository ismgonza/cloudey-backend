"""
CRUD operations for OCI metrics.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from app.db.database import get_db_connection

logger = logging.getLogger(__name__)


def save_resource_metrics(
    user_id: int,
    resource_ocid: str,
    resource_type: str,
    metrics: Dict[str, float],
    period_start: datetime,
    period_end: datetime
) -> int:
    """
    Save metrics for a resource.
    
    Args:
        user_id: User ID
        resource_ocid: Resource OCID
        resource_type: Type of resource ('compute', 'load_balancer')
        metrics: Dictionary of metric_name -> value
        period_start: Start of the measurement period
        period_end: End of the measurement period
    
    Returns:
        Number of metrics saved
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        saved_count = 0
        
        for metric_name, metric_value in metrics.items():
            cursor.execute("""
                INSERT INTO oci_metrics 
                (user_id, resource_ocid, resource_type, metric_name, metric_value, 
                 aggregation_type, period_start, period_end, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (resource_ocid, metric_name, aggregation_type, period_start)
                DO UPDATE SET
                    metric_value = EXCLUDED.metric_value,
                    period_end = EXCLUDED.period_end,
                    fetched_at = NOW()
            """, (
                user_id,
                resource_ocid,
                resource_type,
                metric_name,
                metric_value,
                'mean',
                period_start,
                period_end
            ))
            saved_count += 1
        
        conn.commit()
        logger.debug(f"Saved {saved_count} metrics for {resource_type} {resource_ocid}")
        return saved_count
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving metrics for {resource_ocid}: {str(e)}")
        raise
    finally:
        conn.close()


def get_resource_metrics(
    resource_ocid: str,
    metric_names: Optional[List[str]] = None,
    max_age_hours: int = 24
) -> Dict[str, float]:
    """
    Get cached metrics for a resource.
    
    Args:
        resource_ocid: Resource OCID
        metric_names: Optional list of metric names to filter
        max_age_hours: Maximum age of cached data in hours
    
    Returns:
        Dictionary of metric_name -> value
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        if metric_names:
            placeholders = ','.join(['%s'] * len(metric_names))
            query = f"""
                SELECT metric_name, metric_value
                FROM oci_metrics
                WHERE resource_ocid = %s
                  AND metric_name IN ({placeholders})
                  AND fetched_at >= %s
                ORDER BY fetched_at DESC
            """
            cursor.execute(query, [resource_ocid] + metric_names + [cutoff_time])
        else:
            cursor.execute("""
                SELECT metric_name, metric_value
                FROM oci_metrics
                WHERE resource_ocid = %s
                  AND fetched_at >= %s
                ORDER BY fetched_at DESC
            """, (resource_ocid, cutoff_time))
        
        rows = cursor.fetchall()
        
        # Return the most recent value for each metric
        results = {}
        for row in rows:
            metric_name = row['metric_name']
            if metric_name not in results:
                results[metric_name] = row['metric_value']
        
        return results
        
    except Exception as e:
        logger.error(f"Error fetching metrics for {resource_ocid}: {str(e)}")
        return {}
    finally:
        conn.close()


def get_metrics_for_multiple_resources(
    resource_ocids: List[str],
    resource_type: Optional[str] = None,
    max_age_hours: int = 24
) -> Dict[str, Dict[str, float]]:
    """
    Get cached metrics for multiple resources.
    
    Args:
        resource_ocids: List of resource OCIDs
        resource_type: Optional resource type filter
        max_age_hours: Maximum age of cached data in hours
    
    Returns:
        Dictionary of resource_ocid -> {metric_name -> value}
    """
    if not resource_ocids:
        return {}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        placeholders = ','.join(['%s'] * len(resource_ocids))
        
        if resource_type:
            query = f"""
                SELECT resource_ocid, metric_name, metric_value
                FROM oci_metrics
                WHERE resource_ocid IN ({placeholders})
                  AND resource_type = %s
                  AND fetched_at >= %s
                ORDER BY resource_ocid, metric_name, fetched_at DESC
            """
            cursor.execute(query, resource_ocids + [resource_type, cutoff_time])
        else:
            query = f"""
                SELECT resource_ocid, metric_name, metric_value
                FROM oci_metrics
                WHERE resource_ocid IN ({placeholders})
                  AND fetched_at >= %s
                ORDER BY resource_ocid, metric_name, fetched_at DESC
            """
            cursor.execute(query, resource_ocids + [cutoff_time])
        
        rows = cursor.fetchall()
        
        # Group by resource_ocid and get most recent value for each metric
        results = {}
        for row in rows:
            resource_ocid = row['resource_ocid']
            metric_name = row['metric_name']
            metric_value = row['metric_value']
            
            if resource_ocid not in results:
                results[resource_ocid] = {}
            
            if metric_name not in results[resource_ocid]:
                results[resource_ocid][metric_name] = metric_value
        
        return results
        
    except Exception as e:
        logger.error(f"Error fetching metrics for multiple resources: {str(e)}")
        return {}
    finally:
        conn.close()


def delete_old_metrics(days_to_keep: int = 30) -> int:
    """
    Delete metrics older than the specified number of days.
    
    Args:
        days_to_keep: Number of days to retain metrics
    
    Returns:
        Number of deleted rows
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        cursor.execute("""
            DELETE FROM oci_metrics
            WHERE fetched_at < %s
        """, (cutoff_date,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        
        logger.info(f"Deleted {deleted_count} old metric records (older than {days_to_keep} days)")
        return deleted_count
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting old metrics: {str(e)}")
        raise
    finally:
        conn.close()


def get_metrics_stats(user_id: int) -> Dict[str, any]:
    """
    Get statistics about cached metrics for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary with stats
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                resource_type,
                COUNT(DISTINCT resource_ocid) as resource_count,
                COUNT(*) as metric_count,
                MAX(fetched_at) as last_fetch
            FROM oci_metrics
            WHERE user_id = %s
            GROUP BY resource_type
        """, (user_id,))
        
        rows = cursor.fetchall()
        
        stats = {}
        for row in rows:
            stats[row['resource_type']] = {
                'resource_count': row['resource_count'],
                'metric_count': row['metric_count'],
                'last_fetch': row['last_fetch']
            }
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting metrics stats: {str(e)}")
        return {}
    finally:
        conn.close()

