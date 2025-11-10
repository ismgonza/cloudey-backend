"""
OCI Resource Synchronization Module - Normalized Schema.

Syncs resources to normalized tables:
- oci_compartments (master)
- oci_compute
- oci_volumes
- oci_buckets
- oci_file_storage
- oci_database
- oci_database_psql
- oci_load_balancer
"""

import logging
from typing import Dict, List, Any, Set
from datetime import datetime

from app.cloud.oci.compartment import CompartmentClient
from app.cloud.oci.compute import ComputeClient
from app.cloud.oci.block_storage import BlockStorageClient
from app.cloud.oci.object_storage import ObjectStorageClient
from app.cloud.oci.file_storage import FileStorageClient
from app.cloud.oci.database import DatabaseClient
from app.cloud.oci.postgresql import PostgresqlClient
from app.cloud.oci.load_balancer import LoadBalancerClient
from app.db.resource_crud import (
    upsert_compartment,
    upsert_instance,
    upsert_volume,
    upsert_bucket,
    upsert_file_storage,
    upsert_database,
    upsert_postgresql,
    upsert_load_balancer,
    mark_compartment_deleted,
    mark_instance_deleted,
    mark_volume_deleted,
    mark_bucket_deleted,
    mark_file_storage_deleted,
    mark_database_deleted,
    mark_postgresql_deleted,
    mark_load_balancer_deleted,
    get_all_compartments,
    get_sync_stats
)

logger = logging.getLogger(__name__)


