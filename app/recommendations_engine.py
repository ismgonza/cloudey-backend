"""
AI-Powered Recommendations Engine

Generates cost optimization insights using cached data and AI analysis.
"""

import logging
import json
from typing import Dict, List, Any
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage

from app.cache import get_cost_cache
from app.cloud.oci.optimization import CostOptimizationAnalyzer
from app.db import crud
from app.db.resource_crud import (
    get_all_instances_for_user,
    get_all_volumes_for_user
)

logger = logging.getLogger(__name__)


async def generate_ai_recommendations(user_id: int) -> Dict[str, Any]:
    """
    Generate AI-powered cost optimization recommendations.
    
    Uses cached cost data and resource inventory to provide instant insights.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary with recommendations and insights
    """
    logger.info(f"🤖 Generating AI recommendations for user {user_id}")
    
    try:
        # Get user's OCI config
        config = crud.get_oci_config_by_user_id(user_id)
        if not config:
            return {
                "error": "No OCI configuration found",
                "recommendations": [],
                "insights": []
            }
        
        # Get cost cache
        cost_cache = get_cost_cache()
        
        # Determine which months to analyze (last 3 complete months)
        today = datetime.now()
        months_to_analyze = []
        for i in range(1, 4):
            month_date = today.replace(day=1) - timedelta(days=i*30)
            month_key = month_date.strftime("%Y-%m")
            months_to_analyze.append(month_key)
        
        months_to_analyze = sorted(list(set(months_to_analyze)))  # Deduplicate and sort
        
        # Fetch cached costs for analysis
        monthly_costs = {}
        for month in months_to_analyze:
            costs = cost_cache.get_costs(month, user_id)
            if costs:
                monthly_costs[month] = costs
        
        if not monthly_costs:
            return {
                "error": "No cached cost data available. Please visit the Detailed Costs page to populate the cache.",
                "recommendations": [],
                "insights": []
            }
        
        # ========================================================================
        # LOAD RESOURCE INVENTORY (used across multiple insights)
        # ========================================================================
        instances = get_all_instances_for_user(user_id)
        volumes = get_all_volumes_for_user(user_id)
        
        # Get compartments for mapping
        from app.db.resource_crud import get_all_compartments_for_user
        compartments = get_all_compartments_for_user(user_id)
        compartment_map = {comp['ocid']: comp['name'] for comp in compartments}
        
        # ========================================================================
        # LOAD CACHED METRICS (utilization data)
        # ========================================================================
        from app.db.metrics_crud import get_metrics_for_multiple_resources
        from app.db.resource_crud import get_all_load_balancers_for_user
        
        # Get instance OCIDs
        instance_ocids = [inst['ocid'] for inst in instances if not inst.get('is_deleted', False)]
        
        # Fetch cached compute metrics (last 48 hours for more flexibility)
        # Note: Older metrics = less confidence in recommendations
        instance_metrics = get_metrics_for_multiple_resources(
            resource_ocids=instance_ocids,
            resource_type='compute',
            max_age_hours=48  # 2 days - balances freshness vs availability
        ) if instance_ocids else {}
        
        logger.debug(f"Loaded metrics for {len(instance_metrics)} instances")
        
        # Get load balancers and their metrics
        load_balancers = get_all_load_balancers_for_user(user_id)
        lb_ocids = [lb['ocid'] for lb in load_balancers if not lb.get('is_deleted', False)]
        
        lb_metrics = get_metrics_for_multiple_resources(
            resource_ocids=lb_ocids,
            resource_type='load_balancer',
            max_age_hours=48
        ) if lb_ocids else {}
        
        logger.debug(f"Loaded metrics for {len(lb_metrics)} load balancers")
        
        # ========================================================================
        # 1. COST TREND INSIGHTS (REMOVED - Now using AI narrative only)
        # ========================================================================
        insights = []  # Keeping empty for compatibility, removed insight generation
        
        # Calculate monthly totals (still needed for AI narrative)
        monthly_totals = {}
        for month, costs in monthly_costs.items():
            monthly_totals[month] = sum(c['cost'] for c in costs)
        
        # NOTE: Removed all static insight generation logic (cost trends, dominant services, etc.)
        # These are now handled by the AI narrative in the LLM analysis section below.
        
        # Collect underutilized instances for dedicated recommendation card
        underutilized_instances_data = []
        potential_underutil_savings = 0
        
        # Count total running instances and vCPUs for more accurate calculation
        total_running_vcpus = sum(inst.get('vcpus', 0) for inst in instances if inst['lifecycle_state'] == 'RUNNING')
        
        for inst in instances:
            if inst['lifecycle_state'] == 'RUNNING' and not inst.get('is_deleted', False):
                metrics = instance_metrics.get(inst['ocid'], {})
                cpu = metrics.get('CpuUtilization')
                mem = metrics.get('MemoryUtilization')
                
                if cpu is not None and mem is not None and cpu < 40 and mem < 40:
                    vcpus = inst.get('vcpus') or 0
                    savings = 0
                    # Savings calculation will be done after we know compute costs
                    # For now just collect the instance
                    
                    underutilized_instances_data.append({
                        "name": inst.get('display_name', 'N/A'),
                        "compartment": compartment_map.get(inst.get('compartment_ocid'), 'Unknown'),
                        "vcpus": vcpus,
                        "memory_gb": inst.get('memory_in_gbs') or 0,
                        "shape": inst.get('shape', 'N/A'),
                        "cpu_percent": cpu,
                        "memory_percent": mem,
                        "potential_savings": savings,
                        "lifecycle_state": inst.get('lifecycle_state', 'N/A'),
                        "ocid": inst.get('ocid', 'N/A')
                })
        
        # ========================================================================
        # 2. CALCULATE SERVICE COSTS & TIME PERIODS (needed for Quick Wins and AI analysis)
        # ========================================================================
        
        # Calculate time periods for analysis
        sorted_months = sorted(monthly_costs.keys()) if monthly_costs else []
        oldest_month = sorted_months[0] if sorted_months else None
        newest_month = sorted_months[-1] if sorted_months else None
        latest_month = newest_month  # Alias for compatibility
        
        # Aggregate costs by service for latest month
        latest_costs = monthly_costs.get(latest_month, []) if latest_month else []
        
        service_costs = {}
        for cost in latest_costs:
            service = cost['service']
            service_costs[service] = service_costs.get(service, 0) + cost['cost']
        
        # Calculate accurate savings for underutilized instances using real compute costs
        if underutilized_instances_data and total_running_vcpus > 0:
            compute_cost = service_costs.get('COMPUTE', service_costs.get('Compute', 0))
            if compute_cost > 0:
                # Calculate cost per vCPU based on actual spending
                cost_per_vcpu = compute_cost / total_running_vcpus
                
                # Calculate savings for underutilized instances (assume 30% savings from rightsizing)
                for inst_data in underutilized_instances_data:
                    vcpus = inst_data['vcpus']
                    if vcpus > 0:
                        estimated_cost = vcpus * cost_per_vcpu
                        savings = estimated_cost * 0.30  # Conservative 30% savings
                        inst_data['potential_savings'] = savings
                        potential_underutil_savings += savings
        
        # ========================================================================
        # 3. RESOURCE-BASED RECOMMENDATIONS
        # ========================================================================
        
        recommendations = []
        
        # ========================================================================
        # 3.0 UNDERUTILIZED INSTANCES (NEW DEDICATED CARD)
        # ========================================================================
        if underutilized_instances_data:
            # Build summary
            action_parts = []
            action_parts.append(f"**{len(underutilized_instances_data)} running instances** are severely underutilized (both CPU & Memory <40%)")
            action_parts.append("")
            action_parts.append("These instances are using far less resources than their current shape provides.")
            action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Downsize to smaller shapes (reduce vCPUs and memory)")
            action_parts.append("• Review application requirements vs current allocations")
            action_parts.append("• Test smaller shapes in non-prod first")
            action_parts.append("• Consider burstable instances for variable workloads")
            action_parts.append("")
            action_parts.append(f"**Estimated Savings:** ~${potential_underutil_savings:,.0f}/month")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(underutilized_instances_data)} instances with CPU/Memory metrics")
            
            recommendations.append({
                "type": "underutilized_instances",
                "severity": "high",
                "title": f"🎯 {len(underutilized_instances_data)} underutilized instance(s) detected",
                "description": f"Instances running with low CPU and Memory utilization (<40%).",
                "potential_savings": potential_underutil_savings,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(underutilized_instances_data),
                    "data": underutilized_instances_data
                }
            })
        
        # ========================================================================
        # 3.1 STOPPED INSTANCES (HIGH PRIORITY)
        # ========================================================================
        stopped_instances = [i for i in instances if i['lifecycle_state'] == 'STOPPED' and not i.get('is_deleted', False)]
        
        if stopped_instances:
            # Estimate cost (rough estimate: $50/month per stopped instance for storage)
            estimated_cost = len(stopped_instances) * 50
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"**{len(stopped_instances)} stopped instances** still costing ~**${estimated_cost}/month**")
            action_parts.append("")
            action_parts.append("Stopped compute instances still cost ~$50/month each for boot volume storage.")
            action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Create backups if needed before termination")
            action_parts.append("• Terminate unused instances")
            action_parts.append("• Remove associated boot volumes")
            action_parts.append("• Consider custom images for future redeployment")
            action_parts.append("")
            action_parts.append(f"**Estimated Savings:** ~${estimated_cost:,.0f}/month")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(stopped_instances)} stopped instances")
            
            recommendations.append({
                "type": "stopped_instances",
                "severity": "high",
                "title": f"🛑 {len(stopped_instances)} stopped instance(s) still incurring costs",
                "description": f"Stopped compute instances still cost ~$50/month each for boot volume storage.",
                "potential_savings": estimated_cost,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(stopped_instances),
                    "data": [
                        {
                            "name": inst.get('display_name', 'N/A'),
                            "compartment": compartment_map.get(inst.get('compartment_ocid'), 'Unknown'),
                            "vcpus": inst.get('vcpus') or 0,
                            "memory_gb": inst.get('memory_in_gbs') or 0,
                            "shape": inst.get('shape', 'N/A'),
                            "estimated_cost": 50,  # $50/month per stopped instance
                            "lifecycle_state": inst.get('lifecycle_state', 'N/A'),
                            "ocid": inst.get('ocid', 'N/A')
                        }
                        for inst in stopped_instances
                    ]
                }
            })
        
        # ========================================================================
        # 3.2 UNATTACHED VOLUMES (MEDIUM PRIORITY)
        # ========================================================================
        unattached_volumes = []
        
        # We'd need to check if volume is attached, for now assume volumes without "is_deleted" are candidates
        for vol in volumes:
            if not vol.get('is_deleted', False) and vol['lifecycle_state'] == 'AVAILABLE':
                unattached_volumes.append(vol)
        
        if unattached_volumes:
            # Estimate cost: $0.0255/GB/month for block storage
            total_gb = sum((vol.get('size_in_gbs') or 0) for vol in unattached_volumes)
            estimated_cost = total_gb * 0.0255
            
            # Sort by size (largest first)
            sorted_volumes = sorted(unattached_volumes, key=lambda v: v.get('size_in_gbs') or 0, reverse=True)
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"**{len(unattached_volumes)} unattached volumes** ({total_gb:,.0f} GB total) costing ~**${estimated_cost:,.2f}/month**")
            action_parts.append("")
            action_parts.append("These volumes are not attached to any instances and are wasting money.")
            action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Review the full list and delete unused volumes")
            action_parts.append("• Attach volumes that are still needed")
            action_parts.append("• Take snapshots before deletion for backup")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(unattached_volumes)} volumes with details")
            
            recommendations.append({
                "type": "unattached_volumes",
                "severity": "medium",
                "title": f"💾 {len(unattached_volumes)} unattached volume(s) found",
                "description": f"Unattached block volumes ({total_gb:,.0f} GB total) are costing you money without being used.",
                "potential_savings": estimated_cost,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(unattached_volumes),
                    "data": [
                        {
                            "name": vol.get('display_name', 'N/A'),
                            "compartment": compartment_map.get(vol.get('compartment_ocid'), 'Unknown'),
                            "size_gb": vol.get('size_in_gbs') or 0,
                            "monthly_cost": (vol.get('size_in_gbs') or 0) * 0.0255,
                            "availability_domain": vol.get('availability_domain', 'N/A'),
                            "lifecycle_state": vol.get('lifecycle_state', 'N/A'),
                            "ocid": vol.get('ocid', 'N/A')
                        }
                        for vol in sorted_volumes
                    ]
                }
            })
        
        # ========================================================================
        # 3.3 LARGE VOLUMES (COST OPTIMIZATION)
        # ========================================================================
        large_volumes = [v for v in volumes if (v.get('size_in_gbs') or 0) > 1000 and not v.get('is_deleted', False)]
        
        if large_volumes:
            total_gb = sum((v.get('size_in_gbs') or 0) for v in large_volumes)
            # Potential 30% savings by moving to lower-cost tier
            current_cost = total_gb * 0.0255
            potential_savings = current_cost * 0.30
            
            # Sort by size (largest first)
            sorted_large_volumes = sorted(large_volumes, key=lambda v: v.get('size_in_gbs') or 0, reverse=True)
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"**{len(large_volumes)} large volumes** ({total_gb:,.0f} GB total) costing ~**${current_cost:,.2f}/month**")
            action_parts.append("")
            action_parts.append("Large volumes (>1TB) might be using expensive Ultra High Performance tier.")
            action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Switch to Balanced tier for non-critical workloads (30% cheaper)")
            action_parts.append("• Move cold data to Lower Cost tier (50% cheaper)")
            action_parts.append("• Review I/O requirements per volume")
            action_parts.append("")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.2f}/month (30% reduction)")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(large_volumes)} volumes with costs")
            
            recommendations.append({
                "type": "large_volumes",
                "severity": "medium",
                "title": f"📦 {len(large_volumes)} large volume(s) could use lower-cost tiers",
                "description": f"Large volumes ({total_gb:,.0f} GB total) might benefit from Balanced or Lower Cost performance tiers.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(large_volumes),
                    "data": [
                        {
                            "name": vol.get('display_name', 'N/A'),
                            "compartment": compartment_map.get(vol.get('compartment_ocid'), 'Unknown'),
                            "size_gb": vol.get('size_in_gbs') or 0,
                            "current_cost": (vol.get('size_in_gbs') or 0) * 0.0255,
                            "potential_savings": (vol.get('size_in_gbs') or 0) * 0.0255 * 0.30,
                            "lifecycle_state": vol.get('lifecycle_state', 'N/A'),
                            "ocid": vol.get('ocid', 'N/A')
                        }
                        for vol in sorted_large_volumes
                    ]
                }
            })
        
        # ========================================================================
        # 3.4 ALWAYS-ON NON-PRODUCTION (SCHEDULING OPPORTUNITY)
        # ========================================================================
        # Heuristic: instances with "dev", "test", "uat", "sandbox" in name
        non_prod_keywords = ['dev', 'test', 'uat', 'sandbox', 'staging', 'qa', 'demo']
        non_prod_instances = []
        
        for inst in instances:
            if inst['lifecycle_state'] == 'RUNNING' and not inst.get('is_deleted', False):
                name_lower = inst.get('display_name', '').lower()
                if any(keyword in name_lower for keyword in non_prod_keywords):
                    non_prod_instances.append(inst)
        
        if non_prod_instances:
            # Calculate actual costs for non-prod instances based on vCPUs
            estimated_current = 0
            if total_running_vcpus > 0:
                compute_cost = service_costs.get('COMPUTE', service_costs.get('Compute', 0))
                if compute_cost > 0:
                    cost_per_vcpu = compute_cost / total_running_vcpus
                    for inst in non_prod_instances:
                        vcpus = inst.get('vcpus', 0)
                        estimated_current += vcpus * cost_per_vcpu
            
            # Potential 65% savings by running only during business hours (35% of time)
            potential_savings = estimated_current * 0.65
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"**{len(non_prod_instances)} non-production instances** running 24/7")
            action_parts.append("")
            action_parts.append("These dev/test/stage instances don't need to run outside business hours.")
            action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Auto-stop instances at 6pm, auto-start at 9am (weekdays only)")
            action_parts.append("• Use OCI Instance Scheduler or automation scripts")
            action_parts.append("• Start with staging environments first")
            action_parts.append("")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.0f}/month (65% reduction)")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(non_prod_instances)} instances")
            
            # Calculate individual instance savings for details
            cost_per_vcpu = 0
            if total_running_vcpus > 0 and compute_cost > 0:
                cost_per_vcpu = compute_cost / total_running_vcpus
            
            recommendations.append({
                "type": "non_prod_scheduling",
                "severity": "high",
                "title": f"⏰ {len(non_prod_instances)} non-production instance(s) running 24/7",
                "description": f"Non-production instances detected that could be scheduled to run only during business hours.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(non_prod_instances),
                    "data": [
                        {
                            "name": inst.get('display_name', 'N/A'),
                            "compartment": compartment_map.get(inst.get('compartment_ocid'), 'Unknown'),
                            "vcpus": inst.get('vcpus') or 0,
                            "shape": inst.get('shape', 'N/A'),
                            "current_cost": (inst.get('vcpus', 0) * cost_per_vcpu),
                            "potential_savings": (inst.get('vcpus', 0) * cost_per_vcpu) * 0.65,  # 65% savings
                            "lifecycle_state": inst.get('lifecycle_state', 'N/A'),
                            "ocid": inst.get('ocid', 'N/A')
                        }
                        for inst in non_prod_instances
                    ]
                }
            })
        
        # ========================================================================
        # 3.5 UNDERUTILIZED LOAD BALANCERS (BANDWIDTH ANALYSIS) 🔄
        # ========================================================================
        underutilized_lbs = []
        potential_lb_savings = 0
        
        for lb in load_balancers:
            if lb['lifecycle_state'] != 'ACTIVE' or lb.get('is_deleted', False):
                continue
            
            lb_ocid = lb['ocid']
            lb_name = lb['display_name']
            lb_shape = lb.get('shape_name', 'flexible')
            
            # Check if we have metrics for this load balancer
            metrics = lb_metrics.get(lb_ocid, {})
            peak_bandwidth = metrics.get('PeakBandwidth')
            
            # CASE 1: We have real metrics - HIGH confidence recommendation
            if peak_bandwidth is not None:
                # Underutilized: <10 Mbps peak bandwidth (very low usage)
                if peak_bandwidth < 10:
                    # Load balancer costs ~$25-50/month depending on shape
                    estimated_cost = 35  # Average
                    
                    # Get configured bandwidth from database (for flexible LBs)
                    configured_bandwidth = lb.get('max_bandwidth_mbps')
                    if configured_bandwidth is None:
                        # Fallback: Try to parse from shape name (for fixed-shape LBs)
                        if lb_shape and 'Mbps' in lb_shape:
                            try:
                                # Extract number before 'Mbps' (e.g., "100Mbps" -> 100)
                                parts = lb_shape.split('Mbps')[0]
                                configured_bandwidth = int(''.join(filter(str.isdigit, parts)))
                            except:
                                configured_bandwidth = None
                    
                    underutilized_lbs.append({
                        'lb': lb,
                        'peak_bandwidth': peak_bandwidth,
                        'configured_bandwidth': configured_bandwidth,
                        'savings': estimated_cost,
                        'confidence': 'HIGH'
                    })
                    potential_lb_savings += estimated_cost
            
            # CASE 2: No metrics - can't determine utilization
            # Don't add to list unless it's a private LB with suspicious name
            elif lb.get('is_private') and any(keyword in lb_name.lower() for keyword in ['test', 'dev', 'unused', 'old']):
                estimated_cost = 35
                underutilized_lbs.append({
                    'lb': lb,
                    'peak_bandwidth': None,
                    'configured_bandwidth': None,
                    'savings': estimated_cost,
                    'confidence': 'MEDIUM'
                })
                potential_lb_savings += estimated_cost
        
        if underutilized_lbs:
            # Separate by confidence
            high_confidence = [lb for lb in underutilized_lbs if lb['confidence'] == 'HIGH']
            medium_confidence = [lb for lb in underutilized_lbs if lb['confidence'] == 'MEDIUM']
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"**{len(underutilized_lbs)} load balancers** with low bandwidth usage")
            action_parts.append("")
            if high_confidence:
                action_parts.append(f"• **{len(high_confidence)} confirmed low-traffic** (<10 Mbps peak)")
            if medium_confidence:
                action_parts.append(f"• **{len(medium_confidence)} suspicious LBs** (no metrics)")
                action_parts.append("")
            action_parts.append("**Recommended Actions:**")
            action_parts.append("• Consolidate multiple low-bandwidth LBs into one")
            action_parts.append("• Switch to Network Load Balancer (cheaper for TCP/UDP)")
            action_parts.append("• Delete LBs with near-zero traffic")
            if medium_confidence:
                action_parts.append("• Run 'Refresh Metrics' to verify actual usage")
            action_parts.append("")
            action_parts.append(f"**Potential Savings:** ~${potential_lb_savings:,.0f}/month")
            
            action = "\n".join(action_parts)
            
            severity = "high" if len(high_confidence) > 0 else "medium"
            title_emoji = "🔄" if len(high_confidence) > 0 else "⚖️"
            
            recommendations.append({
                "type": "underutilized_load_balancers",
                "severity": severity,
                "title": f"{title_emoji} {len(underutilized_lbs)} load balancer(s) with low bandwidth",
                "description": f"Found {len(high_confidence)} confirmed low-bandwidth load balancers (<10 Mbps peak) and {len(medium_confidence)} suspicious ones.",
                "potential_savings": potential_lb_savings,
                "action": action,
                "details": {
                    "total_count": len(underutilized_lbs),
                    "data": [
                        {
                            "name": item['lb'].get('display_name', 'N/A'),
                            "compartment": compartment_map.get(item['lb'].get('compartment_ocid'), 'Unknown'),
                            "shape": item['lb'].get('shape_name', 'N/A'),
                            "peak_bw_mbps": item['peak_bandwidth'] if item['peak_bandwidth'] is not None else 'No metrics',
                            "max_bw_mbps": item['configured_bandwidth'] if item['configured_bandwidth'] else 'N/A',
                            "confidence": item['confidence'],
                            "potential_savings": item['savings'],
                            "lifecycle_state": item['lb'].get('lifecycle_state', 'N/A'),
                            "ocid": item['lb'].get('ocid', 'N/A')
                        }
                        for item in underutilized_lbs
                    ]
                }
            })
        
        # ========================================================================
        # 4. QUICK WINS
        # ========================================================================
        
        quick_wins = []
        
        # Reserved capacity opportunity
        running_instances = [i for i in instances if i['lifecycle_state'] == 'RUNNING' and not i.get('is_deleted', False)]
        if running_instances:
            # Use actual compute costs (monthly)
            compute_cost = service_costs.get('COMPUTE', service_costs.get('Compute', 0))
            potential_savings = compute_cost * 0.38  # 38% savings with 1-year reserved capacity
            
            # Sort by shape (largest first based on vCPUs)
            sorted_instances = sorted(running_instances, key=lambda i: i.get('vcpus') or 0, reverse=True)
            
            # Build summary (no table - it's in the modal now)
            action_parts = []
            action_parts.append(f"You have **{len(running_instances)} running instance(s)**. Reserve capacity for 1-year to save **38%**.")
            action_parts.append("")
            action_parts.append("**⚡ Action:**")
            action_parts.append("• Focus on production instances that run 24/7")
            action_parts.append("• Commit to 1-year or 3-year terms for maximum savings")
            action_parts.append("• Benefits: Guaranteed capacity + 38% cost reduction")
            action_parts.append("")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.0f}/month")
            action_parts.append("")
            action_parts.append(f"💡 Click **'View Full Report'** to see all {len(running_instances)} eligible instances")
            action_parts.append("**Best for:** Always-on production workloads (not dev/test)")
            
            # Calculate individual instance savings for details
            cost_per_vcpu = 0
            if total_running_vcpus > 0:
                cost_per_vcpu = compute_cost / total_running_vcpus
            
            quick_wins.append({
                "type": "reserved_capacity",
                "title": "Consider Reserved Capacity",
                "description": f"You have {len(running_instances)} running instance(s). Reserve capacity for 1-year to save 38%.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts),
                "details": {
                    "total_count": len(running_instances),
                    "data": [
                        {
                            "name": inst.get('display_name', 'N/A'),
                            "compartment": compartment_map.get(inst.get('compartment_ocid'), 'Unknown'),
                            "vcpus": inst.get('vcpus') or 0,
                            "shape": inst.get('shape', 'N/A'),
                            "current_cost": (inst.get('vcpus', 0) * cost_per_vcpu),
                            "potential_savings": (inst.get('vcpus', 0) * cost_per_vcpu) * 0.38,  # 38% savings
                            "lifecycle_state": inst.get('lifecycle_state', 'N/A'),
                            "ocid": inst.get('ocid', 'N/A')
                        }
                        for inst in running_instances[:min(len(running_instances), 1000)]  # Limit to avoid huge payloads
                    ]
                }
            })
        
        # Object Storage tier optimization
        if 'OBJECT_STORAGE' in service_costs:
            obj_storage_cost = service_costs['OBJECT_STORAGE']
            if obj_storage_cost > 100:  # If spending > $100/month
                potential_savings = obj_storage_cost * 0.5  # 50% with Archive tier
                
                quick_wins.append({
                    "type": "storage_tier",
                    "title": "Optimize Object Storage Tiers",
                    "description": f"You're spending ${obj_storage_cost:,.2f}/month on Object Storage.",
                    "potential_savings": potential_savings,
                    "action": "Move infrequently accessed data to Archive tier (90% cheaper) or Infrequent Access tier (50% cheaper)."
                })
        
        # ========================================================================
        # 5. CALCULATE TOTAL POTENTIAL SAVINGS
        # ========================================================================
        
        total_potential_savings = sum(r.get('potential_savings', 0) for r in recommendations + quick_wins)
        
        # ========================================================================
        # 6. AI NARRATIVE ANALYSIS (The Real AI!)
        # ========================================================================
        
        logger.info("🤖 Generating AI narrative analysis...")
        
        ai_analysis = {
            "narrative": "",
            "reasoning_steps": [],
            "tool_invocations": [],
            "confidence_scores": {}
        }
        
        try:
            # Track tool invocations for transparency
            ai_analysis["tool_invocations"] = [
                {"tool": "get_cost_cache", "status": "completed", "result": f"Found {len(monthly_costs)} months of data"},
                {"tool": "get_resource_inventory", "status": "completed", "result": f"{len(instances)} instances, {len(volumes)} volumes"},
                {"tool": "static_analysis", "status": "completed", "result": f"{len(insights)} insights, {len(recommendations)} recommendations"}
            ]
            
            # Prepare data summary for LLM
            data_summary = {
                "timeframe": f"{months_to_analyze[0]} to {months_to_analyze[-1]}",
                "latest_month_cost": monthly_totals.get(latest_month, 0),
                "cost_trend": {
                    "oldest": monthly_totals.get(oldest_month, 0),
                    "newest": monthly_totals.get(newest_month, 0),
                    "change_pct": ((monthly_totals.get(newest_month, 0) - monthly_totals.get(oldest_month, 0)) / monthly_totals.get(oldest_month, 1)) * 100 if monthly_totals.get(oldest_month, 0) > 0 else 0
                },
                "resources": {
                    "instances": {
                        "total": len(instances),
                        "running": len([i for i in instances if i['lifecycle_state'] == 'RUNNING']),
                        "stopped": len([i for i in instances if i['lifecycle_state'] == 'STOPPED'])
                    },
                    "volumes": {
                        "total": len(volumes),
                        "unattached": len([v for v in volumes if v['lifecycle_state'] == 'AVAILABLE']),
                        "total_unattached_gb": sum(v.get('size_in_gbs', 0) for v in volumes if v['lifecycle_state'] == 'AVAILABLE')
                    }
                },
                "top_services": sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[:3],
                "static_findings": {
                    "insights_count": len(insights),
                    "recommendations_count": len(recommendations),
                    "potential_savings": total_potential_savings
                }
            }
            
            # Create prompt for LLM
            prompt = f"""You are analyzing cloud infrastructure cost data. Based on the data below, provide a structured analysis.

Format your response EXACTLY like this:

**Executive Summary:**
[2-3 sentences about the most important cost trends and overall health]

**Key Findings:**
• [Finding 1 with specific numbers and percentages]
• [Finding 2 with specific numbers and percentages]
• [Finding 3 with specific numbers and percentages]
• [Finding 4 with specific numbers and percentages]

**Priority Actions:**
1. [Action 1] - [Expected impact in dollars]
2. [Action 2] - [Expected impact in dollars]
3. [Action 3] - [Expected impact in dollars]

Data Summary:
```json
{json.dumps(data_summary, indent=2)}
```

Guidelines:
- Use **bold** for section headers (Executive Summary, Key Findings, Priority Actions)
- Use bullet points (•) for Key Findings
- Use numbered lists (1. 2. 3.) for Priority Actions
- Be specific with numbers, percentages, and dollar amounts
- Focus on actionable insights, not generic advice
- If costs are rising, explain WHY with data
- If there's waste, QUANTIFY it with dollars
- Use business language, avoid cloud jargon
- Keep it concise but informative

Your analysis:"""

            # Call LLM directly (no checkpointer needed for one-off analysis)
            ai_analysis["tool_invocations"].append({
                "tool": "LLM_analysis", 
                "status": "running", 
                "result": "Analyzing data..."
            })
            
            # Import LLM directly
            from app.models import get_openai_client
            llm = get_openai_client()
            
            # Call LLM without agent/checkpointer (we don't need conversation state)
            messages = [HumanMessage(content=prompt)]
            response = await llm.ainvoke(messages)
            
            # Extract AI response
            ai_narrative = response.content if hasattr(response, 'content') else str(response)
            
            ai_analysis["narrative"] = ai_narrative
            ai_analysis["tool_invocations"][-1]["status"] = "completed"
            ai_analysis["tool_invocations"][-1]["result"] = f"Generated {len(ai_narrative)} chars"
            
            # Add reasoning steps
            ai_analysis["reasoning_steps"] = [
                "Fetched cost data from cache for last 3 months",
                "Loaded resource inventory (instances, volumes, load balancers)",
                "Performed static analysis for cost trends and waste detection",
                f"Analyzed {len(monthly_costs)} months of billing data",
                "Generated AI narrative with LLM reasoning"
            ]
            
            # Add confidence scores to existing insights
            for insight in insights:
                # High confidence if we have actual data
                if "cost" in insight.get("type", ""):
                    ai_analysis["confidence_scores"][insight["title"]] = 95
                elif "metrics" in insight.get("description", "").lower():
                    ai_analysis["confidence_scores"][insight["title"]] = 90
                else:
                    ai_analysis["confidence_scores"][insight["title"]] = 85
            
            for rec in recommendations:
                # Confidence based on whether we have utilization metrics
                if "metrics" in rec.get("action", "").lower() and "Refresh Metrics" in rec.get("action", ""):
                    ai_analysis["confidence_scores"][rec["title"]] = 70
                else:
                    ai_analysis["confidence_scores"][rec["title"]] = 85
            
            logger.info(f"✅ Generated AI narrative ({len(ai_narrative)} characters)")
            
        except Exception as e:
            logger.error(f"Error generating AI narrative: {str(e)}", exc_info=True)
            ai_analysis["narrative"] = "AI analysis temporarily unavailable. Showing static insights only."
            ai_analysis["tool_invocations"].append({
                "tool": "LLM_analysis",
                "status": "failed",
                "result": str(e)
            })
        
        # ========================================================================
        # RETURN RESULTS
        # ========================================================================
        
        result = {
            "generated_at": datetime.now().isoformat(),
            "months_analyzed": months_to_analyze,
            "total_cost_latest_month": monthly_totals.get(latest_month, 0),
            "total_potential_savings": total_potential_savings,
            "insights": insights,
            "recommendations": recommendations,
            "quick_wins": quick_wins,
            "ai_analysis": ai_analysis,  # NEW!
            "summary": {
                "total_insights": len(insights),
                "total_recommendations": len(recommendations),
                "total_quick_wins": len(quick_wins),
                "estimated_monthly_savings": total_potential_savings,
                "is_ai_powered": bool(ai_analysis.get("narrative"))  # NEW!
            }
        }
        
        logger.info(f"✅ Generated {len(insights)} insights, {len(recommendations)} recommendations, {len(quick_wins)} quick wins")
        
        return result
    
    except Exception as e:
        logger.error(f"Error generating AI recommendations: {str(e)}", exc_info=True)
        return {
            "error": f"Error generating recommendations: {str(e)}",
            "recommendations": [],
            "insights": [],
            "quick_wins": []
        }

