"""Multi-cloud cost comparison module.

Compares pricing and costs across different cloud providers (OCI, AWS, Azure, etc.)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from app.cloud.oci.pricing_client import OCIPricingClient
from app.cloud.aws.pricing_client import AWSPricingClient

logger = logging.getLogger(__name__)


class MultiCloudComparator:
    """Compare costs and pricing across multiple cloud providers."""
    
    def __init__(self):
        """Initialize multi-cloud comparator."""
        self.oci_pricing = OCIPricingClient()
        self.aws_pricing = AWSPricingClient()
    
    def compare_compute_costs(
        self,
        oci_shape: str,
        aws_instance_type: str,
        hours_per_month: int = 730
    ) -> str:
        """Compare compute costs between OCI and AWS.
        
        Args:
            oci_shape: OCI compute shape (e.g., 'VM.Standard.E4.Flex')
            aws_instance_type: AWS instance type (e.g., 't3.medium')
            hours_per_month: Hours per month (default: 730)
        
        Returns:
            Formatted comparison report
        """
        try:
            report = "## 🔄 Multi-Cloud Compute Cost Comparison\n\n"
            
            # Get OCI pricing
            oci_products = self.oci_pricing.get_compute_pricing(shape=oci_shape)
            
            # Get AWS pricing (requires AWS credentials)
            aws_products = self.aws_pricing.get_ec2_pricing(region='us-east-1', instance_type=aws_instance_type)
            
            if not oci_products and not aws_products.get('products'):
                return "❌ No pricing data found for the specified configurations."
            
            # Format OCI section
            if oci_products:
                oci_product = oci_products[0]
                oci_hourly = float(oci_product.get('unit_price', 0))
                oci_monthly = oci_hourly * hours_per_month
                
                report += "### Oracle Cloud Infrastructure (OCI)\n\n"
                report += f"**Shape**: {oci_shape}\n\n"
                report += f"**Hourly Rate**: ${oci_hourly:.4f}\n\n"
                report += f"**Monthly Cost** ({hours_per_month} hours): ${oci_monthly:.2f}\n\n"
                report += "---\n\n"
            
            # Format AWS section
            if aws_products.get('error'):
                report += "### Amazon Web Services (AWS)\n\n"
                report += f"**Instance Type**: {aws_instance_type}\n\n"
                report += f"**Note**: {aws_products['error']}\n\n"
                report += "To enable AWS pricing:\n"
                report += "1. Set `AWS_ACCESS_KEY_ID` environment variable\n"
                report += "2. Set `AWS_SECRET_ACCESS_KEY` environment variable\n\n"
                report += f"Or use: [AWS Pricing Calculator](https://calculator.aws/)\n\n"
                report += "---\n\n"
            elif aws_products.get('products') and len(aws_products['products']) > 0:
                aws_product = aws_products['products'][0]
                aws_hourly = aws_product.get('price_per_hour', 0)
                aws_monthly = aws_hourly * hours_per_month if aws_hourly else 0
                
                report += "### Amazon Web Services (AWS)\n\n"
                report += f"**Instance Type**: {aws_instance_type}\n\n"
                report += f"**vCPU**: {aws_product.get('vcpu', 'N/A')}\n\n"
                report += f"**Memory**: {aws_product.get('memory', 'N/A')}\n\n"
                report += f"**Hourly Rate**: ${aws_hourly:.4f}\n\n" if aws_hourly else ""
                report += f"**Monthly Cost** ({hours_per_month} hours): ${aws_monthly:.2f}\n\n" if aws_monthly else ""
                report += "---\n\n"
            
            # Cost comparison
            if oci_products and aws_products.get('products') and aws_products['products'][0].get('price_per_hour'):
                oci_monthly = float(oci_products[0].get('unit_price', 0)) * hours_per_month
                aws_monthly = float(aws_products['products'][0]['price_per_hour']) * hours_per_month
                
                report += "### 💰 Cost Comparison\n\n"
                if oci_monthly < aws_monthly:
                    savings = aws_monthly - oci_monthly
                    savings_pct = (savings / aws_monthly) * 100
                    report += f"**OCI is ${savings:.2f}/month cheaper** ({savings_pct:.1f}% savings)\n\n"
                    report += f"**Annual Savings**: ${savings * 12:.2f}\n\n"
                else:
                    extra = oci_monthly - aws_monthly
                    report += f"**AWS is ${extra:.2f}/month cheaper**\n\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error comparing compute costs: {str(e)}")
            return f"Error comparing compute costs: {str(e)}"
    
    def compare_storage_costs(
        self,
        storage_type: str = "block",
        capacity_gb: int = 1000
    ) -> str:
        """Compare storage costs between OCI and AWS.
        
        Args:
            storage_type: Type of storage ('block', 'object')
            capacity_gb: Storage capacity in GB
        
        Returns:
            Formatted comparison report
        """
        try:
            report = "## 💾 Multi-Cloud Storage Cost Comparison\n\n"
            report += f"**Storage Type**: {storage_type.title()}\n\n"
            report += f"**Capacity**: {capacity_gb} GB\n\n"
            report += "---\n\n"
            
            # Get OCI storage pricing
            oci_storage = self.oci_pricing.get_storage_pricing(storage_type=storage_type)
            
            if oci_storage:
                oci_product = oci_storage[0]
                oci_price_per_gb = float(oci_product.get('unit_price', 0))
                oci_monthly = oci_price_per_gb * capacity_gb
                
                report += "### Oracle Cloud Infrastructure (OCI)\n\n"
                report += f"**Product**: {oci_product.get('name')}\n\n"
                report += f"**Price per GB**: ${oci_price_per_gb:.4f}/month\n\n"
                report += f"**Total Monthly Cost**: ${oci_monthly:.2f}\n\n"
                report += "---\n\n"
            
            # AWS comparison (simplified)
            report += "### Amazon Web Services (AWS)\n\n"
            
            if storage_type == "block":
                aws_price = 0.10  # EBS gp3 ~$0.08-$0.10/GB/month
                report += "**Service**: Amazon EBS (gp3)\n\n"
                report += f"**Estimated Price per GB**: ${aws_price:.4f}/month\n\n"
                report += f"**Estimated Monthly Cost**: ${aws_price * capacity_gb:.2f}\n\n"
            elif storage_type == "object":
                aws_price = 0.023  # S3 Standard ~$0.023/GB/month
                report += "**Service**: Amazon S3 (Standard)\n\n"
                report += f"**Estimated Price per GB**: ${aws_price:.4f}/month\n\n"
                report += f"**Estimated Monthly Cost**: ${aws_price * capacity_gb:.2f}\n\n"
            
            report += "\n*Note: AWS prices are estimates. Use AWS Pricing Calculator for accurate costs.*\n\n"
            
            # Savings analysis
            if oci_storage:
                oci_monthly_cost = float(oci_storage[0].get('unit_price', 0)) * capacity_gb
                aws_monthly_cost = (0.10 if storage_type == "block" else 0.023) * capacity_gb
                
                report += "---\n\n"
                report += "### 💰 Potential Savings\n\n"
                
                if oci_monthly_cost < aws_monthly_cost:
                    savings = aws_monthly_cost - oci_monthly_cost
                    savings_pct = (savings / aws_monthly_cost) * 100
                    report += f"**OCI is cheaper by**: ${savings:.2f}/month ({savings_pct:.1f}%)\n\n"
                else:
                    extra_cost = oci_monthly_cost - aws_monthly_cost
                    report += f"**AWS is cheaper by**: ${extra_cost:.2f}/month\n\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error comparing storage costs: {str(e)}")
            return f"Error comparing storage costs: {str(e)}"
    
    def recommend_best_provider(
        self,
        workload_type: str,
        monthly_budget: float
    ) -> str:
        """Recommend best cloud provider based on workload and budget.
        
        Args:
            workload_type: Type of workload ('compute', 'storage', 'database')
            monthly_budget: Monthly budget in USD
        
        Returns:
            Recommendation report
        """
        try:
            report = "## 🎯 Cloud Provider Recommendation\n\n"
            report += f"**Workload Type**: {workload_type.title()}\n\n"
            report += f"**Monthly Budget**: ${monthly_budget:.2f}\n\n"
            report += "---\n\n"
            
            recommendations = []
            
            # Add OCI recommendation
            recommendations.append({
                'provider': 'Oracle Cloud Infrastructure (OCI)',
                'pros': [
                    'Typically 30-50% cheaper than AWS for compute',
                    'Predictable pricing with no data egress fees',
                    'High performance networking included',
                    'Generous free tier'
                ],
                'cons': [
                    'Smaller service ecosystem than AWS',
                    'Fewer global regions',
                    'Less third-party integration'
                ],
                'best_for': 'Cost-sensitive workloads, enterprise applications, database-heavy workloads'
            })
            
            # Add AWS recommendation
            recommendations.append({
                'provider': 'Amazon Web Services (AWS)',
                'pros': [
                    'Largest service ecosystem',
                    'Most global regions',
                    'Extensive third-party integrations',
                    'Mature managed services'
                ],
                'cons': [
                    'Higher costs than OCI',
                    'Data egress fees can be expensive',
                    'Complex pricing model',
                    'Reserved instances required for best pricing'
                ],
                'best_for': 'Feature-rich workloads, global presence needed, extensive service requirements'
            })
            
            # Format recommendations
            for rec in recommendations:
                report += f"### {rec['provider']}\n\n"
                
                report += "**Pros**:\n"
                for pro in rec['pros']:
                    report += f"- {pro}\n"
                report += "\n"
                
                report += "**Cons**:\n"
                for con in rec['cons']:
                    report += f"- {con}\n"
                report += "\n"
                
                report += f"**Best For**: {rec['best_for']}\n\n"
                report += "---\n\n"
            
            # Add general recommendation
            report += "### 💡 General Recommendation\n\n"
            
            if workload_type.lower() in ['compute', 'database']:
                report += "**Recommendation**: Start with **OCI** for cost savings\n\n"
                report += "OCI typically offers 30-50% lower costs for compute and database workloads. "
                report += "Consider AWS if you need specific managed services not available in OCI.\n\n"
            else:
                report += "**Recommendation**: Compare specific services\n\n"
                report += "Both providers have strengths. Evaluate based on your specific requirements.\n\n"
            
            report += "**Pro Tip**: Consider a multi-cloud strategy - use OCI for cost-sensitive workloads "
            report += "and AWS for specialized services.\n\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating recommendation: {str(e)}")
            return f"Error generating recommendation: {str(e)}"

