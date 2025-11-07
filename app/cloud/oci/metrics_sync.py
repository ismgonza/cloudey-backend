"""
OCI Metrics Sync Module

Fetches utilization metrics from OCI Monitoring service and caches them in PostgreSQL.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

from app.cloud.oci.monitoring import MonitoringClient
from app.db.resource_crud import (
    get_all_instances_for_user,
    get_all_compartments_for_user
)
from app.db.metrics_crud import (
    save_resource_metrics,
    get_metrics_stats,
    delete_old_metrics
)

logger = logging.getLogger(__name__)


# Metrics to fetch for each resource type (ONLY configurable metrics!)
COMPUTE_METRICS = ['CpuUtilization', 'MemoryUtilization']
LOAD_BALANCER_METRICS = ['PeakBandwidth']  # In Mbps - the only configurable LB metric


async def sync_compute_metrics(user_id: int, days: int = 7) -> Dict[str, any]:
    """
    Fetch and cache compute instance metrics.
    
    Args:
        user_id: User ID
        days: Number of days to look back for metrics
    
    Returns:
        Dictionary with sync statistics
    """
    logger.info(f"📊 Starting compute metrics sync for user {user_id}")
    
    try:
        # Get all running instances
        instances = get_all_instances_for_user(user_id, include_deleted=False)
        running_instances = [
            inst for inst in instances 
            if inst['lifecycle_state'] == 'RUNNING'
        ]
        
        if not running_instances:
            logger.info("No running instances found")
            return {
                'instances_checked': 0,
                'metrics_saved': 0,
                'errors': 0
            }
        
        logger.info(f"Found {len(running_instances)} running instances")
        
        # Initialize monitoring client
        monitoring_client = MonitoringClient(user_id)
        
        # Get compartments for mapping
        compartments = get_all_compartments_for_user(user_id)
        compartment_map = {comp['ocid']: comp for comp in compartments}
        
        stats = {
            'instances_checked': 0,
            'metrics_saved': 0,
            'errors': 0,
            'instances_processed': []
        }
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Process instances in batches by compartment for efficiency
        instances_by_compartment = {}
        for instance in running_instances:
            comp_id = instance['compartment_ocid']
            if comp_id not in instances_by_compartment:
                instances_by_compartment[comp_id] = []
            instances_by_compartment[comp_id].append(instance)
        
        # Fetch metrics for each compartment
        for compartment_id, comp_instances in instances_by_compartment.items():
            compartment_name = compartment_map.get(compartment_id, {}).get('name', 'Unknown')
            logger.info(f"Processing {len(comp_instances)} instances in compartment: {compartment_name}")
            
            for instance in comp_instances:
                try:
                    instance_ocid = instance['ocid']
                    instance_name = instance['display_name']
                    
                    logger.debug(f"Fetching metrics for instance: {instance_name}")
                    
                    # Fetch metrics from OCI
                    metrics = monitoring_client.get_instance_metrics(
                        compartment_id=compartment_id,
                        instance_ocid=instance_ocid,
                        metric_names=COMPUTE_METRICS,
                        days=days
                    )
                    
                    if metrics:
                        # Save to database
                        saved_count = save_resource_metrics(
                            user_id=user_id,
                            resource_ocid=instance_ocid,
                            resource_type='compute',
                            metrics=metrics,
                            period_start=period_start,
                            period_end=period_end
                        )
                        
                        stats['metrics_saved'] += saved_count
                        stats['instances_processed'].append({
                            'name': instance_name,
                            'ocid': instance_ocid,
                            'metrics': metrics
                        })
                        
                        logger.debug(
                            f"✅ {instance_name}: "
                            f"CPU={metrics.get('CpuUtilization', 0):.1f}% "
                            f"Mem={metrics.get('MemoryUtilization', 0):.1f}%"
                        )
                    
                    stats['instances_checked'] += 1
                    
                except Exception as e:
                    logger.error(f"Error fetching metrics for instance {instance.get('display_name')}: {str(e)}")
                    stats['errors'] += 1
        
        logger.info(
            f"✅ Compute metrics sync complete: "
            f"{stats['instances_checked']} instances checked, "
            f"{stats['metrics_saved']} metrics saved, "
            f"{stats['errors']} errors"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Error syncing compute metrics: {str(e)}", exc_info=True)
        raise


async def sync_load_balancer_metrics(user_id: int, days: int = 7) -> Dict[str, any]:
    """
    Fetch and cache load balancer metrics.
    
    Args:
        user_id: User ID
        days: Number of days to look back for metrics
    
    Returns:
        Dictionary with sync statistics
    """
    logger.info(f"⚖️ Starting load balancer metrics sync for user {user_id}")
    
    try:
        # Import here to avoid circular dependency
        from app.db.resource_crud import get_all_load_balancers_for_user
        
        # Get all load balancers
        load_balancers = get_all_load_balancers_for_user(user_id, include_deleted=False)
        active_lbs = [
            lb for lb in load_balancers 
            if lb['lifecycle_state'] == 'ACTIVE'
        ]
        
        if not active_lbs:
            logger.info("No active load balancers found")
            return {
                'load_balancers_checked': 0,
                'metrics_saved': 0,
                'errors': 0
            }
        
        logger.info(f"Found {len(active_lbs)} active load balancers")
        
        # Initialize monitoring client
        monitoring_client = MonitoringClient(user_id)
        
        # Get compartments for mapping
        compartments = get_all_compartments_for_user(user_id)
        compartment_map = {comp['ocid']: comp for comp in compartments}
        
        stats = {
            'load_balancers_checked': 0,
            'metrics_saved': 0,
            'errors': 0,
            'load_balancers_processed': []
        }
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Process load balancers by compartment
        lbs_by_compartment = {}
        for lb in active_lbs:
            comp_id = lb['compartment_ocid']
            if comp_id not in lbs_by_compartment:
                lbs_by_compartment[comp_id] = []
            lbs_by_compartment[comp_id].append(lb)
        
        # Fetch metrics for each compartment
        for compartment_id, comp_lbs in lbs_by_compartment.items():
            compartment_name = compartment_map.get(compartment_id, {}).get('name', 'Unknown')
            logger.info(f"Processing {len(comp_lbs)} load balancers in compartment: {compartment_name}")
            
            for lb in comp_lbs:
                try:
                    lb_ocid = lb['ocid']
                    lb_name = lb['display_name']
                    
                    logger.debug(f"Fetching metrics for load balancer: {lb_name}")
                    
                    # Fetch metrics from OCI
                    metrics = monitoring_client.get_load_balancer_metrics(
                        compartment_id=compartment_id,
                        lb_ocid=lb_ocid,
                        metric_names=LOAD_BALANCER_METRICS,
                        days=days
                    )
                    
                    if metrics:
                        # Save to database
                        saved_count = save_resource_metrics(
                            user_id=user_id,
                            resource_ocid=lb_ocid,
                            resource_type='load_balancer',
                            metrics=metrics,
                            period_start=period_start,
                            period_end=period_end
                        )
                        
                        stats['metrics_saved'] += saved_count
                        stats['load_balancers_processed'].append({
                            'name': lb_name,
                            'ocid': lb_ocid,
                            'metrics': metrics
                        })
                        
                        logger.debug(
                            f"✅ {lb_name}: "
                            f"Bandwidth={metrics.get('PeakBandwidth', 0):.1f} Mbps"
                        )
                    
                    stats['load_balancers_checked'] += 1
                    
                except Exception as e:
                    logger.error(f"Error fetching metrics for load balancer {lb.get('display_name')}: {str(e)}")
                    stats['errors'] += 1
        
        logger.info(
            f"✅ Load balancer metrics sync complete: "
            f"{stats['load_balancers_checked']} load balancers checked, "
            f"{stats['metrics_saved']} metrics saved, "
            f"{stats['errors']} errors"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Error syncing load balancer metrics: {str(e)}", exc_info=True)
        raise


async def sync_all_metrics(user_id: int, days: int = 7) -> Dict[str, any]:
    """
    Sync all metrics (compute + load balancers).
    
    Args:
        user_id: User ID
        days: Number of days to look back for metrics
    
    Returns:
        Combined statistics
    """
    logger.info(f"🚀 Starting full metrics sync for user {user_id}")
    
    start_time = datetime.now()
    
    try:
        # Clean up old metrics (>30 days)
        delete_old_metrics(days_to_keep=30)
        
        # Sync compute metrics
        compute_stats = await sync_compute_metrics(user_id, days)
        
        # Sync load balancer metrics
        lb_stats = await sync_load_balancer_metrics(user_id, days)
        
        # Get final stats
        final_stats = get_metrics_stats(user_id)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        result = {
            'success': True,
            'duration_seconds': duration,
            'compute': compute_stats,
            'load_balancers': lb_stats,
            'total_metrics_saved': compute_stats['metrics_saved'] + lb_stats['metrics_saved'],
            'total_errors': compute_stats['errors'] + lb_stats['errors'],
            'cache_stats': final_stats
        }
        
        logger.info(
            f"🎉 Full metrics sync complete in {duration:.1f}s: "
            f"{result['total_metrics_saved']} metrics saved, "
            f"{result['total_errors']} errors"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in full metrics sync: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'duration_seconds': (datetime.now() - start_time).total_seconds()
        }

