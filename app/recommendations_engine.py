"""
AI-Powered Recommendations Engine

Generates cost optimization insights using cached data and AI analysis.
"""

import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

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
        # 1. COST TREND INSIGHTS
        # ========================================================================
        insights = []
        
        # Calculate monthly totals
        monthly_totals = {}
        for month, costs in monthly_costs.items():
            monthly_totals[month] = sum(c['cost'] for c in costs)
        
        if len(monthly_totals) >= 2:
            sorted_months = sorted(monthly_totals.keys())
            oldest_month = sorted_months[0]
            newest_month = sorted_months[-1]
            
            oldest_total = monthly_totals[oldest_month]
            newest_total = monthly_totals[newest_month]
            
            change = newest_total - oldest_total
            change_pct = (change / oldest_total * 100) if oldest_total > 0 else 0
            
            if abs(change_pct) > 5:
                trend = "increased" if change > 0 else "decreased"
                
                # Analyze which services drove the change
                oldest_costs = monthly_costs[oldest_month]
                newest_costs = monthly_costs[newest_month]
                
                # Aggregate by service for both months
                oldest_by_service = {}
                for cost in oldest_costs:
                    service = cost['service']
                    oldest_by_service[service] = oldest_by_service.get(service, 0) + cost['cost']
                
                newest_by_service = {}
                for cost in newest_costs:
                    service = cost['service']
                    newest_by_service[service] = newest_by_service.get(service, 0) + cost['cost']
                
                # Calculate service-level changes
                service_increases = []
                service_decreases = []
                all_services = set(oldest_by_service.keys()) | set(newest_by_service.keys())
                
                for service in all_services:
                    old_cost = oldest_by_service.get(service, 0)
                    new_cost = newest_by_service.get(service, 0)
                    svc_change = new_cost - old_cost
                    
                    if abs(svc_change) > 10:  # Only show significant changes (>$10)
                        if svc_change > 0:
                            service_increases.append({
                                'service': service,
                                'change': svc_change,
                                'old_cost': old_cost,
                                'new_cost': new_cost
                            })
                        else:
                            service_decreases.append({
                                'service': service,
                                'change': svc_change,
                                'old_cost': old_cost,
                                'new_cost': new_cost
                            })
                
                # Sort by change amount (biggest first)
                service_increases.sort(key=lambda x: x['change'], reverse=True)
                service_decreases.sort(key=lambda x: abs(x['change']), reverse=True)
                
                # Build detailed action
                action_parts = []
                
                if change > 0:  # Overall increase
                    # Show top increases (what's causing the problem)
                    if service_increases:
                        action_parts.append("**Top cost increases:**")
                        for idx, svc in enumerate(service_increases[:3], 1):
                            action_parts.append(
                                f"{idx}. **{svc['service']}** +${svc['change']:,.2f} "
                                f"(${svc['old_cost']:,.2f} → ${svc['new_cost']:,.2f})"
                            )
                        
                        # Mention decreases as a footnote
                        if service_decreases:
                            total_decreased = sum(abs(s['change']) for s in service_decreases)
                            action_parts.append(
                                f"\n*Note: ${total_decreased:,.2f} was saved from {len(service_decreases)} service(s), "
                                f"but increases outpaced savings.*"
                            )
                    else:
                        action_parts.append("New services or resources were added.")
                else:  # Overall decrease
                    # Show top decreases (what's saving money)
                    if service_decreases:
                        action_parts.append("**Top cost savings:**")
                        for idx, svc in enumerate(service_decreases[:3], 1):
                            action_parts.append(
                                f"{idx}. **{svc['service']}** -${abs(svc['change']):,.2f} "
                                f"(${svc['old_cost']:,.2f} → ${svc['new_cost']:,.2f})"
                            )
                
                action = "\n".join(action_parts) if action_parts else "Minor changes across multiple services."
                
                insights.append({
                    "type": "cost_trend",
                    "severity": "high" if change_pct > 20 else "medium",
                    "title": f"Costs {trend} {abs(change_pct):.1f}% over last 3 months",
                    "description": f"Your total costs went from ${oldest_total:,.2f} ({oldest_month}) to ${newest_total:,.2f} ({newest_month}), a change of ${change:+,.2f}.",
                    "action": action
                })
        
        # ========================================================================
        # 2. SERVICE ANALYSIS
        # ========================================================================
        
        # Aggregate costs by service for latest month
        latest_month = sorted(monthly_costs.keys())[-1]
        latest_costs = monthly_costs[latest_month]
        
        service_costs = {}
        for cost in latest_costs:
            service = cost['service']
            service_costs[service] = service_costs.get(service, 0) + cost['cost']
        
        total_cost = sum(service_costs.values())
        
        # Find services > 40% of total
        dominant_services = []
        for service, cost in service_costs.items():
            pct = (cost / total_cost * 100) if total_cost > 0 else 0
            if pct > 40:
                dominant_services.append((service, cost, pct))
        
        if dominant_services:
            for service, cost, pct in dominant_services:
                # Provide service-specific recommendations
                action = ""
                if service in ["COMPUTE", "Compute"]:
                    running = [i for i in instances if i['lifecycle_state'] == 'RUNNING']
                    stopped = [i for i in instances if i['lifecycle_state'] == 'STOPPED']
                    
                    # Check if we have metrics to show underutilization
                    underutilized_count = 0
                    potential_underutil_savings = 0
                    
                    for inst in running:
                        if not inst.get('is_deleted', False):
                            metrics = instance_metrics.get(inst['ocid'], {})
                            cpu = metrics.get('CpuUtilization')
                            mem = metrics.get('MemoryUtilization')
                            
                            if cpu is not None and mem is not None and cpu < 40 and mem < 40:
                                underutilized_count += 1
                                vcpus = inst.get('vcpus') or 0
                                if vcpus > 0:
                                    potential_underutil_savings += (vcpus * 50) * 0.50
                    
                    action = f"**Optimization tips for Compute:**\n"
                    
                    if underutilized_count > 0:
                        action += f"• **{underutilized_count} underutilized instances** detected (CPU & Memory <40%) - Downsize to save ~${potential_underutil_savings:.0f}/month\n"
                    
                    action += f"• {len(running)} running instance(s) - Consider Reserved Capacity (38% savings)\n"
                    
                    if stopped:
                        action += f"• {len(stopped)} stopped instance(s) - Terminate to save ~${len(stopped) * 50}/month\n"
                    
                    if underutilized_count == 0 and len(instance_metrics) < len(running):
                        action += f"• Run 'Refresh Metrics' to analyze {len(running) - len(instance_metrics)} instances without utilization data"
                
                elif service in ["BLOCK_STORAGE", "Block Storage"]:
                    available_vols = [v for v in volumes if v['lifecycle_state'] == 'AVAILABLE']
                    total_gb = sum(v.get('size_in_gbs', 0) for v in available_vols)
                    action = f"**Optimization tips for Block Storage:**\n"
                    action += f"• {len(available_vols)} volume(s) in AVAILABLE state ({total_gb:,.0f} GB)\n"
                    action += f"• Delete unattached volumes (~${total_gb * 0.0255:.2f}/month savings)\n"
                    action += f"• Consider Balanced or Lower Cost performance tiers for non-critical workloads"
                
                elif service in ["OBJECT_STORAGE", "Object Storage"]:
                    action = f"**Optimization tips for Object Storage:**\n"
                    action += f"• Move infrequently accessed data to Archive tier (90% cheaper)\n"
                    action += f"• Use Infrequent Access tier for rarely used data (50% cheaper)\n"
                    action += f"• Enable Object Lifecycle Policies to automate tiering"
                
                elif service in ["DATABASE", "Database", "OCI Database Service with PostgreSQL"]:
                    action = f"**Optimization tips for Database:**\n"
                    action += f"• Review database shapes for rightsizing\n"
                    action += f"• Consider Autonomous Database for automatic optimization\n"
                    action += f"• Stop non-production databases during off-hours"
                
                elif service in ["FILE_STORAGE", "File Storage"]:
                    action = f"**Optimization tips for File Storage:**\n"
                    action += f"• Delete unused file systems\n"
                    action += f"• Review snapshot retention policies\n"
                    action += f"• Consider compressing data to reduce storage"
                
                elif service in ["LOAD_BALANCER", "Load Balancer"]:
                    active_lbs = [lb for lb in load_balancers if lb['lifecycle_state'] == 'ACTIVE']
                    
                    # Check for low-bandwidth load balancers
                    low_bandwidth_count = 0
                    low_bandwidth_savings = 0
                    
                    for lb in active_lbs:
                        if not lb.get('is_deleted', False):
                            metrics = lb_metrics.get(lb['ocid'], {})
                            peak_bandwidth = metrics.get('PeakBandwidth')
                            
                            # Low bandwidth: < 10 Mbps average peak
                            if peak_bandwidth is not None and peak_bandwidth < 10:
                                low_bandwidth_count += 1
                                low_bandwidth_savings += 35
                    
                    action = f"**Optimization tips for Load Balancers:**\n"
                    
                    if low_bandwidth_count > 0:
                        action += f"• **{low_bandwidth_count} low-bandwidth load balancers** detected (<10 Mbps peak) - Downsize or consolidate to save ~${low_bandwidth_savings}/month\n"
                    
                    action += f"• {len(active_lbs)} active load balancers - Review if all are needed\n"
                    action += f"• Consider Network Load Balancers (cheaper for simple TCP/UDP forwarding)\n"
                    
                    if low_bandwidth_count == 0 and len(lb_metrics) < len(active_lbs):
                        action += f"• Run 'Refresh Metrics' to analyze {len(active_lbs) - len(lb_metrics)} load balancers without bandwidth data"
                
                else:
                    action = f"Review {service} resources for optimization opportunities."
                
                insights.append({
                    "type": "dominant_service",
                    "severity": "medium",
                    "title": f"{service} dominates your costs",
                    "description": f"{service} accounts for {pct:.1f}% (${cost:,.2f}) of your total spending in {latest_month}.",
                    "action": action
                })
        
        # ========================================================================
        # 3. RESOURCE-BASED RECOMMENDATIONS
        # ========================================================================
        
        recommendations = []
        
        # ========================================================================
        # 3.1 STOPPED INSTANCES (HIGH PRIORITY)
        # ========================================================================
        stopped_instances = [i for i in instances if i['lifecycle_state'] == 'STOPPED' and not i.get('is_deleted', False)]
        
        if stopped_instances:
            # Estimate cost (rough estimate: $50/month per stopped instance for storage)
            estimated_cost = len(stopped_instances) * 50
            
            # Build detailed list
            action_parts = []
            action_parts.append(f"**🛑 {len(stopped_instances)} stopped instances still costing ~${estimated_cost}/month:**")
            action_parts.append("")
            action_parts.append("| Instance | Compartment | Shape | Action |")
            action_parts.append("|----------|-------------|-------|--------|")
            
            for inst in stopped_instances[:15]:  # Show top 15
                name = inst.get('display_name', 'N/A')[:25]
                compartment = compartment_map.get(inst.get('compartment_ocid'), 'Unknown')[:20]
                vcpus = inst.get('vcpus') or 0
                memory = inst.get('memory_in_gbs') or 0
                shape_display = f"{vcpus}vCPU/{memory}GB" if vcpus and memory else inst.get('shape', 'N/A')[:15]
                
                action_parts.append(
                    f"| {name} | {compartment} | {shape_display} | Terminate |"
                )
            
            if len(stopped_instances) > 15:
                action_parts.append(f"\n*...and {len(stopped_instances) - 15} more stopped instances*")
            
            action_parts.append("\n**Recommended Actions:**")
            action_parts.append("1. Create backups if needed")
            action_parts.append("2. Terminate unused instances")
            action_parts.append("3. Remove associated boot volumes")
            action_parts.append("4. **Estimated Savings:** ~${:,.0f}/month".format(estimated_cost))
            
            recommendations.append({
                "type": "stopped_instances",
                "severity": "high",
                "title": f"🛑 {len(stopped_instances)} stopped instance(s) still incurring costs",
                "description": f"Stopped compute instances still cost ~$50/month each for boot volume storage.",
                "potential_savings": estimated_cost,
                "action": "\n".join(action_parts)
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
            
            # Build detailed table
            action_parts = []
            action_parts.append(f"**💾 {len(unattached_volumes)} unattached volumes costing ~${estimated_cost:,.2f}/month:**")
            action_parts.append("")
            action_parts.append("| Volume | Compartment | Size | Monthly Cost | Action |")
            action_parts.append("|--------|-------------|------|--------------|--------|")
            
            # Sort by size (largest first)
            sorted_volumes = sorted(unattached_volumes, key=lambda v: v.get('size_in_gbs') or 0, reverse=True)
            
            for vol in sorted_volumes[:15]:  # Show top 15
                name = vol.get('display_name', 'N/A')[:20]
                compartment = compartment_map.get(vol.get('compartment_ocid'), 'Unknown')[:15]
                size_gb = vol.get('size_in_gbs') or 0
                monthly_cost = size_gb * 0.0255
                
                action_parts.append(
                    f"| {name} | {compartment} | {size_gb} GB | ${monthly_cost:.2f} | Delete/Attach |"
                )
            
            if len(unattached_volumes) > 15:
                action_parts.append(f"\n*...and {len(unattached_volumes) - 15} more unattached volumes*")
            
            action_parts.append(f"\n**Total:** {total_gb:,.0f} GB unattached storage costing ${estimated_cost:,.2f}/month")
            action_parts.append("**Action:** Delete unused volumes or attach them to instances")
            
            recommendations.append({
                "type": "unattached_volumes",
                "severity": "medium",
                "title": f"💾 {len(unattached_volumes)} unattached volume(s) found",
                "description": f"Unattached block volumes ({total_gb:,.0f} GB total) are costing you money without being used.",
                "potential_savings": estimated_cost,
                "action": "\n".join(action_parts)
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
            
            # Build detailed table
            action_parts = []
            action_parts.append(f"**📦 {len(large_volumes)} large volumes ({total_gb:,.0f} GB) costing ~${current_cost:,.2f}/month:**")
            action_parts.append("")
            action_parts.append("| Volume | Compartment | Size | Current Cost | Potential Savings |")
            action_parts.append("|--------|-------------|------|--------------|-------------------|")
            
            # Sort by size (largest first)
            sorted_large_volumes = sorted(large_volumes, key=lambda v: v.get('size_in_gbs') or 0, reverse=True)
            
            for vol in sorted_large_volumes[:15]:  # Show top 15
                name = vol.get('display_name', 'N/A')[:20]
                compartment = compartment_map.get(vol.get('compartment_ocid'), 'Unknown')[:15]
                size_gb = vol.get('size_in_gbs') or 0
                monthly_cost = size_gb * 0.0255
                tier_savings = monthly_cost * 0.30  # 30% savings with lower tier
                
                action_parts.append(
                    f"| {name} | {compartment} | {size_gb:,} GB | ${monthly_cost:.2f} | ${tier_savings:.2f} |"
                )
            
            if len(large_volumes) > 15:
                action_parts.append(f"\n*...and {len(large_volumes) - 15} more large volumes*")
            
            action_parts.append(f"\n**Recommendation:** Switch from Ultra High Performance to Balanced or Lower Cost tier")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.2f}/month (30% reduction)")
            
            recommendations.append({
                "type": "large_volumes",
                "severity": "medium",
                "title": f"📦 {len(large_volumes)} large volume(s) could use lower-cost tiers",
                "description": f"Large volumes ({total_gb:,.0f} GB total) might benefit from Balanced or Lower Cost performance tiers.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts)
            })
        
        # ========================================================================
        # 3.4 INSTANCE RIGHTSIZING (WITH REAL UTILIZATION DATA!) 🎯
        # ========================================================================
        underutilized_instances = []
        potential_rightsizing_savings = 0
        
        for inst in instances:
            if inst['lifecycle_state'] != 'RUNNING' or inst.get('is_deleted', False):
                continue
            
            inst_ocid = inst['ocid']
            inst_name = inst['display_name']
            vcpus = inst.get('vcpus') or 0
            memory = inst.get('memory_in_gbs') or 0
            
            # Skip small instances
            if vcpus < 4:
                continue
            
            # Check if we have metrics for this instance
            metrics = instance_metrics.get(inst_ocid, {})
            cpu_util = metrics.get('CpuUtilization')
            mem_util = metrics.get('MemoryUtilization')
            
            # CASE 1: We have real metrics - HIGH confidence recommendation
            if cpu_util is not None and mem_util is not None:
                if cpu_util < 40 and mem_util < 40:
                    # Estimate savings: 50% reduction in size = 50% cost savings
                    estimated_cost = vcpus * 50  # Rough: $50/vCPU/month
                    savings = estimated_cost * 0.50
                    
                    underutilized_instances.append({
                        'instance': inst,
                        'cpu': cpu_util,
                        'memory': mem_util,
                        'savings': savings,
                        'confidence': 'HIGH'
                    })
                    potential_rightsizing_savings += savings
            
            # CASE 2: No metrics but large instance - MEDIUM confidence
            elif (vcpus >= 8 or memory >= 64):
                estimated_cost = vcpus * 50
                savings = estimated_cost * 0.30  # Conservative estimate
                
                underutilized_instances.append({
                    'instance': inst,
                    'cpu': None,
                    'memory': None,
                    'savings': savings,
                    'confidence': 'MEDIUM'
                })
                potential_rightsizing_savings += savings
        
        if underutilized_instances:
            # Separate by confidence
            high_confidence = [i for i in underutilized_instances if i['confidence'] == 'HIGH']
            medium_confidence = [i for i in underutilized_instances if i['confidence'] == 'MEDIUM']
            
            # Build action message with detailed table
            action_parts = []
            
            if high_confidence:
                action_parts.append(f"**✅ {len(high_confidence)} confirmed underutilized (with monitoring data):**")
                action_parts.append("")
                action_parts.append("| Instance | Compartment | Current Shape | CPU % | Memory % | Recommendation |")
                action_parts.append("|----------|-------------|---------------|-------|----------|----------------|")
                
                for item in high_confidence[:10]:  # Show top 10
                    inst = item['instance']
                    vcpus = inst.get('vcpus') or 0
                    memory = inst.get('memory_in_gbs') or 0
                    compartment = compartment_map.get(inst.get('compartment_ocid'), 'Unknown')[:15]
                    cpu_pct = item['cpu']
                    mem_pct = item['memory']
                    
                    # Suggest smaller shape (half the size if heavily underutilized)
                    if cpu_pct < 20 and mem_pct < 20:
                        suggested_vcpus = max(2, vcpus // 2) if vcpus > 0 else 2
                        suggested_memory = max(16, memory // 2) if memory > 0 else 16
                        recommendation = f"→ {suggested_vcpus}vCPU/{suggested_memory}GB"
                    else:
                        suggested_vcpus = max(2, int(vcpus * 0.75)) if vcpus > 0 else 2
                        suggested_memory = max(16, int(memory * 0.75)) if memory > 0 else 16
                        recommendation = f"→ {suggested_vcpus}vCPU/{suggested_memory}GB"
                    
                    action_parts.append(
                        f"| {inst['display_name'][:20]} | {compartment} | {vcpus}vCPU/{memory}GB | {cpu_pct:.1f}% | {mem_pct:.1f}% | {recommendation} |"
                    )
                
                if len(high_confidence) > 10:
                    action_parts.append(f"\n*...and {len(high_confidence) - 10} more underutilized instances*")
                
                action_parts.append("\n**Estimated Savings:** ~${:,.0f}/month by rightsizing these instances".format(
                    sum(item['savings'] for item in high_confidence)
                ))
            
            if medium_confidence:
                action_parts.append(f"\n**⚠️ {len(medium_confidence)} large instances (no recent metrics):**")
                for item in medium_confidence[:5]:
                    inst = item['instance']
                    action_parts.append(
                        f"• **{inst['display_name']}** ({inst.get('vcpus', 0)} vCPUs, {inst.get('memory_in_gbs', 0)} GB) - "
                        f"Run metrics sync to get utilization data"
                    )
            
            action = "\n".join(action_parts)
            
            severity = "high" if len(high_confidence) > 0 else "medium"
            title_emoji = "🎯" if len(high_confidence) > 0 else "🔧"
            
            recommendations.append({
                "type": "rightsizing",
                "severity": severity,
                "title": f"{title_emoji} {len(underutilized_instances)} instance(s) for rightsizing review",
                "description": f"Found {len(high_confidence)} confirmed underutilized instances and {len(medium_confidence)} large instances to review.",
                "potential_savings": potential_rightsizing_savings,
                "action": action
            })
        
        # ========================================================================
        # 3.5 ALWAYS-ON NON-PRODUCTION (SCHEDULING OPPORTUNITY)
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
            # Potential 65% savings by running only during business hours (35% of time)
            estimated_current = len(non_prod_instances) * 100  # $100/month per instance
            potential_savings = estimated_current * 0.65
            
            # Build detailed table
            action_parts = []
            action_parts.append(f"**⏰ {len(non_prod_instances)} non-production instances running 24/7:**")
            action_parts.append("")
            action_parts.append("| Instance | Compartment | Shape | Current Cost | Savings (65%) |")
            action_parts.append("|----------|-------------|-------|--------------|---------------|")
            
            for inst in non_prod_instances[:15]:  # Show top 15
                name = inst.get('display_name', 'N/A')[:20]
                compartment = compartment_map.get(inst.get('compartment_ocid'), 'Unknown')[:15]
                vcpus = inst.get('vcpus') or 0
                memory = inst.get('memory_in_gbs') or 0
                shape_display = f"{vcpus}vCPU/{memory}GB" if vcpus and memory else inst.get('shape', 'N/A')[:15]
                
                # Estimate cost based on shape
                monthly_cost = 100  # Rough estimate
                savings = monthly_cost * 0.65
                
                action_parts.append(
                    f"| {name} | {compartment} | {shape_display} | ${monthly_cost:.0f} | ${savings:.0f} |"
                )
            
            if len(non_prod_instances) > 15:
                action_parts.append(f"\n*...and {len(non_prod_instances) - 15} more non-prod instances*")
            
            action_parts.append(f"\n**Recommendation:** Auto-stop instances outside business hours (9am-6pm weekdays)")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.0f}/month (65% reduction)")
            action_parts.append("**Implementation:** Use OCI Instance Scheduler or custom scripts")
            
            recommendations.append({
                "type": "non_prod_scheduling",
                "severity": "high",
                "title": f"⏰ {len(non_prod_instances)} non-production instance(s) running 24/7",
                "description": f"Non-production instances detected that could be scheduled to run only during business hours.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts)
            })
        
        # ========================================================================
        # 3.6 UNDERUTILIZED LOAD BALANCERS (BANDWIDTH ANALYSIS) 🔄
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
                    
                    # Extract configured bandwidth from shape if possible
                    configured_bandwidth = None
                    if 'Mbps' in lb_shape:
                        try:
                            configured_bandwidth = int(''.join(filter(str.isdigit, lb_shape.split('Mbps')[0])))
                        except:
                            pass
                    
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
            
            # Build action message with detailed list
            action_parts = []
            
            if high_confidence:
                action_parts.append(f"**✅ {len(high_confidence)} confirmed underutilized (with bandwidth metrics):**")
                action_parts.append("")
                action_parts.append("| Load Balancer | Compartment | Shape | Peak Bandwidth | Recommendation |")
                action_parts.append("|--------------|-------------|-------|----------------|----------------|")
                
                for item in high_confidence[:10]:  # Show top 10
                    lb = item['lb']
                    compartment = compartment_map.get(lb.get('compartment_ocid'), 'Unknown')[:15]
                    shape = lb.get('shape_name', 'N/A')[:15]
                    peak = item['peak_bandwidth']
                    configured = item['configured_bandwidth']
                    
                    if configured and configured > 100:
                        recommendation = f"↓ {configured // 2} Mbps"
                    elif peak < 1:
                        recommendation = "Delete (zero traffic)"
                    else:
                        recommendation = "Consolidate/downsize"
                    
                    action_parts.append(
                        f"| {lb['display_name'][:20]} | {compartment} | {shape} | {peak:.1f} Mbps | {recommendation} |"
                    )
                
                if len(high_confidence) > 10:
                    action_parts.append(f"\n*...and {len(high_confidence) - 10} more*")
                
                action_parts.append("\n**Potential Actions:**")
                action_parts.append("• Consolidate multiple low-bandwidth LBs into one")
                action_parts.append("• Switch to Network Load Balancer (cheaper for TCP/UDP)")
                action_parts.append("• Delete LBs with near-zero traffic")
            
            if medium_confidence:
                action_parts.append(f"\n**⚠️ {len(medium_confidence)} suspicious load balancers (no metrics):**")
                for item in medium_confidence[:3]:
                    lb = item['lb']
                    action_parts.append(
                        f"• **{lb['display_name']}** - Run metrics sync to verify usage"
                    )
            
            action = "\n".join(action_parts)
            
            severity = "high" if len(high_confidence) > 0 else "medium"
            title_emoji = "🔄" if len(high_confidence) > 0 else "⚖️"
            
            recommendations.append({
                "type": "underutilized_load_balancers",
                "severity": severity,
                "title": f"{title_emoji} {len(underutilized_lbs)} load balancer(s) with low bandwidth",
                "description": f"Found {len(high_confidence)} confirmed low-bandwidth load balancers (<10 Mbps peak) and {len(medium_confidence)} suspicious ones.",
                "potential_savings": potential_lb_savings,
                "action": action
            })
        
        # ========================================================================
        # 4. QUICK WINS
        # ========================================================================
        
        quick_wins = []
        
        # Reserved capacity opportunity
        running_instances = [i for i in instances if i['lifecycle_state'] == 'RUNNING' and not i.get('is_deleted', False)]
        if running_instances:
            # Rough estimate: $100/instance/month, 38% savings with reserved
            estimated_current_cost = len(running_instances) * 100
            potential_savings = estimated_current_cost * 0.38
            
            # Build detailed table for top production instances
            action_parts = []
            action_parts.append(f"**💰 {len(running_instances)} running instances eligible for Reserved Capacity:**")
            action_parts.append("")
            action_parts.append("| Instance | Compartment | Shape | Est. Monthly Cost | Savings (38%) |")
            action_parts.append("|----------|-------------|-------|-------------------|---------------|")
            
            # Sort by shape (largest first based on vCPUs)
            sorted_instances = sorted(running_instances, key=lambda i: i.get('vcpus') or 0, reverse=True)
            
            for inst in sorted_instances[:15]:  # Show top 15 largest
                name = inst.get('display_name', 'N/A')[:20]
                compartment = compartment_map.get(inst.get('compartment_ocid'), 'Unknown')[:15]
                vcpus = inst.get('vcpus') or 0
                memory = inst.get('memory_in_gbs') or 0
                shape_display = f"{vcpus}vCPU/{memory}GB" if vcpus and memory else inst.get('shape', 'N/A')[:15]
                
                # Estimate cost based on vCPUs
                monthly_cost = max(50, vcpus * 25) if vcpus > 0 else 100  # ~$25/vCPU
                savings = monthly_cost * 0.38
                
                action_parts.append(
                    f"| {name} | {compartment} | {shape_display} | ${monthly_cost:.0f} | ${savings:.0f} |"
                )
            
            if len(running_instances) > 15:
                action_parts.append(f"\n*...and {len(running_instances) - 15} more running instances*")
            
            action_parts.append(f"\n**Recommendation:** Purchase Reserved Capacity for 1-year commitment")
            action_parts.append(f"**Potential Savings:** ~${potential_savings:,.0f}/month (38% discount)")
            action_parts.append("**Best for:** Always-on production workloads (not dev/test)")
            
            quick_wins.append({
                "type": "reserved_capacity",
                "title": "Consider Reserved Capacity",
                "description": f"You have {len(running_instances)} running instance(s). Reserve capacity for 1-year to save 38%.",
                "potential_savings": potential_savings,
                "action": "\n".join(action_parts)
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
            "summary": {
                "total_insights": len(insights),
                "total_recommendations": len(recommendations),
                "total_quick_wins": len(quick_wins),
                "estimated_monthly_savings": total_potential_savings
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

