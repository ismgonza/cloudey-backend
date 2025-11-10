"""OCI Load Balancer operations."""

from typing import List, Dict, Optional
import oci
from oci import load_balancer

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class LoadBalancerClient:
    """Client for OCI Load Balancer operations."""
    
    def __init__(self, user_id: int):
        """Initialize Load Balancer client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the Load Balancer client."""
        self.lb_client = load_balancer.LoadBalancerClient(
            self.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY
        )
    
    def _make_api_call_with_rate_limit(self, api_call):
        """Make an API call with proactive rate limiting."""
        self._rate_limiter.wait_if_needed(self.user_id)
        try:
            return api_call()
        except Exception as e:
            raise ValueError(f"OCI API call failed: {str(e)}")
    
    def list_load_balancers(self, compartment_id: str) -> List[Dict]:
        """List all load balancers in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list load balancers from
        
        Returns:
            List of load balancers with details
        """
        try:
            api_call = lambda: self.lb_client.list_load_balancers(
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            load_balancers = []
            for lb in response.data:
                # Extract IP addresses
                ip_addresses = []
                if hasattr(lb, 'ip_addresses') and lb.ip_addresses:
                    ip_addresses = [ip.ip_address for ip in lb.ip_addresses if hasattr(ip, 'ip_address')]
                
                # Extract bandwidth configuration (for flexible shapes)
                min_bandwidth_mbps = None
                max_bandwidth_mbps = None
                if hasattr(lb, 'shape_details') and lb.shape_details:
                    if hasattr(lb.shape_details, 'minimum_bandwidth_in_mbps'):
                        min_bandwidth_mbps = lb.shape_details.minimum_bandwidth_in_mbps
                    if hasattr(lb.shape_details, 'maximum_bandwidth_in_mbps'):
                        max_bandwidth_mbps = lb.shape_details.maximum_bandwidth_in_mbps
                
                load_balancers.append({
                    "id": lb.id,
                    "display_name": lb.display_name,
                    "compartment_id": lb.compartment_id,
                    "shape_name": lb.shape_name,
                    "is_private": lb.is_private,
                    "ip_addresses": ip_addresses,
                    "lifecycle_state": lb.lifecycle_state,
                    "time_created": str(lb.time_created) if lb.time_created else None,
                    "min_bandwidth_mbps": min_bandwidth_mbps,
                    "max_bandwidth_mbps": max_bandwidth_mbps
                })
            
            return load_balancers
        except Exception as e:
            raise ValueError(f"Error listing load balancers: {str(e)}")
    
    def get_load_balancer(self, load_balancer_id: str) -> Dict:
        """Get details of a specific load balancer.
        
        Args:
            load_balancer_id: Load balancer OCID
        
        Returns:
            Load balancer details
        """
        try:
            api_call = lambda: self.lb_client.get_load_balancer(load_balancer_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            lb = response.data
            
            # Extract IP addresses
            ip_addresses = []
            if hasattr(lb, 'ip_addresses') and lb.ip_addresses:
                ip_addresses = [ip.ip_address for ip in lb.ip_addresses if hasattr(ip, 'ip_address')]
            
            return {
                "id": lb.id,
                "display_name": lb.display_name,
                "compartment_id": lb.compartment_id,
                "shape_name": lb.shape_name,
                "is_private": lb.is_private,
                "ip_addresses": ip_addresses,
                "lifecycle_state": lb.lifecycle_state,
                "time_created": str(lb.time_created) if lb.time_created else None,
                "freeform_tags": lb.freeform_tags,
                "defined_tags": lb.defined_tags
            }
        except Exception as e:
            raise ValueError(f"Error getting load balancer details: {str(e)}")
