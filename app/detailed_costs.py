"""
Detailed costs analysis and aggregation module.
Provides comprehensive cost breakdowns by compartment, service, and resource.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

import oci.usage_api as usage_api
from oci import retry

from app.cloud.oci.usage_api_client import UsageApiClient
from app.cloud.oci.compartment import CompartmentClient
from app.db.resource_crud import get_resource_by_ocid
from app.cache import cached, CacheKeyPrefixes, get_cost_cache
from app.sysconfig import CacheConfig

logger = logging.getLogger(__name__)


def get_resource_type_from_ocid(ocid: str) -> Optional[str]:
    """
    Determine resource type from OCID.
    
    OCI OCIDs follow pattern: ocid1.<resource_type>.<realm>.<region>.<unique_id>
    """
    if not ocid or not ocid.startswith('ocid1.'):
        return None
    
    parts = ocid.split('.')
    if len(parts) < 2:
        return None
    
    return parts[1]  # e.g., 'instance', 'volume', 'bucket', etc.


def get_resource_name(resource_id: str, compartment_id: str, user_id: int) -> str:
    """
    Get resource display name from normalized DB tables.
    
    Strategy:
    1. Query normalized tables by OCID (primary key lookup - instant!)
    2. If not found, return shortened OCID
    3. Resource sync populates tables via "Sync Resources" button
    
    Args:
        resource_id: Resource OCID
        compartment_id: Not used (kept for backwards compatibility)
        user_id: Not used (OCID is globally unique)
    
    Returns:
        Resource display name or shortened OCID
    """
    try:
        # Query normalized tables by OCID (super fast PK lookup!)
        db_resource = get_resource_by_ocid(resource_id)
        
        if db_resource:
            # Check if resource is deleted
            if db_resource.get('is_deleted'):
                name = db_resource.get('resource_name', 'Unknown')
                return f"{name} (Deleted)"
            
            # Return active resource name
            if db_resource.get('resource_name'):
                return db_resource['resource_name']
        
        # Not in DB yet - return shortened OCID
        # User needs to click "Sync Resources" to populate
        logger.debug(f"Resource {resource_id} not in DB, using shortened OCID")
        return resource_id.split('.')[-1] if '.' in resource_id else resource_id
    
    except Exception as e:
        logger.debug(f"Error getting resource name from DB for {resource_id}: {str(e)}")
        # Fallback to shortened OCID
        return resource_id.split('.')[-1] if '.' in resource_id else resource_id


def get_previous_months(num_months: int = 3) -> List[tuple]:
    """Get date ranges for the last N complete months.
    
    Args:
        num_months: Number of complete months to retrieve
    
    Returns:
        List of tuples: [(start_date, end_date, month_name), ...]
        Ordered from oldest to newest
    """
    current_date = datetime.now()
    months = []
    
    for i in range(1, num_months + 1):
        # Calculate year and month
        month = current_date.month - i
        year = current_date.year
        
        while month <= 0:
            month += 12
            year -= 1
        
        # Get first day of month
        first_day = datetime(year, month, 1)
        
        # Get last day of month
        if month == 12:
            last_day = datetime(year, 12, 31)
        else:
            next_month_first = datetime(year, month + 1, 1)
            last_day = next_month_first - timedelta(days=1)
        
        month_name = first_day.strftime("%B %Y")
        months.append((first_day, last_day, month_name))
    
    return list(reversed(months))  # Return oldest to newest


def calculate_trend(values: List[float]) -> Dict[str, Any]:
    """Calculate trend from a list of values.
    
    Args:
        values: List of numeric values (oldest to newest)
    
    Returns:
        Dict with change_pct, direction, color
    """
    if len(values) < 2 or values[-2] == 0:
        return {"change_pct": 0.0, "direction": "stable", "color": "gray"}
    
    latest = values[-1]
    previous = values[-2]
    change_pct = ((latest - previous) / previous) * 100
    
    # Determine direction and color
    if change_pct < -5:
        direction = "down"
        color = "green"
    elif change_pct > 5:
        direction = "up"
        color = "red"
    else:
        direction = "stable"
        color = "gray"
    
    return {
        "change_pct": round(change_pct, 1),
        "direction": direction,
        "color": color
    }


@cached(prefix=CacheKeyPrefixes.PREFIX_DASHBOARD, ttl=CacheConfig.DASHBOARD_TTL)
async def get_detailed_costs(user_id: int, force_refresh: bool = False) -> Dict[str, Any]:
    """Get detailed cost breakdown by compartment, service, and resource.
    
    Args:
        user_id: User ID
        force_refresh: If True, bypass cache and fetch fresh data
    
    Returns:
        Dict containing:
        - compartments: List of compartments with 3-month costs and trends
        - services_summary: List of services aggregated across all compartments
        - top_cost_drivers: Top 10 most expensive resources
        - metadata: Additional info (date range, totals, etc.)
    """
    logger.info(f"Fetching detailed costs for user_id={user_id}, force_refresh={force_refresh}")
    
    # Initialize clients (they fetch OCI config internally)
    usage_client = UsageApiClient(user_id)
    compartment_client = CompartmentClient(user_id)
    
    # Get all compartments and tenancy ID
    tenancy_id = compartment_client.config["tenancy"]
    compartments = compartment_client.list_compartments(include_root=True)
    compartment_map = {comp['id']: comp['name'] for comp in compartments}
    
    # Get last 3 months date ranges
    months = get_previous_months(3)
    logger.info(f"Fetching costs for months: {[m[2] for m in months]}")
    
    # Data structures to aggregate costs
    compartment_costs = defaultdict(lambda: {"name": "", "months": [0.0] * 3, "services": defaultdict(lambda: [0.0] * 3)})
    service_totals = defaultdict(lambda: [0.0] * 3)
    resource_costs = []  # For top cost drivers (only latest month)
    
    # Track resources by service (for expandable services table)
    # Structure: {service_name: {resource_id: {"compartment": ..., "months": [0,0,0]}}}
    service_resources = defaultdict(lambda: defaultdict(lambda: {"compartment_id": "", "compartment_name": "", "months": [0.0] * 3}))
    
    # Fetch costs for each month
    for month_idx, (start_date, end_date, month_name) in enumerate(months):
        logger.info(f"Fetching costs for {month_name} ({start_date.date()} to {end_date.date()})")
        
        try:
            # Determine cache key (YYYY-MM format)
            month_key = start_date.strftime("%Y-%m")
            
            # Check hybrid cache (Redis for current month, SQLite for historical)
            cost_cache = get_cost_cache()
            cached_costs = cost_cache.get_costs(month_key, user_id)
            
            items = []
            use_cache = False
            
            if cached_costs:
                logger.info(f"✅ Using cached costs for {month_name}")
                
                # Convert cached data to OCI item-like structure for aggregation
                class CachedItem:
                    def __init__(self, service, resource_id, cost):
                        self.compartment_id = None  # Will be fetched from resource tables
                        self.service = service
                        self.resource_id = resource_id
                        self.computed_amount = cost
                
                items = [
                    CachedItem(
                        record['service'],
                        record['resource_ocid'],
                        record['cost']
                    )
                    for record in cached_costs
                ]
                use_cache = True
                logger.debug(f"Loaded {len(items)} cost items from hybrid cache for {month_name}")
            
            # If not cached or current month, fetch from OCI
            if not use_cache:
                logger.info(f"🌐 Fetching costs from OCI for {month_name}")
                
                # Use OCI SDK directly to get compartment + service + resource breakdown
                # OCI API's time_usage_ended is EXCLUSIVE, so add +1 day to include the last day
                # e.g., to get costs for Aug 1-31, we set end to Sep 1 00:00:00
                start_datetime = datetime.combine(start_date.date(), datetime.min.time())
                end_datetime = datetime.combine(end_date.date(), datetime.min.time()) + timedelta(days=1)
                
                # Build request for OCI Usage API
                request_details = {
                    "tenant_id": tenancy_id,
                    "time_usage_started": start_datetime,
                    "time_usage_ended": end_datetime,
                    "granularity": "DAILY",
                    "query_type": "COST",
                    "group_by": ["service", "compartmentId", "resourceId"],
                    "compartment_depth": 7
                }
                
                request = usage_api.models.RequestSummarizedUsagesDetails(**request_details)
                
                # Call OCI API
                response = usage_client.usage_client.request_summarized_usages(
                    request,
                    retry_strategy=retry.DEFAULT_RETRY_STRATEGY
                )
                
                items = response.data.items if response.data else []
                logger.debug(f"Received {len(items)} cost items from OCI for {month_name}")
                
                # Aggregate DAILY costs into MONTHLY totals before caching
                # OCI API returns DAILY granularity, but we want monthly totals
                cost_aggregates = defaultdict(lambda: {'service': '', 'cost': 0.0})
                
                for item in items:
                    service_name = getattr(item, 'service', 'Unknown')
                    resource_id = getattr(item, 'resource_id', None)
                    computed_amount = getattr(item, 'computed_amount', None)
                    cost = float(computed_amount) if computed_amount is not None else 0.0
                    
                    if resource_id:  # Only aggregate resource-level costs
                        cost_aggregates[resource_id]['service'] = service_name
                        cost_aggregates[resource_id]['cost'] += cost  # SUM daily costs
                
                # Convert aggregates to cache records
                cache_records = [
                    {
                            'resource_ocid': resource_id,
                        'service': data['service'],
                        'cost': data['cost']
                    }
                    for resource_id, data in cost_aggregates.items()
                ]
                
                # Save aggregated monthly totals to hybrid cache
                if cache_records:
                    cost_cache.save_costs(month_key, user_id, cache_records)
                    logger.info(f"💾 Saved {len(cache_records)} aggregated cost records to hybrid cache for {month_name} (from {len(items)} daily records)")
            
            # Process items for aggregation
            logger.debug(f"Processing {len(items)} cost items for aggregation")
            
            # Aggregate costs
            for item in items:
                service_name = getattr(item, 'service', 'Unknown')
                resource_id = getattr(item, 'resource_id', None)
                
                # Get compartment_id (from OCI API or lookup from resource tables)
                compartment_id = getattr(item, 'compartment_id', None)
                
                if compartment_id is None and resource_id:
                    # Cached data - lookup compartment from resource tables
                    resource_info = get_resource_by_ocid(resource_id)
                    if resource_info:
                        compartment_id = resource_info.get('compartment_ocid', 'Unknown')
                    else:
                        compartment_id = 'Unknown'
                elif compartment_id is None:
                    compartment_id = 'Unknown'
                
                # Handle None computed_amount
                computed_amount = getattr(item, 'computed_amount', None)
                cost = float(computed_amount) if computed_amount is not None else 0.0
                
                # Compartment-level aggregation
                if compartment_id not in compartment_costs:
                    # Determine display name
                    if compartment_id in compartment_map:
                        # Compartment exists - use its name
                        display_name = compartment_map[compartment_id]
                        is_deleted = False
                    else:
                        # Compartment not found (deleted) - use shortened OCID
                        short_id = compartment_id[-8:] if len(compartment_id) > 8 else compartment_id
                        display_name = f"{short_id} (Deleted)"
                        is_deleted = True
                    
                    compartment_costs[compartment_id]['name'] = display_name
                    compartment_costs[compartment_id]['is_deleted'] = is_deleted
                
                compartment_costs[compartment_id]['months'][month_idx] += cost
                compartment_costs[compartment_id]['services'][service_name][month_idx] += cost
                
                # Service-level aggregation (across all compartments)
                service_totals[service_name][month_idx] += cost
                
                # Resource-level tracking by service (all months)
                if resource_id:
                    service_resources[service_name][resource_id]['compartment_id'] = compartment_id
                    service_resources[service_name][resource_id]['compartment_name'] = compartment_map.get(compartment_id, compartment_id)
                    service_resources[service_name][resource_id]['months'][month_idx] += cost
                
                # Resource-level tracking (only for latest month - for top cost drivers)
                if month_idx == len(months) - 1 and resource_id:
                    resource_costs.append({
                        'resource_id': resource_id,
                        'service': service_name,
                        'compartment_id': compartment_id,
                        'compartment_name': compartment_map.get(compartment_id, compartment_id),
                        'cost': cost
                    })
        
        except Exception as e:
            logger.error(f"Error fetching costs for {month_name}: {str(e)}", exc_info=True)
            # Continue with other months
    
    # Format compartments data with trends
    compartments_data = []
    for comp_id, comp_data in compartment_costs.items():
        months_costs = comp_data['months']
        trend = calculate_trend(months_costs)
        
        # Format services for this compartment
        services_list = []
        for service_name, service_months in comp_data['services'].items():
            service_trend = calculate_trend(service_months)
            total_cost = service_months[-1]  # Latest month
            pct_of_compartment = (total_cost / months_costs[-1] * 100) if months_costs[-1] > 0 else 0
            
            services_list.append({
                'service': service_name,
                'months': [round(m, 2) for m in service_months],
                'change_pct': service_trend['change_pct'],
                'direction': service_trend['direction'],
                'color': service_trend['color'],
                'pct_of_compartment': round(pct_of_compartment, 1)
            })
        
        # Sort services by latest month cost (descending)
        services_list.sort(key=lambda x: x['months'][-1], reverse=True)
        
        compartments_data.append({
            'compartment_id': comp_id,
            'compartment_name': comp_data['name'],
            'is_deleted': comp_data.get('is_deleted', False),
            'months': [round(m, 2) for m in months_costs],
            'change_pct': trend['change_pct'],
            'direction': trend['direction'],
            'color': trend['color'],
            'services': services_list
        })
    
    # Sort compartments by latest month cost (descending)
    compartments_data.sort(key=lambda x: x['months'][-1], reverse=True)
    
    # Calculate totals row
    total_months = [sum(comp['months'][i] for comp in compartments_data) for i in range(3)]
    total_trend = calculate_trend(total_months)
    
    # Format services summary (across all compartments)
    services_summary = []
    
    for service_name, service_months in service_totals.items():
        trend = calculate_trend(service_months)
        pct_of_total = (service_months[-1] / total_months[-1] * 100) if total_months[-1] > 0 else 0
        
        # Get top 10 resources for this service
        top_resources = []
        if service_name in service_resources:
            resources_list = []
            for res_id, res_data in service_resources[service_name].items():
                total_cost = sum(res_data['months'])
                resources_list.append({
                    'resource_id': res_id,
                    'compartment_id': res_data['compartment_id'],
                    'compartment_name': res_data['compartment_name'],
                    'months': [round(m, 2) for m in res_data['months']],
                    'total_cost': round(total_cost, 2)
                })
            # Sort by total cost and take top 10
            resources_list.sort(key=lambda x: x['total_cost'], reverse=True)
            top_10 = resources_list[:10]
            
            # Fetch resource names from DB (fast, no API calls)
            FETCH_RESOURCE_NAMES = True  # DB-first strategy enabled
            
            if FETCH_RESOURCE_NAMES:
                # Fetch resource names only for top 10 (to minimize API calls)
                # Wrap in try/except to ensure cost data still works even if name fetching fails
                logger.info(f"Fetching names for top 10 resources in {service_name}")
                for resource in top_10:
                    try:
                        resource['resource_name'] = get_resource_name(
                            resource['resource_id'],
                            resource['compartment_id'],
                            user_id
                        )
                    except Exception as e:
                        logger.warning(f"Failed to fetch name for {resource['resource_id']}: {str(e)}")
                        # Fallback to shortened OCID
                        res_id = resource['resource_id']
                        resource['resource_name'] = res_id.split('.')[-1] if '.' in res_id else res_id
            else:
                # Use shortened OCID without API calls
                logger.info(f"Using shortened OCIDs for {service_name} (name fetching disabled)")
                for resource in top_10:
                    res_id = resource['resource_id']
                    resource['resource_name'] = res_id.split('.')[-1] if '.' in res_id else res_id
            
            top_resources = top_10
        
        services_summary.append({
            'service': service_name,
            'months': [round(m, 2) for m in service_months],
            'change_pct': trend['change_pct'],
            'direction': trend['direction'],
            'color': trend['color'],
            'pct_of_total': round(pct_of_total, 1),
            'top_resources': top_resources
        })
    
    # Sort services by latest month cost (descending)
    services_summary.sort(key=lambda x: x['months'][-1], reverse=True)
    
    # Top 10 cost drivers (resources)
    # Aggregate by resource_id (in case of duplicates)
    resource_aggregated = defaultdict(lambda: {'service': '', 'compartment_name': '', 'cost': 0.0})
    for item in resource_costs:
        res_id = item['resource_id']
        resource_aggregated[res_id]['service'] = item['service']
        resource_aggregated[res_id]['compartment_name'] = item['compartment_name']
        resource_aggregated[res_id]['cost'] += item['cost']
    
    top_cost_drivers = [
        {
            'resource_id': res_id,
            'resource_name': res_id.split('.')[-1] if '.' in res_id else res_id,  # Extract short name
            'service': data['service'],
            'compartment_name': data['compartment_name'],
            'cost': round(data['cost'], 2)
        }
        for res_id, data in resource_aggregated.items()
    ]
    
    # Sort by cost and take top 10
    top_cost_drivers.sort(key=lambda x: x['cost'], reverse=True)
    top_cost_drivers = top_cost_drivers[:10]
    
    # Prepare metadata
    month_names = [m[2] for m in months]
    
    result = {
        'compartments': compartments_data,
        'totals': {
            'months': [round(m, 2) for m in total_months],
            'change_pct': total_trend['change_pct'],
            'direction': total_trend['direction'],
            'color': total_trend['color']
        },
        'services_summary': services_summary,
        'top_cost_drivers': top_cost_drivers,
        'metadata': {
            'month_names': month_names,
            'generated_at': datetime.now().isoformat(),
            'num_compartments': len(compartments_data),
            'num_services': len(services_summary),
            'latest_month_total': round(total_months[-1], 2)
        }
    }
    
    logger.info(f"Detailed costs data generated: {len(compartments_data)} compartments, "
                f"{len(services_summary)} services, {len(top_cost_drivers)} top resources")
    
    return result

