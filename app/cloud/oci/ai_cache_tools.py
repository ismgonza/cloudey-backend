"""
AI Cache Tools - LangChain tools for querying cached cost data.

These tools allow the AI agent to query cached data (Redis + SQLite)
instead of making expensive OCI API calls.
"""

import logging
import os
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

# Check if demo mode is active
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# Import demo mode functions if active
if DEMO_MODE:
    from app.demo_middleware import anonymize_compartment, anonymize_resource_name, obfuscate_cost


def anonymize_for_demo(data):
    """Apply demo mode anonymization to tool outputs"""
    if not DEMO_MODE:
        return data
    
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Anonymize compartment names
            if 'compartment' in key.lower():
                result[key] = anonymize_compartment(value, ocid=data.get('compartment_ocid'))
            # Anonymize resource names
            elif any(keyword in key.lower() for keyword in ['name', 'resource_name', 'display_name']) and 'service' not in key.lower():
                result[key] = anonymize_resource_name(value, ocid=data.get('resource_ocid') or data.get('ocid'))
            # Obfuscate costs
            elif 'cost' in key.lower() or 'amount' in key.lower() or 'total' in key.lower():
                result[key] = obfuscate_cost(value) if isinstance(value, (int, float)) else value
            else:
                result[key] = anonymize_for_demo(value)
        return result
    elif isinstance(data, list):
        return [anonymize_for_demo(item) for item in data]
    else:
        return data


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
        
        # Filter by service if specified (handle both "Block Storage" and "BLOCK_STORAGE" formats)
        if service:
            # Normalize service name for comparison (remove spaces, underscores, make uppercase)
            service_normalized = service.upper().replace(' ', '').replace('_', '')
            costs = [c for c in costs if c['service'].upper().replace(' ', '').replace('_', '') == service_normalized]
        
        # Sort by cost descending
        costs = sorted(costs, key=lambda x: x['cost'], reverse=True)
        
        # Limit results
        costs = costs[:limit]
        
        # Enrich with resource names from inventory
        from app.db.resource_crud import get_resource_by_ocid
        for cost in costs:
            resource_info = get_resource_by_ocid(cost['resource_ocid'])
            if resource_info:
                cost['resource_name'] = resource_info.get('resource_name', 'Unknown')
                cost['compartment_name'] = compartment_map.get(resource_info.get('compartment_ocid', ''), 'Unknown')
            else:
                # Use shortened OCID if not in inventory
                ocid = cost['resource_ocid']
                cost['resource_name'] = ocid[-20:] if ocid.startswith('ocid1.') else ocid
                cost['compartment_name'] = 'Unknown'
        
        # Apply demo mode anonymization to costs data
        costs = anonymize_for_demo(costs)
        
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
            name = cost.get('resource_name', 'Unknown')
            comp = cost.get('compartment_name', 'Unknown')
            result += f"{i}. {cost['service']}: {name} ({comp}) = ${cost['cost']:,.2f}\n"
        
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
        compartment_name: Compartment name (supports fuzzy matching - e.g., "production", "prod staging", "staging" all work)
    
    Returns:
        Formatted string with resource inventory showing names, states, shapes, and compartments
    
    Examples:
        - query_resource_inventory(1, "instance", None, "production") - list all instances in production
        - query_resource_inventory(1, "instance", "STOPPED", None) - list all stopped instances
        - query_resource_inventory(1, None, None, "staging") - list all resources in staging compartment
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
        
        # Apply demo mode anonymization to results
        results = anonymize_for_demo(results)
        
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
def get_resources_with_costs(
    user_id: int,
    resource_type: str,
    compartment_name: Optional[str] = None,
    months: str = None,
    limit: int = 100
) -> str:
    """
    Get resources of a specific type with their costs across multiple months.
    Perfect for queries like "instances in compartment X with their costs".
    
    Args:
        user_id: User ID
        resource_type: Type of resource ("instance", "volume", "bucket")
        compartment_name: Optional compartment name (supports fuzzy matching)
        months: Comma-separated months (e.g., "2025-09,2025-10") - defaults to last 2 months
        limit: Maximum number of resources to return (default: 100)
    
    Returns:
        Formatted string with resources and their costs per month
    
    Examples:
        - get_resources_with_costs(1, "instance", "production", "2025-09,2025-10", 50)
        - get_resources_with_costs(1, "volume", "staging", "2025-10", 20)
    """
    try:
        logger.info(f"🔍 AI getting resources with costs: type={resource_type}, compartment={compartment_name}")
        
        # Get compartment mapping
        from app.db.resource_crud import get_all_compartments
        compartments = get_all_compartments(user_id)
        compartment_map = {c['ocid']: c['name'] for c in compartments}
        
        # Find matching compartments if specified
        matching_compartment_ocids = []
        if compartment_name:
            for comp in compartments:
                comp_name = comp.get('name', '').lower()
                search_name = compartment_name.lower().replace(' ', '_').replace('-', '_')
                if search_name in comp_name or comp_name in search_name:
                    matching_compartment_ocids.append(comp['ocid'])
            
            if not matching_compartment_ocids:
                return f"No compartment found matching '{compartment_name}'"
        
        # Get resources using inventory tool
        resources = []
        if resource_type.lower() == "instance":
            from app.db.resource_crud import get_all_instances_for_user
            instances = get_all_instances_for_user(user_id)
            for inst in instances:
                comp_ocid = inst.get('compartment_ocid', '')
                if not matching_compartment_ocids or comp_ocid in matching_compartment_ocids:
                    resources.append({
                        'ocid': inst['ocid'],
                        'name': inst['display_name'],
                        'type': 'Compute',
                        'compartment_ocid': comp_ocid,
                        'compartment_name': compartment_map.get(comp_ocid, 'Unknown'),
                        'state': inst.get('lifecycle_state', 'Unknown'),
                        'shape': inst.get('shape', 'Unknown')
                    })
        elif resource_type.lower() == "volume":
            from app.db.resource_crud import get_all_volumes_for_user
            volumes = get_all_volumes_for_user(user_id)
            for vol in volumes:
                comp_ocid = vol.get('compartment_ocid', '')
                if not matching_compartment_ocids or comp_ocid in matching_compartment_ocids:
                    resources.append({
                        'ocid': vol['ocid'],
                        'name': vol['display_name'],
                        'type': 'Block Storage',
                        'compartment_ocid': comp_ocid,
                        'compartment_name': compartment_map.get(comp_ocid, 'Unknown'),
                        'state': vol.get('lifecycle_state', 'Unknown'),
                        'size': f"{vol.get('size_in_gbs', 0)} GB"
                    })
        elif resource_type.lower() == "bucket":
            from app.db.resource_crud import get_all_buckets_for_user
            buckets = get_all_buckets_for_user(user_id)
            for bucket in buckets:
                comp_ocid = bucket.get('compartment_ocid', '')
                if not matching_compartment_ocids or comp_ocid in matching_compartment_ocids:
                    resources.append({
                        'ocid': bucket['ocid'],
                        'name': bucket['name'],
                        'type': 'Object Storage',
                        'compartment_ocid': comp_ocid,
                        'compartment_name': compartment_map.get(comp_ocid, 'Unknown'),
                        'namespace': bucket.get('namespace', 'Unknown')
                    })
        
        if not resources:
            return f"No {resource_type}s found" + (f" in compartment '{compartment_name}'" if compartment_name else "")
        
        # Limit resources
        resources = resources[:limit]
        
        # Parse months (default to last 2 months if not specified)
        if not months:
            from datetime import datetime, timedelta
            today = datetime.now()
            month1 = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            month2 = today.strftime("%Y-%m")
            month_list = [month1, month2]
        else:
            month_list = [m.strip() for m in months.split(',')]
        
        # Get costs for these resources
        cost_cache = get_cost_cache()
        resource_costs = {r['ocid']: {m: 0.0 for m in month_list} for r in resources}
        
        for month in month_list:
            costs = cost_cache.get_costs(month, user_id)
            if costs:
                for cost in costs:
                    ocid = cost['resource_ocid']
                    if ocid in resource_costs:
                        resource_costs[ocid][month] = cost['cost']
        
        # Apply demo mode anonymization to resources
        resources = anonymize_for_demo(resources)
        # Anonymize costs in resource_costs dict
        if DEMO_MODE:
            resource_costs = {k: {m: obfuscate_cost(v) for m, v in months.items()} for k, months in resource_costs.items()}
        
        # Format response
        result = f"📦 {len(resources)} {resource_type.title()}(s)"
        if compartment_name:
            result += f" in {compartment_name}"
        result += f"\nCosts for: {', '.join(month_list)}\n\n"
        
        for i, resource in enumerate(resources, 1):
            ocid = resource['ocid']
            costs = resource_costs[ocid]
            total_cost = sum(costs.values())
            
            result += f"{i}. {resource['name']}\n"
            result += f"   Compartment: {resource['compartment_name']}\n"
            
            if 'state' in resource:
                result += f"   State: {resource['state']}\n"
            if 'shape' in resource:
                result += f"   Shape: {resource['shape']}\n"
            if 'size' in resource:
                result += f"   Size: {resource['size']}\n"
            
            result += f"   Costs: "
            month_costs_str = ", ".join([f"{m}: ${costs[m]:,.2f}" for m in month_list])
            result += month_costs_str
            result += f" (Total: ${total_cost:,.2f})\n\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting resources with costs: {str(e)}")
        return f"Error getting resources with costs: {str(e)}"


