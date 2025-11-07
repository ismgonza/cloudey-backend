"""OCI Cost Optimization and Recommendations Engine.

This module analyzes OCI resources and provides cost optimization recommendations.
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class CostOptimizationAnalyzer:
    """Analyzes OCI costs and provides optimization recommendations."""
    
    def __init__(self, user_id: int):
        """Initialize the optimizer.
        
        Args:
            user_id: User ID for accessing cloud configs
        """
        self.user_id = user_id
        self.recommendations = []
    
    def calculate_reserved_capacity_savings(
        self,
        instances: List[Dict],
        cost_data: Dict
    ) -> List[Dict[str, Any]]:
        """Calculate potential savings with reserved capacity.
        
        OCI Reserved Capacity provides up to 38% discount for 1-year
        and up to 52% discount for 3-year commitments.
        
        Args:
            instances: List of compute instances
            cost_data: Current cost data
        
        Returns:
            List of recommendations for reserved capacity
        """
        recommendations = []
        
        # Find always-running instances (good candidates for reserved capacity)
        running_instances = [
            inst for inst in instances
            if inst.get('lifecycle_state') == 'RUNNING'
        ]
        
        if len(running_instances) >= 2:  # Minimum threshold for recommendation
            # Get compute costs from service breakdown
            service_breakdown = cost_data.get('service_breakdown', [])
            compute_service = next(
                (s for s in service_breakdown if 'compute' in s.get('service', '').lower()),
                None
            )
            
            if compute_service:
                monthly_compute_cost = compute_service['cost']
                
                # Calculate savings potential
                one_year_savings = monthly_compute_cost * 12 * 0.38  # 38% discount
                three_year_savings = monthly_compute_cost * 12 * 0.52  # 52% discount
                
                recommendations.append({
                    'type': 'RESERVED_CAPACITY',
                    'severity': 'MEDIUM',
                    'title': 'Reserved Capacity Savings Available',
                    'description': f'You have {len(running_instances)} running instance(s) that could benefit from reserved capacity.',
                    'potential_savings': f'${one_year_savings:.2f}/year (1-year) or ${three_year_savings:.2f}/year (3-year)',
                    'action': 'Consider purchasing reserved capacity for always-on workloads. 1-year commitment saves 38%, 3-year saves 52%.',
                    'details': f'Current monthly compute cost: ${monthly_compute_cost:.2f}',
                    'resources': [inst['display_name'] for inst in running_instances[:5]]
                })
        
        return recommendations
    
    def analyze_region_optimization(
        self,
        current_region: str,
        cost_data: Dict
    ) -> List[Dict[str, Any]]:
        """Analyze if moving to a different region could save costs.
        
        Args:
            current_region: Current OCI region
            cost_data: Current cost data
        
        Returns:
            List of recommendations for region optimization
        """
        recommendations = []
        
        # OCI region pricing is generally consistent, but data transfer varies
        # Some regions may have slightly different pricing
        
        total_cost = cost_data.get('total_cost', 0)
        
        if total_cost > 1000:  # Only recommend for significant spend
            # Check if using a premium region
            premium_regions = ['uk-london-1', 'ap-tokyo-1', 'me-jeddah-1']
            
            if current_region in premium_regions:
                recommendations.append({
                    'type': 'REGION_OPTIMIZATION',
                    'severity': 'LOW',
                    'title': 'Consider Standard Regions for Cost Savings',
                    'description': f'You are using region: {current_region}. Some regions may have lower data transfer costs.',
                    'potential_savings': 'Variable (typically 5-10% on data transfer)',
                    'action': f'If your workload does not require {current_region}, consider moving to us-ashburn-1 or us-phoenix-1 for potential savings.',
                    'details': 'OCI compute pricing is consistent across regions, but data transfer and some services vary.'
                })
        
        return recommendations
    
    def analyze_compute_utilization(
        self,
        instances: List[Dict],
        cost_data: Dict
    ) -> List[Dict[str, Any]]:
        """Analyze compute instances for optimization opportunities.
        
        Args:
            instances: List of compute instances
            cost_data: Cost data for the period
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        # Check for stopped instances with costs
        stopped_instances = [
            inst for inst in instances
            if inst.get('lifecycle_state') in ['STOPPED', 'TERMINATED']
        ]
        
        if stopped_instances:
            recommendations.append({
                'type': 'STOPPED_INSTANCES',
                'severity': 'HIGH',
                'title': 'Stopped Instances Still Incurring Costs',
                'description': f'Found {len(stopped_instances)} stopped instance(s). Boot volumes and attached block storage continue to incur charges.',
                'potential_savings': 'Moderate',
                'action': 'Review stopped instances and delete unused boot volumes and block storage.',
                'resources': [inst['display_name'] for inst in stopped_instances[:5]]
            })
        
        return recommendations
    
    def analyze_storage_optimization(
        self,
        volumes: List[Dict],
        cost_data: Dict
    ) -> List[Dict[str, Any]]:
        """Analyze storage for optimization opportunities.
        
        Args:
            volumes: List of block volumes
            cost_data: Cost data for the period
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        # Check for unattached volumes
        unattached = [
            vol for vol in volumes
            if not vol.get('is_attached', True)
        ]
        
        if unattached:
            total_gb = sum(vol.get('size_in_gbs', 0) for vol in unattached)
            # OCI block storage ~$0.0255/GB/month
            estimated_savings = total_gb * 0.0255
            
            recommendations.append({
                'type': 'UNATTACHED_VOLUMES',
                'severity': 'MEDIUM',
                'title': 'Unattached Block Volumes',
                'description': f'Found {len(unattached)} unattached volume(s) totaling {total_gb} GB.',
                'potential_savings': f'~${estimated_savings:.2f}/month',
                'action': 'Delete unused volumes or attach them to instances.',
                'resources': [vol['display_name'] for vol in unattached[:5]]
            })
        
        # Check for large volumes
        large_volumes = [
            vol for vol in volumes
            if vol.get('size_in_gbs', 0) > 1000  # Larger than 1TB
        ]
        
        if large_volumes:
            recommendations.append({
                'type': 'LARGE_VOLUMES',
                'severity': 'LOW',
                'title': 'Large Block Volumes Detected',
                'description': f'Found {len(large_volumes)} volume(s) larger than 1TB.',
                'potential_savings': 'Variable',
                'action': 'Consider using Object Storage for infrequently accessed data (up to 90% cheaper).',
                'resources': [f"{vol['display_name']} ({vol['size_in_gbs']}GB)" for vol in large_volumes[:5]]
            })
        
        return recommendations
    
    def analyze_spending_trends(
        self,
        monthly_costs: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Analyze spending trends for anomalies.
        
        Args:
            monthly_costs: List of monthly cost data
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        if len(monthly_costs) < 2:
            return recommendations
        
        # Sort by date
        sorted_costs = sorted(monthly_costs, key=lambda x: x['end_date'])
        
        # Check for significant increases (>20%)
        for i in range(1, len(sorted_costs)):
            prev_cost = sorted_costs[i-1]['total_cost']
            curr_cost = sorted_costs[i]['total_cost']
            
            if prev_cost > 0:
                increase_pct = ((curr_cost - prev_cost) / prev_cost) * 100
                
                if increase_pct > 20:
                    recommendations.append({
                        'type': 'COST_SPIKE',
                        'severity': 'HIGH',
                        'title': 'Significant Cost Increase Detected',
                        'description': f'Costs increased by {increase_pct:.1f}% from {sorted_costs[i-1]["end_date"]} to {sorted_costs[i]["end_date"]}.',
                        'potential_savings': 'Investigation needed',
                        'action': 'Review service usage and identify the cause of the spike.',
                        'details': f'Increased from ${prev_cost:.2f} to ${curr_cost:.2f}'
                    })
        
        return recommendations
    
    def analyze_service_distribution(
        self,
        service_breakdown: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Analyze service cost distribution for optimization.
        
        Args:
            service_breakdown: List of services with costs
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        if not service_breakdown:
            return recommendations
        
        total_cost = sum(s['cost'] for s in service_breakdown)
        
        # Check if any single service is >60% of costs
        for service in service_breakdown:
            if service['cost'] / total_cost > 0.6:
                recommendations.append({
                    'type': 'SERVICE_CONCENTRATION',
                    'severity': 'MEDIUM',
                    'title': f'High Concentration in {service["service"]}',
                    'description': f'{service["service"]} represents {(service["cost"]/total_cost*100):.1f}% of your total costs (${service["cost"]:.2f}).',
                    'potential_savings': 'Variable',
                    'action': f'Review {service["service"]} usage for optimization opportunities like rightsizing or reserved capacity.',
                })
        
        # Check for Object Storage optimization
        obj_storage = next((s for s in service_breakdown if 'object storage' in s['service'].lower()), None)
        if obj_storage and obj_storage['cost'] > 100:
            recommendations.append({
                'type': 'STORAGE_TIER',
                'severity': 'LOW',
                'title': 'Object Storage Tier Optimization',
                'description': f'Object Storage costs ${obj_storage["cost"]:.2f}/month.',
                'potential_savings': 'Up to 90%',
                'action': 'Move infrequently accessed data to Archive Storage (90% cheaper) or Infrequent Access tier (50% cheaper).',
            })
        
        return recommendations
    
    def generate_recommendations_report(
        self,
        instances: List[Dict] = None,
        volumes: List[Dict] = None,
        cost_data: Dict = None,
        monthly_trends: List[Dict] = None,
        current_region: str = None
    ) -> str:
        """Generate a comprehensive recommendations report.
        
        Args:
            instances: Compute instances data
            volumes: Block volumes data
            cost_data: Current cost data
            monthly_trends: Historical monthly costs
            current_region: Current OCI region
        
        Returns:
            Formatted recommendations report
        """
        all_recommendations = []
        
        # Analyze compute
        if instances and cost_data:
            all_recommendations.extend(
                self.analyze_compute_utilization(instances, cost_data)
            )
        
        # Phase 2: Reserved Capacity Analysis
        if instances and cost_data:
            all_recommendations.extend(
                self.calculate_reserved_capacity_savings(instances, cost_data)
            )
        
        # Analyze storage
        if volumes and cost_data:
            all_recommendations.extend(
                self.analyze_storage_optimization(volumes, cost_data)
            )
        
        # Analyze trends
        if monthly_trends:
            all_recommendations.extend(
                self.analyze_spending_trends(monthly_trends)
            )
        
        # Analyze service distribution
        if cost_data and cost_data.get('service_breakdown'):
            all_recommendations.extend(
                self.analyze_service_distribution(cost_data['service_breakdown'])
            )
        
        # Phase 2: Region Optimization
        if current_region and cost_data:
            all_recommendations.extend(
                self.analyze_region_optimization(current_region, cost_data)
            )
        
        # Sort by severity
        severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        all_recommendations.sort(key=lambda x: severity_order.get(x['severity'], 3))
        
        # Format report
        if not all_recommendations:
            return "✅ **No optimization opportunities found!** Your infrastructure looks well-optimized."
        
        report = f"## 💰 Cost Optimization Recommendations\n\n"
        report += f"Found {len(all_recommendations)} optimization opportunity(ies):\n\n"
        
        for i, rec in enumerate(all_recommendations, 1):
            emoji = "🔴" if rec['severity'] == "HIGH" else "🟡" if rec['severity'] == "MEDIUM" else "🔵"
            report += f"### {i}. {emoji} {rec['title']}\n\n"
            report += f"**Severity**: {rec['severity']}\n\n"
            report += f"**Description**: {rec['description']}\n\n"
            report += f"**Potential Savings**: {rec['potential_savings']}\n\n"
            report += f"**Recommended Action**: {rec['action']}\n\n"
            
            if rec.get('resources'):
                report += f"**Affected Resources**:\n"
                for resource in rec['resources']:
                    report += f"- {resource}\n"
                report += "\n"
            
            if rec.get('details'):
                report += f"**Details**: {rec['details']}\n\n"
            
            report += "---\n\n"
        
        return report