async def sync_user_resources(user_id: int, force: bool = False) -> Dict[str, int]:
    """
    Sync resources from OCI to normalized local database.
    
    Process:
    1. Sync compartments first (master table)
    2. Sync instances, volumes, buckets (referencing compartments)
    3. Mark missing resources as deleted
    
    Args:
        user_id: User ID
        force: Force full sync even if recently synced
    
    Returns:
        Dictionary with sync statistics
    """
    logger.info(f"🔄 Starting normalized resource sync for user {user_id} (force={force})")
    start_time = datetime.now()
    
    stats = {
        'compartments': {'new': 0, 'updated': 0, 'deleted': 0},
        'instances': {'new': 0, 'updated': 0, 'deleted': 0},
        'volumes': {'new': 0, 'updated': 0, 'deleted': 0},
        'buckets': {'new': 0, 'updated': 0, 'deleted': 0},
        'file_systems': {'new': 0, 'updated': 0, 'deleted': 0},
        'databases': {'new': 0, 'updated': 0, 'deleted': 0},
        'postgresql_systems': {'new': 0, 'updated': 0, 'deleted': 0},
        'load_balancers': {'new': 0, 'updated': 0, 'deleted': 0},
    }
    
    try:
        # Initialize clients
        compartment_client = CompartmentClient(user_id)
        compute_client = ComputeClient(user_id)
        block_storage_client = BlockStorageClient(user_id)
        object_storage_client = ObjectStorageClient(user_id)
        file_storage_client = FileStorageClient(user_id)
        database_client = DatabaseClient(user_id)
        postgresql_client = PostgresqlClient(user_id)
        load_balancer_client = LoadBalancerClient(user_id)
        
        region = compartment_client.config.get('region', 'us-ashburn-1')
        
        # ===== STEP 1: SYNC COMPARTMENTS =====
        logger.info("📦 Step 1: Syncing compartments...")
        
        oci_compartments = compartment_client.list_compartments(include_root=True)
        oci_compartment_ocids = set(comp['id'] for comp in oci_compartments)
        
        # Get existing compartments from DB
        db_compartments = get_all_compartments(user_id, include_deleted=False)
        db_compartment_ocids = set(comp['ocid'] for comp in db_compartments)
        
        # Upsert compartments
        for comp in oci_compartments:
            comp_data = {
                'ocid': comp['id'],
                'name': comp['name'],
                'description': comp.get('description'),
                'lifecycle_state': comp.get('lifecycle_state'),
                'time_created': comp.get('time_created')
            }
            upsert_compartment(user_id, comp_data)
            
            if comp['id'] in db_compartment_ocids:
                stats['compartments']['updated'] += 1
            else:
                stats['compartments']['new'] += 1
        
        # Mark deleted compartments
        deleted_comp_ocids = db_compartment_ocids - oci_compartment_ocids
        for ocid in deleted_comp_ocids:
            mark_compartment_deleted(ocid)
            stats['compartments']['deleted'] += 1
        
        logger.info(f"✅ Compartments: {stats['compartments']}")
        
        # ===== STEP 2: SYNC INSTANCES =====
        logger.info("💻 Step 2: Syncing compute instances...")
        
        oci_compute = {}
        for comp in oci_compartments:
            try:
                instances = compute_client.list_instances(comp['id'])
                for inst in instances:
                    oci_compute[inst['id']] = {
                        'ocid': inst['id'],
                        'compartment_ocid': comp['id'],
                        'display_name': inst['display_name'],
                        'shape': inst.get('shape'),
                        'lifecycle_state': inst.get('lifecycle_state'),
                        'availability_domain': inst.get('availability_domain'),
                        'vcpus': inst.get('vcpus'),  # Added
                        'memory_in_gbs': inst.get('memory_in_gbs'),  # Added
                        'region': region,
                        'time_created': inst.get('time_created')
                    }
                logger.debug(f"  ✅ Found {len(instances)} instances in {comp['name']}")
            except Exception as e:
                logger.warning(f"  ⚠️ Error fetching instances from {comp['name']}: {str(e)}")
        
        # Get existing instances from DB
        from app.db.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_compute WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_instance_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert instances
        for ocid, inst_data in oci_compute.items():
            upsert_instance(user_id, inst_data)
            if ocid in db_instance_ocids:
                stats['instances']['updated'] += 1
            else:
                stats['instances']['new'] += 1
        
        # Mark deleted instances
        deleted_inst_ocids = db_instance_ocids - set(oci_compute.keys())
        for ocid in deleted_inst_ocids:
            mark_instance_deleted(ocid)
            stats['instances']['deleted'] += 1
        
        logger.info(f"✅ Instances: {stats['instances']}")
        
        # ===== STEP 3: SYNC VOLUMES =====
        logger.info("💾 Step 3: Syncing block volumes...")
        
        oci_volumes = {}
        for comp in oci_compartments:
            try:
                volumes = block_storage_client.list_volumes(comp['id'])
                for vol in volumes:
                    oci_volumes[vol['id']] = {
                        'ocid': vol['id'],
                        'compartment_ocid': comp['id'],
                        'display_name': vol['display_name'],
                        'size_in_gbs': vol.get('size_in_gbs'),
                        'lifecycle_state': vol.get('lifecycle_state'),
                        'availability_domain': vol.get('availability_domain'),
                        'region': region,
                        'time_created': vol.get('time_created')
                    }
                logger.debug(f"  ✅ Found {len(volumes)} volumes in {comp['name']}")
            except Exception as e:
                logger.warning(f"  ⚠️ Error fetching volumes from {comp['name']}: {str(e)}")
        
        # Get existing volumes from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_volumes WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_volume_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert volumes
        for ocid, vol_data in oci_volumes.items():
            upsert_volume(user_id, vol_data)
            if ocid in db_volume_ocids:
                stats['volumes']['updated'] += 1
            else:
                stats['volumes']['new'] += 1
        
        # Mark deleted volumes
        deleted_vol_ocids = db_volume_ocids - set(oci_volumes.keys())
        for ocid in deleted_vol_ocids:
            mark_volume_deleted(ocid)
            stats['volumes']['deleted'] += 1
        
        logger.info(f"✅ Volumes: {stats['volumes']}")
        
        # ===== STEP 4: SYNC BUCKETS =====
        logger.info("🪣 Step 4: Syncing object storage buckets...")
        
        oci_buckets = {}
        for comp in oci_compartments:
            try:
                buckets = object_storage_client.list_buckets(comp['id'])
                for bucket in buckets:
                    # Create pseudo-OCID for buckets
                    bucket_ocid = f"ocid1.bucket.oc1..{bucket['name']}"
                    oci_buckets[bucket_ocid] = {
                        'ocid': bucket_ocid,
                        'compartment_ocid': comp['id'],
                        'name': bucket['name'],
                        'namespace': bucket.get('namespace'),
                        'region': region,
                        'time_created': bucket.get('time_created')
                    }
                logger.debug(f"  ✅ Found {len(buckets)} buckets in {comp['name']}")
            except Exception as e:
                logger.warning(f"  ⚠️ Error fetching buckets from {comp['name']}: {str(e)}")
        
        # Get existing buckets from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_buckets WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_bucket_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert buckets
        for ocid, bucket_data in oci_buckets.items():
            upsert_bucket(user_id, bucket_data)
            if ocid in db_bucket_ocids:
                stats['buckets']['updated'] += 1
            else:
                stats['buckets']['new'] += 1
        
        # Mark deleted buckets
        deleted_bucket_ocids = db_bucket_ocids - set(oci_buckets.keys())
        for ocid in deleted_bucket_ocids:
            mark_bucket_deleted(ocid)
            stats['buckets']['deleted'] += 1
        
        logger.info(f"✅ Buckets: {stats['buckets']}")
        
        # ===== STEP 5: SYNC FILE STORAGE =====
        logger.info("📁 Step 5: Syncing file storage systems...")
        
        # Get availability domains for file storage
        from oci import identity
        identity_client = identity.IdentityClient(compartment_client.config)
        tenancy_id = compartment_client.config['tenancy']
        availability_domains = []
        try:
            ad_response = identity_client.list_availability_domains(tenancy_id)
            availability_domains = [ad.name for ad in ad_response.data]
            logger.debug(f"  📍 Found {len(availability_domains)} availability domains")
        except Exception as e:
            logger.warning(f"  ⚠️ Error fetching availability domains: {str(e)}")
        
        oci_file_systems = {}
        for comp in oci_compartments:
            for ad in availability_domains:
                try:
                    file_systems = file_storage_client.list_file_systems(comp['id'], ad)
                    for fs in file_systems:
                        oci_file_systems[fs['id']] = {
                            'id': fs['id'],
                            'compartment_id': comp['id'],
                            'display_name': fs['display_name'],
                            'metered_bytes': fs.get('metered_bytes'),
                            'lifecycle_state': fs.get('lifecycle_state'),
                            'availability_domain': fs.get('availability_domain'),
                            'region': region,
                            'time_created': fs.get('time_created')
                        }
                    if file_systems:
                        logger.debug(f"  ✅ Found {len(file_systems)} file systems in {comp['name']} ({ad})")
                except Exception as e:
                    logger.debug(f"  ⚠️ Error fetching file systems from {comp['name']} ({ad}): {str(e)}")
        
        # Get existing file systems from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_file_storage WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_fs_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert file systems
        for ocid, fs_data in oci_file_systems.items():
            upsert_file_storage(user_id, fs_data)
            if ocid in db_fs_ocids:
                stats['file_systems']['updated'] += 1
            else:
                stats['file_systems']['new'] += 1
        
        # Mark deleted file systems
        deleted_fs_ocids = db_fs_ocids - set(oci_file_systems.keys())
        for ocid in deleted_fs_ocids:
            mark_file_storage_deleted(ocid)
            stats['file_systems']['deleted'] += 1
        
        logger.info(f"✅ File Systems: {stats['file_systems']}")
        
        # ===== STEP 6: SYNC ORACLE DATABASES =====
        logger.info("📊 Step 6: Syncing Oracle Database systems...")
        
        oci_databases = {}
        for comp in oci_compartments:
            try:
                db_systems = database_client.list_db_systems(comp['id'])
                for db in db_systems:
                    oci_databases[db['id']] = {
                        'id': db['id'],
                        'compartment_id': comp['id'],
                        'display_name': db['display_name'],
                        'shape': db.get('shape'),
                        'database_edition': db.get('database_edition'),
                        'lifecycle_state': db.get('lifecycle_state'),
                        'availability_domain': db.get('availability_domain'),
                        'cpu_core_count': db.get('cpu_core_count'),
                        'data_storage_size_in_gbs': db.get('data_storage_size_in_gbs'),
                        'region': region,
                        'time_created': db.get('time_created')
                    }
                if db_systems:
                    logger.debug(f"  ✅ Found {len(db_systems)} databases in {comp['name']}")
            except Exception as e:
                logger.debug(f"  ⚠️ Error fetching databases from {comp['name']}: {str(e)}")
        
        # Get existing databases from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_database WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_db_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert databases
        for ocid, db_data in oci_databases.items():
            upsert_database(user_id, db_data)
            if ocid in db_db_ocids:
                stats['databases']['updated'] += 1
            else:
                stats['databases']['new'] += 1
        
        # Mark deleted databases
        deleted_db_ocids = db_db_ocids - set(oci_databases.keys())
        for ocid in deleted_db_ocids:
            mark_database_deleted(ocid)
            stats['databases']['deleted'] += 1
        
        logger.info(f"✅ Databases: {stats['databases']}")
        
        # ===== STEP 7: SYNC POSTGRESQL SYSTEMS =====
        logger.info("🐘 Step 7: Syncing PostgreSQL systems...")
        
        oci_postgresql = {}
        for comp in oci_compartments:
            try:
                psql_systems = postgresql_client.list_db_systems(comp['id'])
                for psql in psql_systems:
                    oci_postgresql[psql['id']] = {
                        'id': psql['id'],
                        'compartment_id': comp['id'],
                        'display_name': psql['display_name'],
                        'shape': psql.get('shape'),
                        'instance_count': psql.get('instance_count'),
                        'storage_details_iops': psql.get('storage_details_iops'),
                        'storage_details_size_in_gbs': psql.get('storage_details_size_in_gbs'),
                        'lifecycle_state': psql.get('lifecycle_state'),
                        'region': region,
                        'time_created': psql.get('time_created')
                    }
                if psql_systems:
                    logger.debug(f"  ✅ Found {len(psql_systems)} PostgreSQL systems in {comp['name']}")
            except Exception as e:
                logger.debug(f"  ⚠️ Error fetching PostgreSQL systems from {comp['name']}: {str(e)}")
        
        # Get existing PostgreSQL systems from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_database_psql WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_psql_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert PostgreSQL systems
        for ocid, psql_data in oci_postgresql.items():
            upsert_postgresql(user_id, psql_data)
            if ocid in db_psql_ocids:
                stats['postgresql_systems']['updated'] += 1
            else:
                stats['postgresql_systems']['new'] += 1
        
        # Mark deleted PostgreSQL systems
        deleted_psql_ocids = db_psql_ocids - set(oci_postgresql.keys())
        for ocid in deleted_psql_ocids:
            mark_postgresql_deleted(ocid)
            stats['postgresql_systems']['deleted'] += 1
        
        logger.info(f"✅ PostgreSQL Systems: {stats['postgresql_systems']}")
        
        # ===== STEP 8: SYNC LOAD BALANCERS =====
        logger.info("⚖️  Step 8: Syncing load balancers...")
        
        oci_load_balancers = {}
        for comp in oci_compartments:
            try:
                lbs = load_balancer_client.list_load_balancers(comp['id'])
                for lb in lbs:
                    oci_load_balancers[lb['id']] = {
                        'id': lb['id'],
                        'compartment_id': comp['id'],
                        'display_name': lb['display_name'],
                        'shape_name': lb.get('shape_name'),
                        'is_private': lb.get('is_private'),
                        'ip_addresses': lb.get('ip_addresses', []),
                        'min_bandwidth_mbps': lb.get('min_bandwidth_mbps'),
                        'max_bandwidth_mbps': lb.get('max_bandwidth_mbps'),
                        'lifecycle_state': lb.get('lifecycle_state'),
                        'region': region,
                        'time_created': lb.get('time_created')
                    }
                if lbs:
                    logger.debug(f"  ✅ Found {len(lbs)} load balancers in {comp['name']}")
            except Exception as e:
                logger.debug(f"  ⚠️ Error fetching load balancers from {comp['name']}: {str(e)}")
        
        # Get existing load balancers from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ocid FROM oci_load_balancer WHERE user_id = %s AND is_deleted = FALSE", (user_id,))
        db_lb_ocids = set(row['ocid'] for row in cursor.fetchall())
        conn.close()
        
        # Upsert load balancers
        for ocid, lb_data in oci_load_balancers.items():
            upsert_load_balancer(user_id, lb_data)
            if ocid in db_lb_ocids:
                stats['load_balancers']['updated'] += 1
            else:
                stats['load_balancers']['new'] += 1
        
        # Mark deleted load balancers
        deleted_lb_ocids = db_lb_ocids - set(oci_load_balancers.keys())
        for ocid in deleted_lb_ocids:
            mark_load_balancer_deleted(ocid)
            stats['load_balancers']['deleted'] += 1
        
        logger.info(f"✅ Load Balancers: {stats['load_balancers']}")
        
        # Calculate totals
        duration = (datetime.now() - start_time).total_seconds()
        total_stats = {
            'compartments': stats['compartments'],
            'instances': stats['instances'],
            'volumes': stats['volumes'],
            'buckets': stats['buckets'],
            'file_systems': stats['file_systems'],
            'databases': stats['databases'],
            'postgresql_systems': stats['postgresql_systems'],
            'load_balancers': stats['load_balancers'],
            'total_new': sum(s['new'] for s in stats.values()),
            'total_updated': sum(s['updated'] for s in stats.values()),
            'total_deleted': sum(s['deleted'] for s in stats.values()),
            'duration_seconds': round(duration, 2)
        }
        
        logger.info(f"✅ Sync complete for user {user_id}: {total_stats}")
        return total_stats
    
    except Exception as e:
        logger.error(f"❌ Error syncing resources for user {user_id}: {str(e)}", exc_info=True)
        raise


async def sync_all_users() -> Dict[int, Dict[str, Any]]:
    """Sync resources for all users."""
    from app.db.database import get_db_connection
    
    logger.info("🔄 Starting sync for all users")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT DISTINCT user_id FROM oci_configs")
        user_ids = [row['user_id'] for row in cursor.fetchall()]
        
        logger.info(f"📊 Found {len(user_ids)} users with OCI configs")
        
        results = {}
        for user_id in user_ids:
            try:
                stats = await sync_user_resources(user_id)
                results[user_id] = stats
            except Exception as e:
                logger.error(f"❌ Error syncing user {user_id}: {str(e)}")
                results[user_id] = {'error': str(e)}
        
        logger.info(f"✅ Completed sync for {len(results)} users")
        return results
    
    finally:
        conn.close()
