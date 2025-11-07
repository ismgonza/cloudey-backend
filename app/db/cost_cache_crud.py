"""
CRUD operations for OCI cost caching.

Stores monthly cost data to avoid repeated API calls for historical months.
"""

import psycopg2
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

from app.db.database import get_db_connection

logger = logging.getLogger(__name__)


def save_cost_data(month: str, cost_records: List[Dict[str, Any]], is_complete: bool = False) -> int:
    """
    Save or update cost data for a specific month.
    
    Args:
        month: Month in 'YYYY-MM' format (e.g., '2025-08')
        cost_records: List of cost records with keys:
            - resource_ocid
            - service
            - cost
        is_complete: If True, marks month as complete (won't refetch)
    
    Returns:
        Number of records saved
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    saved_count = 0
    
    try:
        for record in cost_records:
            cursor.execute("""
                INSERT INTO oci_costs (
                    resource_ocid, service, month, cost,
                    is_complete, last_updated
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(resource_ocid, month) DO UPDATE SET
                    service = excluded.service,
                    cost = excluded.cost,
                    is_complete = excluded.is_complete,
                    last_updated = excluded.last_updated
            """, (
                record['resource_ocid'],
                record['service'],
                month,
                record['cost'],
                is_complete,
                datetime.now().isoformat()
            ))
            saved_count += 1
        
        conn.commit()
        logger.info(f"✅ Saved {saved_count} cost records for {month} (complete={is_complete})")
        return saved_count
    
    except Exception as e:
        logger.error(f"❌ Error saving cost data for {month}: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_cached_costs(month: str) -> Optional[List[Dict[str, Any]]]:
    """
    Get cached cost data for a specific month.
    
    Args:
        month: Month in 'YYYY-MM' format
    
    Returns:
        List of cost records or None if not cached
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT resource_ocid, service, cost, is_complete, last_updated
            FROM oci_costs
            WHERE month = %s
        """, (month,))
        
        rows = cursor.fetchall()
        
        if not rows:
            logger.debug(f"❌ No cached costs found for {month}")
            return None
        
        costs = []
        for row in rows:
            costs.append({
                'resource_ocid': row['resource_ocid'],
                'service': row['service'],
                'cost': row['cost'],
                'is_complete': bool(row['is_complete']),
                'last_updated': row['last_updated']
            })
        
        logger.info(f"✅ Found {len(costs)} cached cost records for {month}")
        return costs
    
    finally:
        conn.close()


def is_month_cached(month: str) -> bool:
    """Check if a month has cached cost data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM oci_costs WHERE month = %s
        """, (month,))
        
        count = cursor.fetchone()[0]
        return count > 0
    
    finally:
        conn.close()


def is_month_complete(month: str) -> bool:
    """Check if a month is marked as complete (immutable)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT is_complete FROM oci_costs 
            WHERE month = %s 
            LIMIT 1
        """, (month,))
        
        row = cursor.fetchone()
        return bool(row['is_complete']) if row else False
    
    finally:
        conn.close()


def mark_month_complete(month: str) -> bool:
    """Mark a month as complete (all historical data finalized)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_costs 
            SET is_complete = TRUE
            WHERE month = %s
        """, (month,))
        
        conn.commit()
        updated = cursor.rowcount
        
        if updated > 0:
            logger.info(f"✅ Marked {month} as complete ({updated} records)")
        
        return updated > 0
    
    finally:
        conn.close()


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about cached cost data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Total cached months
        cursor.execute("""
            SELECT COUNT(DISTINCT month) as total_months,
                   SUM(CASE WHEN is_complete = TRUE THEN 1 ELSE 0 END) as complete_months
            FROM (SELECT DISTINCT month, is_complete FROM oci_costs) as distinct_months
        """)
        row = cursor.fetchone()
        
        # Total records
        cursor.execute("SELECT COUNT(*) as count FROM oci_costs")
        total_records_row = cursor.fetchone()
        total_records = total_records_row['count'] if total_records_row else 0
        
        # Months list
        cursor.execute("""
            SELECT month, COUNT(*) as records, 
                   MAX(is_complete) as is_complete,
                   MAX(last_updated) as last_updated
            FROM oci_costs
            GROUP BY month
            ORDER BY month DESC
        """)
        months = []
        for m_row in cursor.fetchall():
            months.append({
                'month': m_row['month'],
                'records': m_row['records'],
                'is_complete': bool(m_row['is_complete']),
                'last_updated': m_row['last_updated']
            })
        
        return {
            'total_months': row['total_months'] if row else 0,
            'complete_months': row['complete_months'] if row else 0,
            'total_records': total_records,
            'months': months
        }
    
    finally:
        conn.close()


def delete_month_cache(month: str) -> int:
    """Delete cached cost data for a specific month."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM oci_costs WHERE month = %s
        """, (month,))
        
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"🗑️ Deleted {deleted} cost records for {month}")
        return deleted
    
    finally:
        conn.close()


def clear_all_cache() -> int:
    """Clear all cached cost data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM oci_costs")
        conn.commit()
        deleted = cursor.rowcount
        logger.warning(f"🗑️ Cleared ALL cost cache ({deleted} records)")
        return deleted
    
    finally:
        conn.close()

