"""
CRUD operations for normalized OCI resource tables.

Tables:
- oci_compartments (master)
- oci_compute
- oci_volumes
- oci_buckets

Note: Uses PostgreSQL syntax (%s placeholders, not %s)
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

from app.db.database import get_db_connection

logger = logging.getLogger(__name__)


# ===== COMPARTMENT CRUD =====

def upsert_compartment(user_id: int, compartment_data: Dict[str, Any]) -> bool:
    """Create or update a compartment."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_compartments (
                ocid, user_id, name, description, lifecycle_state,
                time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                lifecycle_state = excluded.lifecycle_state,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            compartment_data['ocid'],
            user_id,
            compartment_data['name'],
            compartment_data.get('description'),
            compartment_data.get('lifecycle_state'),
            compartment_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting compartment {compartment_data.get('ocid')}: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_compartment_deleted(ocid: str) -> bool:
    """Mark compartment as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_compartments 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_compartment(ocid: str) -> Optional[Dict[str, Any]]:
    """Get compartment by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_compartments WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_compartments(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all compartments for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT * FROM oci_compartments WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT * FROM oci_compartments WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ===== INSTANCE CRUD =====

def upsert_instance(user_id: int, instance_data: Dict[str, Any]) -> bool:
    """Create or update a compute instance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_compute (
                ocid, user_id, compartment_ocid, display_name, shape,
                lifecycle_state, availability_domain, vcpus, memory_in_gbs,
                region, time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                shape = excluded.shape,
                lifecycle_state = excluded.lifecycle_state,
                availability_domain = excluded.availability_domain,
                vcpus = excluded.vcpus,
                memory_in_gbs = excluded.memory_in_gbs,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            instance_data['ocid'],
            user_id,
            instance_data['compartment_ocid'],
            instance_data['display_name'],
            instance_data.get('shape'),
            instance_data.get('lifecycle_state'),
            instance_data.get('availability_domain'),
            instance_data.get('vcpus'),
            instance_data.get('memory_in_gbs'),
            instance_data.get('region'),
            instance_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting instance {instance_data.get('ocid')}: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_instance_deleted(ocid: str) -> bool:
    """Mark instance as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_compute 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_instance(ocid: str) -> Optional[Dict[str, Any]]:
    """Get instance by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_compute WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===== VOLUME CRUD =====

def upsert_volume(user_id: int, volume_data: Dict[str, Any]) -> bool:
    """Create or update a block volume."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_volumes (
                ocid, user_id, compartment_ocid, display_name, size_in_gbs,
                lifecycle_state, availability_domain, region,
                time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                size_in_gbs = excluded.size_in_gbs,
                lifecycle_state = excluded.lifecycle_state,
                availability_domain = excluded.availability_domain,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            volume_data['ocid'],
            user_id,
            volume_data['compartment_ocid'],
            volume_data['display_name'],
            volume_data.get('size_in_gbs'),
            volume_data.get('lifecycle_state'),
            volume_data.get('availability_domain'),
            volume_data.get('region'),
            volume_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting volume {volume_data.get('ocid')}: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_volume_deleted(ocid: str) -> bool:
    """Mark volume as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_volumes 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_volume(ocid: str) -> Optional[Dict[str, Any]]:
    """Get volume by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_volumes WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===== BUCKET CRUD =====

def upsert_bucket(user_id: int, bucket_data: Dict[str, Any]) -> bool:
    """Create or update an object storage bucket."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_buckets (
                ocid, user_id, compartment_ocid, name, namespace,
                region, time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                name = excluded.name,
                namespace = excluded.namespace,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            bucket_data['ocid'],
            user_id,
            bucket_data['compartment_ocid'],
            bucket_data['name'],
            bucket_data.get('namespace'),
            bucket_data.get('region'),
            bucket_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting bucket {bucket_data.get('ocid')}: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_bucket_deleted(ocid: str) -> bool:
    """Mark bucket as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_buckets 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_bucket(ocid: str) -> Optional[Dict[str, Any]]:
    """Get bucket by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_buckets WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ===== FILE STORAGE CRUD =====

def upsert_file_storage(user_id: int, fs_data: Dict[str, Any]) -> bool:
    """Create or update a file storage system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_file_storage (
                ocid, user_id, compartment_ocid, display_name, metered_bytes,
                lifecycle_state, availability_domain, region,
                time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                metered_bytes = excluded.metered_bytes,
                lifecycle_state = excluded.lifecycle_state,
                availability_domain = excluded.availability_domain,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            fs_data['id'],
            user_id,
            fs_data['compartment_id'],
            fs_data['display_name'],
            fs_data.get('metered_bytes'),
            fs_data.get('lifecycle_state'),
            fs_data.get('availability_domain'),
            fs_data.get('region'),
            fs_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting file storage: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def mark_file_storage_deleted(ocid: str) -> bool:
    """Mark a file storage system as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_file_storage 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error marking file storage as deleted: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_file_storage(ocid: str) -> Optional[Dict[str, Any]]:
    """Get a file storage system by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_file_storage WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_file_storage_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all file storage systems for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, metered_bytes, lifecycle_state,
                       availability_domain, region, compartment_ocid, is_deleted
                FROM oci_file_storage
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, metered_bytes, lifecycle_state,
                       availability_domain, region, compartment_ocid, is_deleted
                FROM oci_file_storage
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ===== DATABASE CRUD =====

def upsert_database(user_id: int, db_data: Dict[str, Any]) -> bool:
    """Create or update an Oracle database system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_database (
                ocid, user_id, compartment_ocid, display_name, db_system_shape,
                database_edition, lifecycle_state, availability_domain,
                cpu_core_count, data_storage_size_in_gbs, region,
                time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                db_system_shape = excluded.db_system_shape,
                database_edition = excluded.database_edition,
                lifecycle_state = excluded.lifecycle_state,
                availability_domain = excluded.availability_domain,
                cpu_core_count = excluded.cpu_core_count,
                data_storage_size_in_gbs = excluded.data_storage_size_in_gbs,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            db_data['id'],
            user_id,
            db_data['compartment_id'],
            db_data['display_name'],
            db_data.get('shape'),
            db_data.get('database_edition'),
            db_data.get('lifecycle_state'),
            db_data.get('availability_domain'),
            db_data.get('cpu_core_count'),
            db_data.get('data_storage_size_in_gbs'),
            db_data.get('region'),
            db_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting database: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def mark_database_deleted(ocid: str) -> bool:
    """Mark a database system as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_database 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error marking database as deleted: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_database(ocid: str) -> Optional[Dict[str, Any]]:
    """Get a database system by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_database WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_databases_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all database systems for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, db_system_shape, database_edition,
                       lifecycle_state, availability_domain, cpu_core_count,
                       data_storage_size_in_gbs, region, compartment_ocid, is_deleted
                FROM oci_database
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, db_system_shape, database_edition,
                       lifecycle_state, availability_domain, cpu_core_count,
                       data_storage_size_in_gbs, region, compartment_ocid, is_deleted
                FROM oci_database
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ===== POSTGRESQL DATABASE CRUD =====

def upsert_postgresql(user_id: int, psql_data: Dict[str, Any]) -> bool:
    """Create or update a PostgreSQL database system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO oci_database_psql (
                ocid, user_id, compartment_ocid, display_name, shape,
                instance_count, storage_details_iops, storage_details_size_in_gbs,
                lifecycle_state, region, time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                shape = excluded.shape,
                instance_count = excluded.instance_count,
                storage_details_iops = excluded.storage_details_iops,
                storage_details_size_in_gbs = excluded.storage_details_size_in_gbs,
                lifecycle_state = excluded.lifecycle_state,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            psql_data['id'],
            user_id,
            psql_data['compartment_id'],
            psql_data['display_name'],
            psql_data.get('shape'),
            psql_data.get('instance_count'),
            psql_data.get('storage_details_iops'),
            psql_data.get('storage_details_size_in_gbs'),
            psql_data.get('lifecycle_state'),
            psql_data.get('region'),
            psql_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting PostgreSQL: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def mark_postgresql_deleted(ocid: str) -> bool:
    """Mark a PostgreSQL system as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_database_psql 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error marking PostgreSQL as deleted: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_postgresql(ocid: str) -> Optional[Dict[str, Any]]:
    """Get a PostgreSQL system by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_database_psql WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_postgresql_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all PostgreSQL systems for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, shape, instance_count,
                       storage_details_iops, storage_details_size_in_gbs,
                       lifecycle_state, region, compartment_ocid, is_deleted
                FROM oci_database_psql
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, shape, instance_count,
                       storage_details_iops, storage_details_size_in_gbs,
                       lifecycle_state, region, compartment_ocid, is_deleted
                FROM oci_database_psql
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ===== LOAD BALANCER CRUD =====

def upsert_load_balancer(user_id: int, lb_data: Dict[str, Any]) -> bool:
    """Create or update a load balancer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        import json
        
        cursor.execute("""
            INSERT INTO oci_load_balancer (
                ocid, user_id, compartment_ocid, display_name, shape_name,
                is_private, ip_addresses, lifecycle_state, region,
                time_created, last_seen_date, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT(ocid) DO UPDATE SET
                compartment_ocid = excluded.compartment_ocid,
                display_name = excluded.display_name,
                shape_name = excluded.shape_name,
                is_private = excluded.is_private,
                ip_addresses = excluded.ip_addresses,
                lifecycle_state = excluded.lifecycle_state,
                region = excluded.region,
                last_seen_date = excluded.last_seen_date,
                is_deleted = FALSE
        """, (
            lb_data['id'],
            user_id,
            lb_data['compartment_id'],
            lb_data['display_name'],
            lb_data.get('shape_name'),
            lb_data.get('is_private'),
            json.dumps(lb_data.get('ip_addresses', [])),
            lb_data.get('lifecycle_state'),
            lb_data.get('region'),
            lb_data.get('time_created'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error upserting load balancer: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def mark_load_balancer_deleted(ocid: str) -> bool:
    """Mark a load balancer as deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE oci_load_balancer 
            SET is_deleted = TRUE
            WHERE ocid = %s
        """, (ocid,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error marking load balancer as deleted: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_load_balancer(ocid: str) -> Optional[Dict[str, Any]]:
    """Get a load balancer by OCID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM oci_load_balancer WHERE ocid = %s
        """, (ocid,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_load_balancers_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all load balancers for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, shape_name, is_private,
                       ip_addresses, lifecycle_state, region,
                       compartment_ocid, is_deleted
                FROM oci_load_balancer
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, shape_name, is_private,
                       ip_addresses, lifecycle_state, region,
                       compartment_ocid, is_deleted
                FROM oci_load_balancer
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ===== GENERIC RESOURCE LOOKUP =====

def get_resource_by_ocid(ocid: str) -> Optional[Dict[str, Any]]:
    """
    Generic lookup: Find resource by OCID across all tables.
    Returns resource with 'resource_type' field added.
    """
    # Determine resource type from OCID
    if not ocid or not ocid.startswith('ocid1.'):
        return None
    
    parts = ocid.split('.')
    if len(parts) < 2:
        return None
    
    resource_type = parts[1]
    
    # Query the appropriate table based on OCID type
    if resource_type == 'instance':
        resource = get_instance(ocid)
        if resource:
            resource['resource_type'] = 'instance'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type in ('volume', 'volumebackup', 'bootvolume'):
        resource = get_volume(ocid)
        if resource:
            resource['resource_type'] = 'volume'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type == 'bucket':
        resource = get_bucket(ocid)
        if resource:
            resource['resource_type'] = 'bucket'
            resource['resource_name'] = resource['name']
        return resource
    
    elif resource_type == 'filesystem':
        resource = get_file_storage(ocid)
        if resource:
            resource['resource_type'] = 'file_storage'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type == 'dbsystem':
        resource = get_database(ocid)
        if resource:
            resource['resource_type'] = 'database'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type == 'postgresqldbsystem':
        resource = get_postgresql(ocid)
        if resource:
            resource['resource_type'] = 'database_psql'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type == 'loadbalancer':
        resource = get_load_balancer(ocid)
        if resource:
            resource['resource_type'] = 'load_balancer'
            resource['resource_name'] = resource['display_name']
        return resource
    
    elif resource_type == 'compartment':
        resource = get_compartment(ocid)
        if resource:
            resource['resource_type'] = 'compartment'
            resource['resource_name'] = resource['name']
        return resource
    
    # Resource type not supported yet (but cost data may exist)
    return None


# ===== SYNC STATISTICS =====

def get_all_instances_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all compute instances for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, shape, lifecycle_state, availability_domain,
                       vcpus, memory_in_gbs, region, compartment_ocid, is_deleted
                FROM oci_compute
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, shape, lifecycle_state, availability_domain,
                       vcpus, memory_in_gbs, region, compartment_ocid, is_deleted
                FROM oci_compute
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        instances = []
        for row in rows:
            instances.append({
                'ocid': row['ocid'],
                'display_name': row['display_name'],
                'shape': row['shape'],
                'lifecycle_state': row['lifecycle_state'],
                'availability_domain': row['availability_domain'],
                'vcpus': row['vcpus'],
                'memory_in_gbs': row['memory_in_gbs'],
                'region': row['region'],
                'compartment_ocid': row['compartment_ocid'],
                'is_deleted': bool(row['is_deleted'])
            })
        return instances
    finally:
        conn.close()


def get_all_volumes_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all block volumes for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, size_in_gbs, lifecycle_state, availability_domain,
                       region, compartment_ocid, is_deleted
                FROM oci_volumes
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, size_in_gbs, lifecycle_state, availability_domain,
                       region, compartment_ocid, is_deleted
                FROM oci_volumes
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        volumes = []
        for row in rows:
            volumes.append({
                'ocid': row['ocid'],
                'display_name': row['display_name'],
                'size_in_gbs': row['size_in_gbs'],
                'lifecycle_state': row['lifecycle_state'],
                'availability_domain': row['availability_domain'],
                'region': row['region'],
                'compartment_ocid': row['compartment_ocid'],
                'is_deleted': bool(row['is_deleted'])
            })
        return volumes
    finally:
        conn.close()


def get_all_buckets_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all object storage buckets for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, name, namespace, region, compartment_ocid, is_deleted
                FROM oci_buckets
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, name, namespace, region, compartment_ocid, is_deleted
                FROM oci_buckets
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        buckets = []
        for row in rows:
            buckets.append({
                'ocid': row['ocid'],
                'name': row['name'],
                'namespace': row['namespace'],
                'region': row['region'],
                'compartment_ocid': row['compartment_ocid'],
                'is_deleted': bool(row['is_deleted'])
            })
        return buckets
    finally:
        conn.close()


def get_all_compartments_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all compartments for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, name, description, lifecycle_state, time_created, is_deleted
                FROM oci_compartments
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, name, description, lifecycle_state, time_created, is_deleted
                FROM oci_compartments
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        compartments = []
        for row in rows:
            compartments.append({
                'ocid': row['ocid'],
                'name': row['name'],
                'description': row['description'],
                'lifecycle_state': row['lifecycle_state'],
                'time_created': row['time_created'],
                'is_deleted': bool(row['is_deleted'])
            })
        return compartments
    finally:
        conn.close()


def get_all_load_balancers_for_user(user_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all load balancers for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if include_deleted:
            cursor.execute("""
                SELECT ocid, display_name, shape_name, is_private, lifecycle_state, 
                       compartment_ocid, is_deleted
                FROM oci_load_balancer
                WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT ocid, display_name, shape_name, is_private, lifecycle_state, 
                       compartment_ocid, is_deleted
                FROM oci_load_balancer
                WHERE user_id = %s AND is_deleted = FALSE
            """, (user_id,))
        
        rows = cursor.fetchall()
        load_balancers = []
        for row in rows:
            load_balancers.append({
                'ocid': row['ocid'],
                'display_name': row['display_name'],
                'shape_name': row['shape_name'],
                'is_private': row['is_private'],
                'lifecycle_state': row['lifecycle_state'],
                'compartment_ocid': row['compartment_ocid'],
                'is_deleted': bool(row['is_deleted'])
            })
        return load_balancers
    finally:
        conn.close()


def get_sync_stats(user_id: int) -> Dict[str, Any]:
    """Get sync statistics across all resource types."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Compartments
        cursor.execute("""
            SELECT COUNT(*) as total, MAX(last_seen_date) as last_sync
            FROM oci_compartments WHERE user_id = %s AND is_deleted = FALSE
        """, (user_id,))
        comp_stats = dict(cursor.fetchone())
        
        # Instances
        cursor.execute("""
            SELECT COUNT(*) as count FROM oci_compute 
            WHERE user_id = %s AND is_deleted = FALSE
        """, (user_id,))
        instances_count = cursor.fetchone()['count']
        
        # Volumes
        cursor.execute("""
            SELECT COUNT(*) as count FROM oci_volumes 
            WHERE user_id = %s AND is_deleted = FALSE
        """, (user_id,))
        volumes_count = cursor.fetchone()['count']
        
        # Buckets
        cursor.execute("""
            SELECT COUNT(*) as count FROM oci_buckets 
            WHERE user_id = %s AND is_deleted = FALSE
        """, (user_id,))
        buckets_count = cursor.fetchone()['count']
        
        total_resources = instances_count + volumes_count + buckets_count
        
        return {
            'total_resources': total_resources,
            'active_resources': total_resources,
            'compartments': comp_stats['total'],
            'instances': instances_count,
            'volumes': volumes_count,
            'buckets': buckets_count,
            'last_sync_date': comp_stats['last_sync']
        }
    finally:
        conn.close()
