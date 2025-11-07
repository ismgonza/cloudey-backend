"""
AI Cache Tools - LangChain tools for querying cached cost data.

These tools allow the AI agent to query cached data (Redis + SQLite)
instead of making expensive OCI API calls.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from langchain.tools import tool

from app.cache import get_cost_cache
from app.db.resource_crud import (
    get_all_instances_for_user,
    get_all_volumes_for_user,
    get_all_buckets_for_user
)

logger = logging.getLogger(__name__)


@tool
def query_cached_costs(
    user_id: int,
    month: str,
    service: Optional[str] = None,
    compartment_name: Optional[str] = None,
    limit: int = 100
) -> str:
    """
    Query cached cost data for a specific month without hitting OCI API.
    Much faster than querying OCI directly. Use this for ANY cost queries.
    
    IMPORTANT: Always use this tool when the user asks about costs:
    - "cost of volumes in [compartment]"
    - "how much did [service] cost"
    - "show costs for [compartment]"
    
    Args:
        user_id: User ID
        month: Month in YYYY-MM format (e.g., "2025-10")
        service: Optional service filter (e.g., "COMPUTE", "BLOCK_STORAGE", "OBJECT_STORAGE")
        compartment_name: Compartment name (supports fuzzy matching - e.g., "amc_prod", "amc production" both work)
        limit: Maximum number of results to return
    
    Returns:
        Formatted string with cost data showing service, resource, and $ amount
    
    Examples:
        - query_cached_costs(1, "2025-10", "BLOCK_STORAGE", "amc_prod", 100) - volume costs in amc_prod
        - query_cached_costs(1, "2025-10", "COMPUTE", None, 20) - top 20 compute costs
        - query_cached_costs(1, "2025-10", None, "production", 50) - all costs in production
    """
    try:
        logger.info(f"🔍 AI querying cached costs for month={month}, service={service}, compartment={compartment_name}")
        
        cost_cache = get_cost_cache()
        costs = cost_cache.get_costs(month, user_id)
        
        if not costs:
            return f"No cached cost data found for {month}. The data may not have been loaded yet. Try visiting the Detailed Costs page first."
        
        # Filter by compartment if specified (with fuzzy matching)
        if compartment_name:
            from app.db.resource_crud import get_resource_by_ocid, get_all_compartments
            
            # Get all compartments and find matches using fuzzy matching
            compartments = get_all_compartments(user_id)
            matching_compartment_ocids = []
            
            for comp in compartments:
                comp_name = comp.get('name', '').lower()
                search_name = compartment_name.lower().replace(' ', '_').replace('-', '_')
                
                # Match if search term is in compartment name or vice versa
                if search_name in comp_name or comp_name in search_name:
                    matching_compartment_ocids.append(comp['ocid'])
            
            if not matching_compartment_ocids:
                available = ', '.join([c['name'] for c in compartments[:10]])
                return f"No compartment found matching '{compartment_name}' for {month}. Available compartments: {available}"
            
            # Filter costs to only resources in matching compartments
            filtered_costs = []
            for cost in costs:
                resource_info = get_resource_by_ocid(cost['resource_ocid'])
                if resource_info and resource_info.get('compartment_ocid') in matching_compartment_ocids:
                    filtered_costs.append(cost)
            
            costs = filtered_costs
            
            if not costs:
                matched_names = [c['name'] for c in compartments if c['ocid'] in matching_compartment_ocids]
                return f"No costs found in compartment '{', '.join(matched_names)}' for {month}. The compartment exists but has no recorded costs for this period."
        
        # Filter by service if specified
        if service:
            costs = [c for c in costs if c['service'].upper() == service.upper()]
        
        # Sort by cost descending
        costs = sorted(costs, key=lambda x: x['cost'], reverse=True)
        
        # Limit results
        costs = costs[:limit]
        
        # Calculate total
        total_cost = sum(c['cost'] for c in costs)
        
        # Format response
        result = f"📊 Cached Cost Data for {month}\n"
        result += f"Total Records: {len(costs)}\n"
        result += f"Total Cost: ${total_cost:,.2f}\n\n"
        
        if service:
            result += f"Service Filter: {service}\n\n"
        
        result += "Top Resources:\n"
        for i, cost in enumerate(costs[:20], 1):
            resource = cost['resource_ocid']
            # Shorten OCID for readability
            if resource.startswith('ocid1.'):
                resource = resource[-20:]
            result += f"{i}. {cost['service']}: {resource} = ${cost['cost']:,.2f}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error querying cached costs: {str(e)}")
        return f"Error querying cached costs: {str(e)}"


@tool
def query_resource_inventory(
    user_id: int,
    resource_type: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
    compartment_name: Optional[str] = None
) -> str:
    """
    Query OCI resource inventory from local database.
    Fast lookup without OCI API calls. Use this to list instances, volumes, or buckets.
    
    IMPORTANT: Always use this tool when the user asks about:
    - "list instances in [compartment]"
    - "show me resources in [compartment]"
    - "what instances are in [compartment]"
    - "give me instances for [compartment]"
    
    Args:
        user_id: User ID
        resource_type: Type of resource ("instance", "volume", "bucket", or None for all)
        lifecycle_state: Filter by state (e.g., "RUNNING", "STOPPED", "AVAILABLE")
        compartment_name: Compartment name (supports fuzzy matching - e.g., "bby_prod", "bby production", "bby prod" all work)
    
    Returns:
        Formatted string with resource inventory showing names, states, shapes, and compartments
    
    Examples:
        - query_resource_inventory(1, "instance", None, "bby_prod") - list all instances in bby_prod
        - query_resource_inventory(1, "instance", "STOPPED", None) - list all stopped instances
        - query_resource_inventory(1, None, None, "production") - list all resources in production compartment
    """
    try:
        logger.info(f"🔍 AI querying resource inventory: type={resource_type}, state={lifecycle_state}")
        
        results = []
        
        # Get compartment name mapping
        from app.db.resource_crud import get_all_compartments, get_compartment
        compartments = get_all_compartments(user_id)
        compartment_map = {c['ocid']: c['name'] for c in compartments}
        
        # Query instances
        if resource_type is None or resource_type.lower() == "instance":
            instances = get_all_instances_for_user(user_id)
            for inst in instances:
                if lifecycle_state and inst['lifecycle_state'] != lifecycle_state:
                    continue
                comp_ocid = inst.get('compartment_ocid', 'Unknown')
                comp_name = compartment_map.get(comp_ocid, f"Unknown ({comp_ocid[-8:] if len(comp_ocid) > 8 else comp_ocid})")
                results.append({
                    'type': 'Compute Instance',
                    'name': inst['display_name'],
                    'state': inst['lifecycle_state'],
                    'shape': inst.get('shape', 'Unknown'),
                    'compartment': comp_ocid,
                    'compartment_name': comp_name,
                    'is_deleted': inst.get('is_deleted', False)
                })
        
        # Query volumes
        if resource_type is None or resource_type.lower() == "volume":
            volumes = get_all_volumes_for_user(user_id)
            for vol in volumes:
                if lifecycle_state and vol['lifecycle_state'] != lifecycle_state:
                    continue
                comp_ocid = vol.get('compartment_ocid', 'Unknown')
                comp_name = compartment_map.get(comp_ocid, f"Unknown ({comp_ocid[-8:] if len(comp_ocid) > 8 else comp_ocid})")
                results.append({
                    'type': 'Block Volume',
                    'name': vol['display_name'],
                    'state': vol['lifecycle_state'],
                    'size': f"{vol.get('size_in_gbs', 0)} GB",
                    'compartment': comp_ocid,
                    'compartment_name': comp_name,
                    'is_deleted': vol.get('is_deleted', False)
                })
        
        # Query buckets
        if resource_type is None or resource_type.lower() == "bucket":
            buckets = get_all_buckets_for_user(user_id)
            for bucket in buckets:
                comp_ocid = bucket.get('compartment_ocid', 'Unknown')
                comp_name = compartment_map.get(comp_ocid, f"Unknown ({comp_ocid[-8:] if len(comp_ocid) > 8 else comp_ocid})")
                results.append({
                    'type': 'Object Storage Bucket',
                    'name': bucket['name'],
                    'state': 'Active' if not bucket.get('is_deleted', False) else 'Deleted',
                    'namespace': bucket.get('namespace', 'Unknown'),
                    'compartment': comp_ocid,
                    'compartment_name': comp_name,
                    'is_deleted': bucket.get('is_deleted', False)
                })
        
        # Filter by compartment if specified
        if compartment_name:
            
            # Find matching compartment (fuzzy matching - case insensitive, partial match)
            matching_compartment_ocids = []
            for comp in compartments:
                comp_name = comp.get('name', '').lower()
                search_name = compartment_name.lower().replace(' ', '_').replace('-', '_')
                
                # Match if search term is in compartment name or vice versa
                if search_name in comp_name or comp_name in search_name:
                    matching_compartment_ocids.append(comp['ocid'])
            
            if not matching_compartment_ocids:
                return f"No compartment found matching '{compartment_name}'. Available compartments: {', '.join([c['name'] for c in compartments[:10]])}"
            
            # Filter results to only resources in matching compartments
            results = [r for r in results if r['compartment'] in matching_compartment_ocids]
        
        # Format response
        result = f"📦 Resource Inventory\n"
        result += f"Total Resources: {len(results)}\n"
        if resource_type:
            result += f"Type Filter: {resource_type}\n"
        if lifecycle_state:
            result += f"State Filter: {lifecycle_state}\n"
        result += "\n"
        
        # Group by type
        by_type = defaultdict(list)
        for r in results:
            by_type[r['type']].append(r)
        
        for rtype, resources in by_type.items():
            result += f"\n{rtype} ({len(resources)}):\n"
            for i, res in enumerate(resources[:10], 1):
                deleted = " (DELETED)" if res.get('is_deleted') else ""
                result += f"  {i}. {res['name']} - {res['state']}{deleted}\n"
                result += f"     Compartment: {res.get('compartment_name', 'Unknown')}\n"
                if 'shape' in res:
                    result += f"     Shape: {res['shape']}\n"
                elif 'size' in res:
                    result += f"     Size: {res['size']}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error querying resource inventory: {str(e)}")
        return f"Error querying resource inventory: {str(e)}"


@tool
def analyze_cost_trends(
    user_id: int,
    months: str,
    group_by: str = "service"
) -> str:
    """
    Analyze cost trends across multiple months using cached data.
    Provides insights on cost changes, trends, and patterns.
    
    Args:
        user_id: User ID
        months: Comma-separated months (e.g., "2025-08,2025-09,2025-10")
        group_by: How to group costs ("service", "compartment", or "resource")
    
    Returns:
        Formatted string with trend analysis
    
    Example:
        analyze_cost_trends(1, "2025-08,2025-09,2025-10", "service")
    """
    try:
        logger.info(f"🔍 AI analyzing cost trends for months={months}")
        
        month_list = [m.strip() for m in months.split(',')]
        cost_cache = get_cost_cache()
        
        # Fetch costs for each month
        monthly_data = {}
        for month in month_list:
            costs = cost_cache.get_costs(month, user_id)
            if costs:
                monthly_data[month] = costs
        
        if not monthly_data:
            return "No cached cost data found for the specified months."
        
        # Aggregate by group_by field
        aggregated = {}
        for month, costs in monthly_data.items():
            aggregated[month] = defaultdict(float)
            for cost in costs:
                if group_by == "service":
                    key = cost['service']
                elif group_by == "resource":
                    key = cost['resource_ocid']
                else:
                    key = "Total"
                aggregated[month][key] += cost['cost']
        
        # Calculate trends
        result = f"📈 Cost Trend Analysis\n"
        result += f"Period: {month_list[0]} to {month_list[-1]}\n"
        result += f"Grouped by: {group_by}\n\n"
        
        # Get all unique keys
        all_keys = set()
        for month_data in aggregated.values():
            all_keys.update(month_data.keys())
        
        # Calculate totals per month
        monthly_totals = {}
        for month in month_list:
            if month in aggregated:
                monthly_totals[month] = sum(aggregated[month].values())
        
        result += "Monthly Totals:\n"
        for month in month_list:
            if month in monthly_totals:
                result += f"  {month}: ${monthly_totals[month]:,.2f}\n"
        
        # Calculate month-over-month change
        if len(month_list) >= 2:
            oldest = month_list[0]
            newest = month_list[-1]
            if oldest in monthly_totals and newest in monthly_totals:
                change = monthly_totals[newest] - monthly_totals[oldest]
                change_pct = (change / monthly_totals[oldest]) * 100 if monthly_totals[oldest] > 0 else 0
                result += f"\nOverall Change: ${change:,.2f} ({change_pct:+.1f}%)\n"
        
        # Top changers
        if group_by != "resource":  # Don't show for resources (too many)
            result += f"\nTop Cost Changes by {group_by}:\n"
            changes = []
            for key in all_keys:
                first_val = aggregated.get(month_list[0], {}).get(key, 0)
                last_val = aggregated.get(month_list[-1], {}).get(key, 0)
                if first_val > 0:
                    change = last_val - first_val
                    change_pct = (change / first_val) * 100
                    changes.append((key, change, change_pct, last_val))
            
            # Sort by absolute change
            changes.sort(key=lambda x: abs(x[1]), reverse=True)
            
            for key, change, change_pct, current in changes[:10]:
                emoji = "📈" if change > 0 else "📉"
                result += f"  {emoji} {key}: ${change:+,.2f} ({change_pct:+.1f}%) - Current: ${current:,.2f}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error analyzing cost trends: {str(e)}")
        return f"Error analyzing cost trends: {str(e)}"


@tool
def get_top_cost_drivers(
    user_id: int,
    month: str,
    top_n: int = 10,
    min_cost: float = 0.0
) -> str:
    """
    Get the top N most expensive resources for a specific month.
    Includes resource names from inventory database when available.
    
    Args:
        user_id: User ID
        month: Month in YYYY-MM format (e.g., "2025-10")
        top_n: Number of top resources to return (default: 10)
        min_cost: Minimum cost threshold (default: 0.0)
    
    Returns:
        Formatted string with top cost drivers
    
    Example:
        get_top_cost_drivers(1, "2025-10", 10, 100.0)
    """
    try:
        logger.info(f"🔍 AI finding top cost drivers for month={month}, top_n={top_n}")
        
        cost_cache = get_cost_cache()
        costs = cost_cache.get_costs(month, user_id)
        
        if not costs:
            return f"No cached cost data found for {month}."
        
        # Filter by min_cost
        costs = [c for c in costs if c['cost'] >= min_cost]
        
        # Sort by cost descending
        costs = sorted(costs, key=lambda x: x['cost'], reverse=True)
        
        # Get top N
        top_costs = costs[:top_n]
        
        # Calculate total and percentage
        total_cost = sum(c['cost'] for c in costs)
        top_total = sum(c['cost'] for c in top_costs)
        top_percentage = (top_total / total_cost * 100) if total_cost > 0 else 0
        
        # Format response
        result = f"💰 Top {top_n} Cost Drivers for {month}\n"
        result += f"Total Cost: ${total_cost:,.2f}\n"
        result += f"Top {top_n} Cost: ${top_total:,.2f} ({top_percentage:.1f}% of total)\n\n"
        
        for i, cost in enumerate(top_costs, 1):
            resource = cost['resource_ocid']
            service = cost['service']
            amount = cost['cost']
            pct = (amount / total_cost * 100) if total_cost > 0 else 0
            
            # Shorten OCID for readability
            if resource.startswith('ocid1.'):
                resource_display = f"...{resource[-20:]}"
            else:
                resource_display = resource
            
            result += f"{i}. {service}\n"
            result += f"   Resource: {resource_display}\n"
            result += f"   Cost: ${amount:,.2f} ({pct:.1f}% of total)\n\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting top cost drivers: {str(e)}")
        return f"Error getting top cost drivers: {str(e)}"