@tool
def get_volumes_with_details(
    user_id: int,
    month: str,
    top_n: int = 10,
    compartment_name: Optional[str] = None
) -> str:
    """
    Get block volumes with their costs, size, state, and attachment status.
    Perfect for queries about expensive volumes or volume utilization.
    
    Args:
        user_id: User ID
        month: Month in YYYY-MM format (e.g., "2025-10")
        top_n: Number of volumes to return (default: 10)
        compartment_name: Optional compartment filter
    
    Returns:
        Formatted table with volume details
    
    Example:
        get_volumes_with_details(1, "2025-10", 10, "production")
    """
    try:
        logger.info(f"🔍 AI getting volume details for month={month}, top_n={top_n}")
        
        # Get costs for block storage
        cost_cache = get_cost_cache()
        costs = cost_cache.get_costs(month, user_id)
        
        if not costs:
            return f"No cost data found for {month}"
        
        # Filter to Block Storage only and normalize service name
        costs = [c for c in costs if 'block' in c['service'].lower() or 'storage' in c['service'].lower()]
        
        # Get compartments for filtering
        from app.db.resource_crud import get_all_compartments, get_all_volumes_for_user
        compartments = get_all_compartments(user_id)
        compartment_map = {c['ocid']: c['name'] for c in compartments}
        
        # Get all volumes
        volumes = get_all_volumes_for_user(user_id)
        volume_map = {v['ocid']: v for v in volumes}
        
        # Filter by compartment if specified
        if compartment_name:
            matching_compartment_ocids = []
            for comp in compartments:
                comp_name = comp.get('name', '').lower()
                search_name = compartment_name.lower().replace(' ', '_').replace('-', '_')
                if search_name in comp_name or comp_name in search_name:
                    matching_compartment_ocids.append(comp['ocid'])
            
            if not matching_compartment_ocids:
                return f"No compartment found matching '{compartment_name}'"
            
            # Filter volumes to matching compartments
            volumes = [v for v in volumes if v.get('compartment_ocid') in matching_compartment_ocids]
            volume_map = {v['ocid']: v for v in volumes}
        
        # Match costs with volumes
        volume_costs = []
        for cost in costs:
            ocid = cost['resource_ocid']
            if ocid in volume_map:
                vol = volume_map[ocid]
                volume_costs.append({
                    'name': vol.get('display_name', 'Unknown'),
                    'cost': cost['cost'],
                    'size_gb': vol.get('size_in_gbs', 0),
                    'state': vol.get('lifecycle_state', 'Unknown'),
                    'compartment': compartment_map.get(vol.get('compartment_ocid'), 'Unknown'),
                    'ocid': ocid
                })
        
        if not volume_costs:
            return f"No block volumes found with costs for {month}"
        
        # Sort by cost and get top N
        volume_costs.sort(key=lambda x: x['cost'], reverse=True)
        volume_costs = volume_costs[:top_n]
        
        # Apply demo mode anonymization to volume data
        volume_costs = anonymize_for_demo(volume_costs)
        
        # Calculate total
        total_cost = sum(v['cost'] for v in volume_costs)
        
        # Format as table
        result = f"📊 Top {len(volume_costs)} Block Volumes by Cost ({month})\n\n"
        result += f"Total Cost: ${total_cost:,.2f}\n\n"
        result += "```\n"
        result += f"{'#':<4} {'Volume Name':<40} {'Compartment':<20} {'Size':<10} {'State':<12} {'Cost/Month':<12}\n"
        result += "=" * 100 + "\n"
        
        for i, vol in enumerate(volume_costs, 1):
            name = vol['name'][:38] if len(vol['name']) > 38 else vol['name']
            comp = vol['compartment'][:18] if len(vol['compartment']) > 18 else vol['compartment']
            size = f"{vol['size_gb']} GB"
            state = vol['state']
            cost = f"${vol['cost']:,.2f}"
            
            result += f"{i:<4} {name:<40} {comp:<20} {size:<10} {state:<12} {cost:<12}\n"
        
        result += "```\n\n"
        result += "**Note**: Costs shown are for the specified month only.\n"
        result += "**Attachment Status**: Check the 'State' column - 'AVAILABLE' means not attached, others may be attached.\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting volume details: {str(e)}")
        return f"Error getting volume details: {str(e)}"


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
        
        # Enrich with resource names from inventory
        from app.db.resource_crud import get_resource_by_ocid, get_all_compartments
        compartments = get_all_compartments(user_id)
        compartment_map = {c['ocid']: c['name'] for c in compartments}
        
        for cost in top_costs:
            resource_info = get_resource_by_ocid(cost['resource_ocid'])
            if resource_info:
                cost['resource_name'] = resource_info.get('resource_name', 'Unknown')
                cost['compartment_name'] = compartment_map.get(resource_info.get('compartment_ocid', ''), 'Unknown')
            else:
                # Use shortened OCID if not in inventory
                ocid = cost['resource_ocid']
                cost['resource_name'] = ocid[-20:] if ocid.startswith('ocid1.') else ocid
                cost['compartment_name'] = 'Unknown'
        
        # Apply demo mode anonymization to top costs data
        top_costs = anonymize_for_demo(top_costs)
        
        # Calculate total and percentage
        total_cost = sum(c['cost'] for c in costs)
        top_total = sum(c['cost'] for c in top_costs)
        top_percentage = (top_total / total_cost * 100) if total_cost > 0 else 0
        
        # Format response
        result = f"💰 Top {top_n} Cost Drivers for {month}\n"
        result += f"Total Cost: ${total_cost:,.2f}\n"
        result += f"Top {top_n} Cost: ${top_total:,.2f} ({top_percentage:.1f}% of total)\n\n"
        
        for i, cost in enumerate(top_costs, 1):
            name = cost.get('resource_name', 'Unknown')
            service = cost['service']
            comp = cost.get('compartment_name', 'Unknown')
            amount = cost['cost']
            pct = (amount / total_cost * 100) if total_cost > 0 else 0
            
            result += f"{i}. {service}: {name}\n"
            result += f"   Compartment: {comp}\n"
            result += f"   Cost: ${amount:,.2f} ({pct:.1f}% of total)\n\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting top cost drivers: {str(e)}")
        return f"Error getting top cost drivers: {str(e)}"

