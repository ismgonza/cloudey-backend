"""LangGraph tools for OCI operations.

This module defines the @tool decorated functions that the AI agent can call.
Each tool is a thin wrapper around the respective client modules.
"""

import logging
from langchain.tools import tool
from typing import List

logger = logging.getLogger(__name__)

# Import all client modules
from app.cloud.oci.compartment import CompartmentClient
from app.cloud.oci.compute import ComputeClient as OCIComputeClient
from app.cloud.oci.block_storage import BlockStorageClient
from app.cloud.oci.object_storage import ObjectStorageClient
from app.cloud.oci.file_storage import FileStorageClient
from app.cloud.oci.usage_api_client import UsageApiClient
from app.cloud.oci.optimization import CostOptimizationAnalyzer
from app.cloud.oci.pricing_client import OCIPricingClient
from app.cloud.comparison import MultiCloudComparator

# Import AI cache tool functions (NOT the @tool decorated versions)
from app.cloud.oci import ai_cache_tools


def create_oci_tools(user_id: int) -> List:
    """Create OCI tools for a specific user.
    
    Args:
        user_id: User ID to create tools for
    
    Returns:
        List of LangGraph tools
    """
    
    # ============================================================================
    # Compartment Tools
    # ============================================================================
    
    @tool
    def list_oci_compartments() -> str:
        """List all OCI compartments (including root) for the current user.
        
        Use this to discover available compartments when the user doesn't know
        the compartment name or wants to see all compartments.
        
        Returns:
            JSON string with list of compartments including name, id, and description
        """
        try:
            client = CompartmentClient(user_id)
            compartments = client.list_compartments(include_root=True)
            
            result = "Available compartments:\n\n"
            for comp in compartments:
                result += f"- **{comp['name']}**\n"
                result += f"  - ID: {comp['id']}\n"
                result += f"  - Description: {comp['description']}\n\n"
            
            return result
        except Exception as e:
            return f"Error listing compartments: {str(e)}"
    
    # ============================================================================
    # Cost/Usage Tools
    # ============================================================================
    
    @tool
    def get_oci_resource_costs(
        start_date: str,
        end_date: str,
        compartment_id: str = "root",
        service_filter: str = None
    ) -> str:
        """Get OCI costs grouped by individual resource (compute instances, volumes, etc.).
        
        This gives you per-resource costs, so you can see which specific instances,
        volumes, or buckets cost the most.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format (inclusive)
            compartment_id: Compartment name, OCID, or "root" for entire tenancy
            service_filter: Optional service name to filter (e.g., "Compute", "Block Storage")
        
        Returns:
            Cost breakdown by individual resource with resource IDs
        
        Examples:
            - get_oci_resource_costs("2024-10-01", "2024-10-31") - All resource costs
            - get_oci_resource_costs("2024-10-01", "2024-10-31", "Production", "Compute") - Compute resources only
        """
        try:
            # Create usage client once
            usage_client = UsageApiClient(user_id)
            
            # Resolve compartment identifier to OCID
            if compartment_id != "root":
                comp_client = CompartmentClient(user_id)
                resolved_id = comp_client.resolve_compartment_id(compartment_id)
            else:
                resolved_id = usage_client.config["tenancy"]
            
            # Get cost data grouped by resource
            data = usage_client.get_cost_data(
                resolved_id,
                start_date,
                end_date,
                group_by_resource=True
            )
            
            # Filter by service if requested
            resources = data['resource_breakdown']
            if service_filter:
                resources = [
                    r for r in resources
                    if service_filter.lower() in r['service'].lower()
                ]
            
            # Format response
            result = f"**Resource Costs: {start_date} to {end_date}**\n\n"
            result += f"Total Cost: ${data['total_cost']:.2f} {data['currency']}\n\n"
            
            if resources:
                result += "**Top Resources by Cost:**\n\n"
                # Show top 20 to avoid overwhelming output
                for i, resource in enumerate(resources[:20], 1):
                    # Show resource name if it looks like a name, otherwise show service type
                    resource_name = resource['resource_id']
                    # If it's an OCID, just show the service type
                    if resource_name.startswith('ocid1.'):
                        result += f"{i}. **{resource['service']}** resource\n"
                    else:
                        result += f"{i}. **{resource['service']}**: {resource_name}\n"
                    result += f"   - Cost: ${resource['cost']:.2f}\n\n"
                
                if len(resources) > 20:
                    remaining_cost = sum(r['cost'] for r in resources[20:])
                    result += f"...and {len(resources) - 20} more resources (${remaining_cost:.2f})\n"
            else:
                result += "No resource cost data available for this period.\n"
            
            return result
        except Exception as e:
            return f"Error getting resource costs: {str(e)}"
    
    @tool
    def get_oci_cost_summary(
        start_date: str,
        end_date: str,
        compartment_id: str = "root"
    ) -> str:
        """Get OCI cost summary for a date range and compartment.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format (inclusive)
            compartment_id: Compartment name, OCID, or "root" for entire tenancy.
                          If not specified, defaults to "root" (all compartments).
                          You can also pass a compartment name like "Production" or "Development"
        
        Returns:
            Cost summary with total and breakdown by service
        
        Examples:
            - get_oci_cost_summary("2024-10-01", "2024-10-31") - Gets costs for all compartments
            - get_oci_cost_summary("2024-10-01", "2024-10-31", "Production") - Gets costs for Production compartment
            - get_oci_cost_summary("2024-10-01", "2024-10-31", "ocid1.compartment....") - Gets costs by OCID
        """
        try:
            # Create usage client once
            usage_client = UsageApiClient(user_id)
            
            # Resolve compartment identifier to OCID
            if compartment_id != "root":
                comp_client = CompartmentClient(user_id)
                resolved_id = comp_client.resolve_compartment_id(compartment_id)
            else:
                resolved_id = usage_client.config["tenancy"]
            
            # Get cost data
            data = usage_client.get_cost_data(resolved_id, start_date, end_date)
            
            # Format response
            result = f"**Cost Summary: {start_date} to {end_date}**\n\n"
            result += f"Total Cost: ${data['total_cost']:.2f} {data['currency']}\n\n"
            
            if data['service_breakdown']:
                result += "**Breakdown by Service:**\n\n"
                for service in data['service_breakdown']:
                    result += f"- {service['service']}: ${service['cost']:.2f}\n"
            else:
                result += "No cost data available for this period.\n"
            
            return result
        except Exception as e:
            return f"Error getting cost summary: {str(e)}"
    
    # ============================================================================
    # Compute Tools
    # ============================================================================
    
    @tool
    def list_oci_compute_instances(compartment_identifier: str = "root") -> str:
        """List all compute instances in a compartment.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root". Defaults to "root".
        
        Returns:
            List of compute instances with details
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # List instances
            compute_client = OCIComputeClient(user_id)
            instances = compute_client.list_instances(compartment_id)
            
            if not instances:
                return f"No compute instances found in compartment '{compartment_identifier}'"
            
            result = f"**Compute Instances in {compartment_identifier}:**\n\n"
            for inst in instances:
                result += f"- **{inst['display_name']}** ({inst['shape']})\n"
                result += f"  - State: {inst['lifecycle_state']}\n"
                result += f"  - Availability Domain: {inst['availability_domain']}\n\n"
            
            return result
        except Exception as e:
            return f"Error listing compute instances: {str(e)}"
    
    # ============================================================================
    # Block Storage Tools
    # ============================================================================
    
    @tool
    def list_oci_block_volumes(compartment_identifier: str = "root") -> str:
        """List all block volumes in a compartment.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root". Defaults to "root".
        
        Returns:
            List of block volumes with details
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # List volumes
            storage_client = BlockStorageClient(user_id)
            volumes = storage_client.list_volumes(compartment_id)
            
            if not volumes:
                return f"No block volumes found in compartment '{compartment_identifier}'"
            
            result = f"**Block Volumes in {compartment_identifier}:**\n\n"
            for vol in volumes:
                result += f"- **{vol['display_name']}** ({vol['size_in_gbs']} GB)\n"
                result += f"  - State: {vol['lifecycle_state']}\n"
                result += f"  - Availability Domain: {vol['availability_domain']}\n\n"
            
            return result
        except Exception as e:
            return f"Error listing block volumes: {str(e)}"
    
    # ============================================================================
    # Object Storage Tools
    # ============================================================================
    
    @tool
    def list_oci_object_storage_buckets(compartment_identifier: str = "root") -> str:
        """List all object storage buckets in a compartment.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root". Defaults to "root".
        
        Returns:
            List of buckets with details
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # List buckets
            obj_storage_client = ObjectStorageClient(user_id)
            buckets = obj_storage_client.list_buckets(compartment_id)
            
            if not buckets:
                return f"No object storage buckets found in compartment '{compartment_identifier}'"
            
            result = f"**Object Storage Buckets in {compartment_identifier}:**\n\n"
            for bucket in buckets:
                result += f"- **{bucket['name']}**\n"
                result += f"  - Namespace: {bucket['namespace']}\n"
                result += f"  - Created: {bucket['time_created']}\n\n"
            
            return result
        except Exception as e:
            return f"Error listing object storage buckets: {str(e)}"
    
    @tool
    def get_oci_bucket_details(bucket_name: str) -> str:
        """Get detailed information about a specific object storage bucket.
        
        Args:
            bucket_name: Name of the bucket
        
        Returns:
            Detailed bucket information including size and object count
        """
        try:
            obj_storage_client = ObjectStorageClient(user_id)
            bucket = obj_storage_client.get_bucket(bucket_name)
            
            result = f"**Bucket: {bucket['name']}**\n\n"
            result += f"- Namespace: {bucket['namespace']}\n"
            result += f"- Storage Tier: {bucket.get('storage_tier', 'N/A')}\n"
            result += f"- Public Access: {bucket.get('public_access_type', 'N/A')}\n"
            
            if bucket.get('approximate_count') is not None:
                result += f"- Approximate Object Count: {bucket['approximate_count']}\n"
            if bucket.get('approximate_size') is not None:
                result += f"- Approximate Size: {bucket['approximate_size']} bytes\n"
            
            result += f"- Created: {bucket['time_created']}\n"
            
            return result
        except Exception as e:
            return f"Error getting bucket details: {str(e)}"
    
    # ============================================================================
    # File Storage Tools
    # ============================================================================
    
    @tool
    def list_oci_file_systems(
        compartment_identifier: str,
        availability_domain: str
    ) -> str:
        """List all file systems in a compartment and availability domain.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root"
            availability_domain: Availability domain (e.g., "AD-1", "AD-2", "AD-3")
        
        Returns:
            List of file systems with details
        
        Note: File systems are AD-specific, so you must provide an availability domain.
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # List file systems
            file_storage_client = FileStorageClient(user_id)
            file_systems = file_storage_client.list_file_systems(compartment_id, availability_domain)
            
            if not file_systems:
                return f"No file systems found in compartment '{compartment_identifier}' and AD '{availability_domain}'"
            
            result = f"**File Systems in {compartment_identifier} ({availability_domain}):**\n\n"
            for fs in file_systems:
                result += f"- **{fs['display_name']}**\n"
                result += f"  - State: {fs['lifecycle_state']}\n"
                if fs.get('metered_bytes'):
                    size_gb = fs['metered_bytes'] / (1024**3)
                    result += f"  - Size: {size_gb:.2f} GB\n\n"
            
            return result
        except Exception as e:
            return f"Error listing file systems: {str(e)}"
    
    # ============================================================================
    # Cost Optimization Tools
    # ============================================================================
    
    @tool
    def get_cost_optimization_recommendations(
        compartment_identifier: str = "root",
        include_compute: bool = True,
        include_storage: bool = True
    ) -> str:
        """Get cost optimization recommendations for your OCI infrastructure.
        
        Analyzes your resources and spending patterns to identify opportunities for cost savings.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root" for entire tenancy
            include_compute: Include compute instance analysis (default: True)
            include_storage: Include storage analysis (default: True)
        
        Returns:
            Detailed cost optimization recommendations with potential savings
        
        Examples:
            - get_cost_optimization_recommendations() - Full analysis for entire tenancy
            - get_cost_optimization_recommendations("Production") - Analysis for Production compartment
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            if compartment_identifier == "root":
                compartment_id = comp_client.config["tenancy"]
            else:
                compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # Initialize optimizer
            optimizer = CostOptimizationAnalyzer(user_id)
            
            # Gather data
            instances = []
            volumes = []
            cost_data = None
            monthly_trends = None
            errors = []
            
            # If root, scan all compartments for instances/volumes
            compartments_to_scan = [compartment_id]
            if compartment_identifier == "root":
                try:
                    comp_client = CompartmentClient(user_id)
                    all_compartments = comp_client.list_compartments(include_root=False)
                    compartments_to_scan.extend([c['id'] for c in all_compartments])
                except Exception as e:
                    errors.append(f"Could not list compartments: {str(e)}")
            
            # Fetch instances from all relevant compartments
            if include_compute:
                for comp_id in compartments_to_scan:
                    try:
                        compute_client = OCIComputeClient(user_id)
                        comp_instances = compute_client.list_instances(comp_id)
                        instances.extend(comp_instances)
                    except Exception as e:
                        errors.append(f"Could not fetch compute instances from {comp_id}: {str(e)}")
            
            # Fetch volumes from all relevant compartments
            if include_storage:
                for comp_id in compartments_to_scan:
                    try:
                        storage_client = BlockStorageClient(user_id)
                        comp_volumes = storage_client.list_volumes(comp_id)
                        volumes.extend(comp_volumes)
                    except Exception as e:
                        errors.append(f"Could not fetch block volumes from {comp_id}: {str(e)}")
            
            # Get current month costs
            try:
                from datetime import datetime, timedelta
                usage_client = UsageApiClient(user_id)
                today = datetime.now()
                first_of_month = today.replace(day=1)
                
                cost_data = usage_client.get_cost_data(
                    compartment_id,
                    first_of_month.strftime("%Y-%m-%d"),
                    today.strftime("%Y-%m-%d")
                )
            except Exception as e:
                logger.warning(f"Could not fetch cost data: {str(e)}")
            
            # Get historical trends (last 3 months)
            try:
                usage_client = UsageApiClient(user_id)
                monthly_trends = []
                
                for i in range(3, 0, -1):
                    month_date = today - timedelta(days=30*i)
                    first_day = month_date.replace(day=1)
                    
                    # Last day of month
                    if first_day.month == 12:
                        last_day = first_day.replace(day=31)
                    else:
                        next_month = first_day.replace(month=first_day.month + 1)
                        last_day = next_month - timedelta(days=1)
                    
                    month_cost = usage_client.get_cost_data(
                        compartment_id,
                        first_day.strftime("%Y-%m-%d"),
                        last_day.strftime("%Y-%m-%d")
                    )
                    monthly_trends.append(month_cost)
            except Exception as e:
                logger.warning(f"Could not fetch historical trends: {str(e)}")
            
            # Get current region
            current_region = None
            try:
                comp_client = CompartmentClient(user_id)
                current_region = comp_client.config.get('region')
            except:
                pass
            
            # Generate recommendations
            report = optimizer.generate_recommendations_report(
                instances=instances if instances else None,
                volumes=volumes if volumes else None,
                cost_data=cost_data,
                monthly_trends=monthly_trends,
                current_region=current_region
            )
            
            # Add debug info if there were errors or empty data
            debug_info = ""
            if errors:
                debug_info += "\n\n## ⚠️ Data Collection Issues\n\n"
                for error in errors:
                    debug_info += f"- {error}\n"
            
            if not instances and include_compute:
                debug_info += "\n⚠️ No compute instances found in the specified compartment(s).\n"
            
            if not volumes and include_storage:
                debug_info += "\n⚠️ No block volumes found in the specified compartment(s).\n"
            
            if debug_info:
                report += debug_info
            
            # Add summary of what was analyzed
            report += f"\n\n## 📊 Analysis Summary\n\n"
            report += f"- Compartments scanned: {len(compartments_to_scan)}\n"
            report += f"- Compute instances found: {len(instances) if instances else 0}\n"
            report += f"- Block volumes found: {len(volumes) if volumes else 0}\n"
            if cost_data:
                report += f"- Total monthly cost: ${cost_data.get('total_cost', 0):.2f}\n"
            
            return report
            
        except Exception as e:
            return f"Error generating optimization recommendations: {str(e)}"
    
    # ============================================================================
    # Resource Cost Analysis Tools
    # ============================================================================
    
    @tool
    def analyze_stopped_instances_cost(compartment_identifier: str = "root") -> str:
        """Analyze costs from stopped compute instances and their attached storage.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root" for entire tenancy
        
        Returns:
            Detailed cost analysis of stopped instances
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            if compartment_identifier == "root":
                compartment_id = comp_client.config["tenancy"]
            else:
                compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # Get all compartments to scan
            compartments_to_scan = [compartment_id]
            if compartment_identifier == "root":
                all_compartments = comp_client.list_compartments(include_root=False)
                compartments_to_scan.extend([c['id'] for c in all_compartments])
            
            # Fetch all instances
            all_instances = []
            for comp_id in compartments_to_scan:
                compute_client = OCIComputeClient(user_id)
                comp_instances = compute_client.list_instances(comp_id)
                all_instances.extend(comp_instances)
            
            # Filter stopped instances
            stopped = [inst for inst in all_instances if inst.get('lifecycle_state') in ['STOPPED', 'TERMINATED']]
            
            if not stopped:
                return "✅ No stopped instances found! All compute instances are running or properly terminated."
            
            # Estimate costs
            # Boot volumes: ~$0.0255/GB/month (same as block storage)
            # Assume 50GB boot volume per instance
            boot_volume_cost_per_instance = 50 * 0.0255
            total_estimated_cost = len(stopped) * boot_volume_cost_per_instance
            
            report = f"## 💸 Stopped Instance Cost Analysis\n\n"
            report += f"Found **{len(stopped)} stopped instance(s)** still incurring costs.\n\n"
            report += f"**Estimated Monthly Cost**: ~${total_estimated_cost:.2f}\n\n"
            report += f"*(Based on boot volumes only. Attached block storage costs extra.)*\n\n"
            report += "---\n\n"
            report += "### Stopped Instances:\n\n"
            
            for i, inst in enumerate(stopped, 1):
                report += f"{i}. **{inst['display_name']}**\n"
                report += f"   - Shape: {inst['shape']}\n"
                report += f"   - State: {inst['lifecycle_state']}\n"
                report += f"   - Availability Domain: {inst['availability_domain']}\n"
                report += f"   - Estimated boot volume cost: ~${boot_volume_cost_per_instance:.2f}/month\n\n"
            
            report += "### 💡 Recommendation\n\n"
            report += "Delete stopped instances you no longer need. When you stop an instance:\n"
            report += "- ✅ Compute charges stop\n"
            report += "- ❌ Boot volume charges continue\n"
            report += "- ❌ Attached block storage charges continue\n\n"
            report += f"**Potential Savings**: Up to ${total_estimated_cost:.2f}/month by deleting unused instances.\n"
            
            return report
            
        except Exception as e:
            return f"Error analyzing stopped instances: {str(e)}"
    
    @tool
    def analyze_unattached_volumes_cost(compartment_identifier: str = "root") -> str:
        """Analyze costs from unattached block volumes.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root" for entire tenancy
        
        Returns:
            Detailed cost analysis of unattached volumes
        """
        try:
            # Resolve compartment
            comp_client = CompartmentClient(user_id)
            if compartment_identifier == "root":
                compartment_id = comp_client.config["tenancy"]
            else:
                compartment_id = comp_client.resolve_compartment_id(compartment_identifier)
            
            # Get all compartments to scan
            compartments_to_scan = [compartment_id]
            if compartment_identifier == "root":
                all_compartments = comp_client.list_compartments(include_root=False)
                compartments_to_scan.extend([c['id'] for c in all_compartments])
            
            # Fetch all volumes
            all_volumes = []
            for comp_id in compartments_to_scan:
                storage_client = BlockStorageClient(user_id)
                comp_volumes = storage_client.list_volumes(comp_id)
                all_volumes.extend(comp_volumes)
            
            # Filter unattached volumes
            unattached = [vol for vol in all_volumes if not vol.get('is_attached', True)]
            
            if not unattached:
                return "✅ No unattached volumes found! All block volumes are properly attached or cleaned up."
            
            # Calculate costs
            # OCI block storage: $0.0255/GB/month
            total_gb = sum(vol.get('size_in_gbs', 0) for vol in unattached)
            total_cost = total_gb * 0.0255
            
            report = f"## 💸 Unattached Volume Cost Analysis\n\n"
            report += f"Found **{len(unattached)} unattached volume(s)** incurring costs.\n\n"
            report += f"**Total Capacity**: {total_gb} GB\n\n"
            report += f"**Monthly Cost**: ~${total_cost:.2f}\n\n"
            report += "---\n\n"
            report += "### Unattached Volumes:\n\n"
            
            for i, vol in enumerate(unattached, 1):
                vol_cost = vol.get('size_in_gbs', 0) * 0.0255
                report += f"{i}. **{vol['display_name']}**\n"
                report += f"   - Size: {vol['size_in_gbs']} GB\n"
                report += f"   - State: {vol['lifecycle_state']}\n"
                report += f"   - Availability Domain: {vol['availability_domain']}\n"
                report += f"   - Monthly Cost: ~${vol_cost:.2f}\n\n"
            
            report += "### 💡 Recommendation\n\n"
            report += "Delete unattached volumes you no longer need.\n\n"
            report += f"**Potential Savings**: ${total_cost:.2f}/month by deleting unused volumes.\n"
            
            return report
            
        except Exception as e:
            return f"Error analyzing unattached volumes: {str(e)}"
    
    # ============================================================================
    # Pricing & Comparison Tools
    # ============================================================================
    
    @tool
    def get_oci_pricing_info(
        service_type: str = "compute",
        shape_or_type: str = None
    ) -> str:
        """Get OCI pricing information from the official price list.
        
        Args:
            service_type: Type of service ('compute', 'storage')
            shape_or_type: Optional shape/type filter
        
        Returns:
            Pricing information from OCI Cost Estimator API
        """
        try:
            pricing_client = OCIPricingClient()
            
            report = f"## 💰 OCI Pricing Information\n\n"
            report += f"**Service Type**: {service_type.title()}\n\n"
            
            if service_type.lower() == "compute":
                products = pricing_client.get_compute_pricing(shape=shape_or_type)
                
                if products:
                    report += "### Compute Instance Pricing\n\n"
                    for i, product in enumerate(products[:10], 1):
                        report += f"{i}. **{product['name']}**\n"
                        report += f"   - Price: ${product['unit_price']}/hour\n"
                        report += f"   - Billing: {product['billing_model']}\n\n"
                else:
                    report += "No pricing data available.\n\n"
            
            elif service_type.lower() == "storage":
                products = pricing_client.get_storage_pricing(storage_type=shape_or_type)
                
                if products:
                    report += "### Storage Pricing\n\n"
                    for i, product in enumerate(products[:10], 1):
                        report += f"{i}. **{product['name']}**\n"
                        report += f"   - Type: {product['type']}\n"
                        report += f"   - Price: ${product['unit_price']}/GB/month\n\n"
                else:
                    report += "No pricing data available.\n\n"
            
            return report
            
        except Exception as e:
            return f"Error fetching OCI pricing: {str(e)}"
    
    @tool
    def compare_cloud_providers(
        comparison_type: str = "compute",
        oci_config: str = None,
        aws_config: str = None
    ) -> str:
        """Compare costs between OCI and AWS for similar services.
        
        Args:
            comparison_type: Type of comparison ('compute', 'storage', 'recommendation')
            oci_config: OCI configuration (e.g., 'VM.Standard.E4.Flex')
            aws_config: AWS configuration (e.g., 't3.medium')
        
        Returns:
            Multi-cloud cost comparison report
        """
        try:
            comparator = MultiCloudComparator()
            
            if comparison_type.lower() == "compute":
                if not oci_config or not aws_config:
                    return "Please specify both oci_config (shape) and aws_config (instance type) for compute comparison."
                
                return comparator.compare_compute_costs(
                    oci_shape=oci_config,
                    aws_instance_type=aws_config
                )
            
            elif comparison_type.lower() == "storage":
                storage_type = oci_config if oci_config else "block"
                capacity = int(aws_config) if aws_config and aws_config.isdigit() else 1000
                
                return comparator.compare_storage_costs(
                    storage_type=storage_type,
                    capacity_gb=capacity
                )
            
            elif comparison_type.lower() == "recommendation":
                workload = oci_config if oci_config else "compute"
                budget = float(aws_config) if aws_config else 1000.0
                
                return comparator.recommend_best_provider(
                    workload_type=workload,
                    monthly_budget=budget
                )
            
            else:
                return f"Unknown comparison type: {comparison_type}. Use 'compute', 'storage', or 'recommendation'."
            
        except Exception as e:
            return f"Error comparing cloud providers: {str(e)}"
    
    # ============================================================================
    # AI Cache Tools (Query cached data instead of OCI APIs - MUCH FASTER!)
    # ============================================================================
    
    @tool
    def query_cached_costs_tool(month: str, service: str = None, compartment_name: str = None, limit: int = 100) -> str:
        """🚀 INSTANT! Query cached cost data for a specific month. NO OCI API calls!
        
        USE THIS FOR: "costs in October", "costs in amc_prod compartment", "compute costs"
        
        Returns: Per-resource cost breakdown with OCIDs, services, and amounts.
        This gives you INDIVIDUAL resource costs, not just totals.
        Can filter by compartment NAME (e.g., "amc_prod", "Production").
        
        Args:
            month: Month in YYYY-MM format (e.g., "2025-10" for October 2025)
            service: Optional filter - "COMPUTE", "OBJECT_STORAGE", "BLOCK_STORAGE", etc.
            compartment_name: Optional compartment name (e.g., "amc_prod", "amc_pat")
            limit: Max results (default: 100, set higher if user wants "all")
        
        Example: query_cached_costs_tool("2025-10", "COMPUTE", "amc_prod", 50)
        Available months: 2025-08, 2025-09, 2025-10, 2025-11
        """
        return ai_cache_tools.query_cached_costs.invoke({
            "user_id": user_id,
            "month": month,
            "service": service,
            "compartment_name": compartment_name,
            "limit": limit
        })
    
    @tool
    def query_resource_inventory_tool(
        resource_type: str = None,
        lifecycle_state: str = None,
        compartment_name: str = None
    ) -> str:
        """Query OCI resource inventory from local database. Fast lookup without OCI API calls.
        
        Args:
            resource_type: Type of resource ("instance", "volume", "bucket", or None for all)
            lifecycle_state: Filter by state (e.g., "RUNNING", "STOPPED", "AVAILABLE")
            compartment_name: Filter by compartment name
        
        Example: query_resource_inventory_tool("instance", "STOPPED")
        """
        return ai_cache_tools.query_resource_inventory.invoke({
            "user_id": user_id,
            "resource_type": resource_type,
            "lifecycle_state": lifecycle_state,
            "compartment_name": compartment_name
        })
    
    @tool
    def analyze_cost_trends_tool(months: str, group_by: str = "service") -> str:
        """Analyze cost trends across multiple months using cached data.
        Provides insights on cost changes, trends, and patterns.
        
        Args:
            months: Comma-separated months (e.g., "2025-08,2025-09,2025-10")
            group_by: How to group costs ("service", "compartment", or "resource")
        
        Example: analyze_cost_trends_tool("2025-08,2025-09,2025-10", "service")
        """
        return ai_cache_tools.analyze_cost_trends.invoke({
            "user_id": user_id,
            "months": months,
            "group_by": group_by
        })
    
    @tool
    def get_top_cost_drivers_tool(month: str, top_n: int = 10, min_cost: float = 0.0) -> str:
        """💰 INSTANT! Get top most expensive resources. NO OCI API calls!
        
        USE THIS FOR: "most expensive instances", "top cost drivers", "cost per instance",
        "what's costing the most", "show me expensive resources"
        
        Returns: Ranked list of resources by cost with service, OCID, and percentage of total.
        Perfect for finding which specific instances/volumes/buckets cost the most.
        
        Args:
            month: Month in YYYY-MM format (e.g., "2025-10" for October 2025)
            top_n: How many top resources to show (default: 10, can go higher)
            min_cost: Only show resources above this $ amount (default: 0.0)
        
        Example: get_top_cost_drivers_tool("2025-10", 20, 100.0)
        Available months: 2025-08, 2025-09, 2025-10, 2025-11
        """
        return ai_cache_tools.get_top_cost_drivers.invoke({
            "user_id": user_id,
            "month": month,
            "top_n": top_n,
            "min_cost": min_cost
        })
    
    # Return all tools
    return [
        # AI Cache Tools (NEW - PRIORITIZE THESE!)
        query_cached_costs_tool,
        query_resource_inventory_tool,
        analyze_cost_trends_tool,
        get_top_cost_drivers_tool,
        # Compartment tools
        list_oci_compartments,
        # Cost tools
        get_oci_cost_summary,
        get_oci_resource_costs,
        # Optimization tools
        get_cost_optimization_recommendations,
        analyze_stopped_instances_cost,
        analyze_unattached_volumes_cost,
        # Pricing & Comparison tools
        get_oci_pricing_info,
        compare_cloud_providers,
        # Compute tools
        list_oci_compute_instances,
        # Block storage tools
        list_oci_block_volumes,
        # Object storage tools
        list_oci_object_storage_buckets,
        get_oci_bucket_details,
        # File storage tools
        list_oci_file_systems,
    ]
