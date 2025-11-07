"""Dashboard data aggregation module.

Provides summarized cost and optimization data for the dashboard view.
"""

import logging
from typing import Dict, List
from datetime import datetime, timedelta

import oci.usage_api as usage_api

from app.cloud.oci.usage_api_client import UsageApiClient
from app.cloud.oci.compartment import CompartmentClient
from app.cloud.oci.compute import ComputeClient
from app.cloud.oci.block_storage import BlockStorageClient
from app.cloud.oci.optimization import CostOptimizationAnalyzer
from app.cache import cached, CacheKeyPrefixes, get_cost_cache
from app.sysconfig import CacheConfig

logger = logging.getLogger(__name__)


@cached(prefix=CacheKeyPrefixes.PREFIX_DASHBOARD, ttl=CacheConfig.DASHBOARD_TTL)
async def get_dashboard_data(user_id: int, force_refresh: bool = False) -> Dict:
    """Get all dashboard data for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary containing all dashboard data
    """
    logger.info(f"📊 Generating dashboard data for user {user_id}")
    
    try:
        # Initialize clients
        comp_client = CompartmentClient(user_id)
        usage_client = UsageApiClient(user_id)
        compute_client = ComputeClient(user_id)
        storage_client = BlockStorageClient(user_id)
        
        tenancy_id = comp_client.config["tenancy"]
        current_region = comp_client.config.get('region', 'us-ashburn-1')
        
        # Get current month date range
        today = datetime.now()
        first_of_month = today.replace(day=1)
        
        # ============================================================================
        # 1. COST OVERVIEW DATA
        # ============================================================================
        logger.debug("Fetching cost overview data...")
        
        # Get current month costs grouped by compartment AND service
        # This ensures we get compartment breakdown
        logger.debug("Fetching costs grouped by compartment and service...")
        
        # OCI API's time_usage_ended is EXCLUSIVE, so add +1 day to include today
        # e.g., to get costs up to Nov 5, we set end to Nov 6 00:00:00
        start_datetime = datetime.combine(first_of_month.date(), datetime.min.time())
        end_datetime = datetime.combine(today.date(), datetime.min.time()) + timedelta(days=1)
        
        request_details = {
            "tenant_id": tenancy_id,
            "time_usage_started": start_datetime,
            "time_usage_ended": end_datetime,
            "granularity": "DAILY",
            "query_type": "COST",
            "group_by": ["service", "compartmentId"],
            "compartment_depth": 7
        }
        
        request = usage_api.models.RequestSummarizedUsagesDetails(**request_details)
        
        from oci import retry
        response = usage_client.usage_client.request_summarized_usages(
            request,
            retry_strategy=retry.DEFAULT_RETRY_STRATEGY
        )
        
        # Process response to build cost breakdown
        items = response.data.items
        total_cost = 0
        service_breakdown = {}
        compartment_breakdown = {}
        
        # Get compartment names map for proper labeling
        compartment_name_map = {}
        try:
            all_compartments = comp_client.list_compartments(include_root=True)
            for comp in all_compartments:
                compartment_name_map[comp['id']] = comp['name']
            compartment_name_map[tenancy_id] = 'Root (Tenancy)'
        except Exception as e:
            logger.warning(f"Could not fetch compartment names: {str(e)}")
        
        for item in items:
            cost = float(item.computed_amount) if item.computed_amount else 0.0
            total_cost += cost
            
            # Service breakdown
            service = getattr(item, 'service', 'Unknown')
            if service not in service_breakdown:
                service_breakdown[service] = 0
            service_breakdown[service] += cost
            
            # Compartment breakdown
            compartment_id = getattr(item, 'compartment_id', tenancy_id)
            # Use our name map instead of relying on item.compartment_name
            compartment_name = compartment_name_map.get(compartment_id, compartment_id[:20] + '...')
            
            if compartment_id not in compartment_breakdown:
                compartment_breakdown[compartment_id] = {
                    'compartment_id': compartment_id,
                    'compartment_name': compartment_name,
                    'cost': 0
                }
            compartment_breakdown[compartment_id]['cost'] += cost
        
        current_costs = {
            'total_cost': total_cost,
            'currency': 'USD',
            'service_breakdown': [
                {'service': svc, 'cost': cost}
                for svc, cost in service_breakdown.items()
            ],
            'compartment_breakdown': list(compartment_breakdown.values())
        }
        
        total_cost = current_costs['total_cost']
        currency = current_costs['currency']
        
        # Get top 3 compartments
        compartment_breakdown = current_costs.get('compartment_breakdown', [])
        top_compartments = sorted(compartment_breakdown, key=lambda x: x['cost'], reverse=True)[:3]
        
        # Get top 3 services
        service_breakdown = current_costs.get('service_breakdown', [])
        top_services = sorted(service_breakdown, key=lambda x: x['cost'], reverse=True)[:3]
        
        # ============================================================================
        # 2. COST TREND DATA (Smart Comparison)
        # ============================================================================
        logger.debug("Fetching cost trend data...")
        
        # Section 1: Last THREE COMPLETE months comparison
        # Calculate the three complete months before current month
        def get_previous_months(current_date, num_months):
            """Get the first and last day of the previous N months."""
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
                
                months.append({
                    'name': first_day.strftime("%B %Y"),
                    'first_day': first_day,
                    'last_day': last_day
                })
            
            return list(reversed(months))  # Return oldest to newest
        
        # Get last 3 complete months
        complete_months = get_previous_months(today, 3)
        
        # Fetch costs for each month (using hybrid cache)
        cost_cache = get_cost_cache()
        month_costs = []
        
        for month_info in complete_months:
            month_key = month_info['first_day'].strftime("%Y-%m")
            
            # Try hybrid cache first (Redis for current month, SQLite for historical)
            cached_costs = cost_cache.get_costs(month_key, user_id)
            
            if cached_costs:
                # Calculate total from cached data
                total_cost_cached = sum(record['cost'] for record in cached_costs)
                logger.debug(f"✅ Using hybrid cache for {month_info['name']}: ${total_cost_cached}")
                month_costs.append({
                    'name': month_info['name'],
                    'total': total_cost_cached
                })
            else:
                # Fetch from OCI
                logger.debug(f"🌐 Fetching costs from OCI for {month_info['name']}")
                costs = usage_client.get_cost_data(
                    tenancy_id,
                    month_info['first_day'].strftime("%Y-%m-%d"),
                    month_info['last_day'].strftime("%Y-%m-%d")
                )
                month_costs.append({
                    'name': month_info['name'],
                    'total': costs['total_cost']
                })
                
                # Note: Detailed cost endpoint will populate the hybrid cache
                # Dashboard uses aggregated totals only
        
        # Calculate average change across the 3 months
        # Compare most recent month vs average of previous 2
        if len(month_costs) >= 3:
            oldest_month = month_costs[0]['total']
            middle_month = month_costs[1]['total']
            newest_month = month_costs[2]['total']
            
            avg_previous = (oldest_month + middle_month) / 2
            if avg_previous > 0:
                complete_months_change_pct = ((newest_month - avg_previous) / avg_previous) * 100
            else:
                complete_months_change_pct = 0
        else:
            complete_months_change_pct = 0
        
        # For backward compatibility, keep prev_month references
        prev_month = complete_months[-1]['first_day'] if complete_months else today
        prev_month_end = complete_months[-1]['last_day'] if complete_months else today
        prev_month_total = month_costs[-1]['total'] if month_costs else 0
        
        # Section 2: Month-to-date comparison (current period vs same period last month)
        current_day = today.day
        
        # Current month to date
        current_mtd = total_cost  # Already have this from earlier
        
        # Same period in previous month
        same_period_last_month_end = datetime(prev_month.year, prev_month.month, min(current_day, prev_month_end.day))
        
        same_period_costs = usage_client.get_cost_data(
            tenancy_id,
            prev_month.strftime("%Y-%m-%d"),
            same_period_last_month_end.strftime("%Y-%m-%d")
        )
        same_period_total = same_period_costs['total_cost']
        
        # Calculate MTD change
        if same_period_total > 0:
            mtd_change_pct = ((current_mtd - same_period_total) / same_period_total) * 100
        else:
            mtd_change_pct = 0
        
        # Determine overall trend
        trend = 'increasing' if mtd_change_pct > 5 else 'decreasing' if mtd_change_pct < -5 else 'stable'
        
        # ============================================================================
        # 3. RESOURCE INVENTORY
        # ============================================================================
        logger.debug("Fetching resource inventory...")
        
        # Get all compartments
        all_compartments = comp_client.list_compartments(include_root=False)
        compartments_to_scan = [tenancy_id] + [c['id'] for c in all_compartments]
        
        # Count resources
        all_instances = []
        all_volumes = []
        
        for comp_id in compartments_to_scan:
            try:
                instances = compute_client.list_instances(comp_id)
                all_instances.extend(instances)
            except:
                pass
            
            try:
                volumes = storage_client.list_volumes(comp_id)
                all_volumes.extend(volumes)
            except:
                pass
        
        running_instances = sum(1 for i in all_instances if i.get('lifecycle_state') == 'RUNNING')
        stopped_instances = sum(1 for i in all_instances if i.get('lifecycle_state') in ['STOPPED', 'TERMINATED'])
        
        # ============================================================================
        # 4. OPTIMIZATION SUMMARY
        # ============================================================================
        logger.debug("Generating optimization summary...")
        
        optimizer = CostOptimizationAnalyzer(user_id)
        
        # Get recommendations
        compute_recs = optimizer.analyze_compute_utilization(all_instances, current_costs)
        storage_recs = optimizer.analyze_storage_optimization(all_volumes, current_costs)
        reserved_recs = optimizer.calculate_reserved_capacity_savings(all_instances, current_costs)
        service_recs = optimizer.analyze_service_distribution(service_breakdown)
        
        all_recs = compute_recs + storage_recs + reserved_recs + service_recs
        
        # Count by severity
        high_severity = sum(1 for r in all_recs if r['severity'] == 'HIGH')
        medium_severity = sum(1 for r in all_recs if r['severity'] == 'MEDIUM')
        low_severity = sum(1 for r in all_recs if r['severity'] == 'LOW')
        
        # Calculate potential savings
        total_potential_savings = 0
        for rec in reserved_recs:
            # Extract savings from "Potential Savings" field
            if 'potential_savings' in rec:
                savings_str = rec['potential_savings']
                # Extract the 1-year savings number
                if '$' in savings_str and '/year' in savings_str:
                    try:
                        # Format: "$2,456.78/year (1-year) or $3,367.89/year (3-year)"
                        parts = savings_str.split('$')[1].split('/')[0]
                        one_year_savings = float(parts.replace(',', ''))
                        total_potential_savings += one_year_savings
                    except:
                        pass
        
        # ============================================================================
        # 5. COST ALERTS - REMOVED (Redundant with optimization recommendations)
        # ============================================================================
        # Alerts are now shown only in the Optimization Summary card
        alerts = []
        
        # ============================================================================
        # COMPILE DASHBOARD DATA
        # ============================================================================
        
        dashboard_data = {
            'cost_overview': {
                'total_cost': round(total_cost, 2),
                'currency': currency,
                'period': {
                    'start': first_of_month.strftime("%Y-%m-%d"),
                    'end': today.strftime("%Y-%m-%d"),
                    'label': today.strftime("%B %Y")
                },
                'top_compartments': [
                    {
                        'name': comp['compartment_name'],
                        'cost': round(comp['cost'], 2)
                    }
                    for comp in top_compartments
                ],
                'top_services': [
                    {
                        'name': svc['service'],
                        'cost': round(svc['cost'], 2),
                        'percentage': round((svc['cost'] / total_cost * 100), 1) if total_cost > 0 else 0
                    }
                    for svc in top_services
                ]
            },
            'cost_trend': {
                # Complete months comparison (3 months)
                'complete_months': [
                    {
                        'name': month['name'],
                        'total': round(month['total'], 2)
                    }
                    for month in month_costs
                ],
                'complete_months_change_pct': round(complete_months_change_pct, 1),
                'complete_months_trend': 'increasing' if complete_months_change_pct > 5 else 'decreasing' if complete_months_change_pct < -5 else 'stable',
                
                # Month-to-date comparison
                'current_month_name': today.strftime("%B %Y"),
                'current_mtd': round(current_mtd, 2),
                'current_day': current_day,
                'same_period_last_month': round(same_period_total, 2),
                'mtd_change_pct': round(mtd_change_pct, 1),
                'mtd_trend': trend,
                
                # Legacy fields for backward compatibility
                'current_month': round(total_cost, 2),
                'last_month': round(prev_month_total, 2),
                'change_percentage': round(mtd_change_pct, 1),
                'trend': trend
            },
            'resource_inventory': {
                'running_instances': running_instances,
                'stopped_instances': stopped_instances,
                'total_instances': len(all_instances),
                'block_volumes': len(all_volumes),
                'compartments': len(all_compartments) + 1  # +1 for root
            },
            'optimization_summary': {
                'total_recommendations': len(all_recs),
                'high_severity': high_severity,
                'medium_severity': medium_severity,
                'low_severity': low_severity,
                'potential_annual_savings': round(total_potential_savings, 2),
                'top_recommendations': [
                    {
                        'title': rec['title'],
                        'severity': rec['severity'].lower(),
                        'savings': rec.get('potential_savings', 'Variable')
                    }
                    for rec in all_recs[:3]  # Top 3
                ]
            },
            'alerts': alerts[:5],  # Top 5 alerts
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'region': current_region,
                'user_id': user_id
            }
        }
        
        logger.info(f"✅ Dashboard data generated successfully")
        return dashboard_data
        
    except Exception as e:
        logger.error(f"Error generating dashboard data: {str(e)}", exc_info=True)
        raise

