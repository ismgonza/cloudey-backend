"""OCI Compute operations."""

from typing import List, Dict, Optional
import oci
from oci import core

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class ComputeClient:
    """Client for OCI compute operations."""
    
    def __init__(self, user_id: int):
        """Initialize compute client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the Compute client."""
        self.compute_client = core.ComputeClient(
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
    
    def list_instances(self, compartment_id: str) -> List[Dict]:
        """List all compute instances in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list instances from
        
        Returns:
            List of instances with details
        """
        try:
            api_call = lambda: self.compute_client.list_instances(
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            instances = []
            for instance in response.data:
                # Extract vCPUs and memory from shape_config
                vcpus = None
                memory_in_gbs = None
                if hasattr(instance, 'shape_config') and instance.shape_config:
                    vcpus = instance.shape_config.ocpus if hasattr(instance.shape_config, 'ocpus') else None
                    memory_in_gbs = instance.shape_config.memory_in_gbs if hasattr(instance.shape_config, 'memory_in_gbs') else None
                
                instances.append({
                    "id": instance.id,
                    "display_name": instance.display_name,
                    "shape": instance.shape,
                    "lifecycle_state": instance.lifecycle_state,
                    "availability_domain": instance.availability_domain,
                    "time_created": str(instance.time_created) if instance.time_created else None,
                    "vcpus": vcpus,
                    "memory_in_gbs": memory_in_gbs
                })
            
            return instances
        except Exception as e:
            raise ValueError(f"Error listing instances: {str(e)}")
    
    def get_instance(self, instance_id: str) -> Dict:
        """Get details of a specific compute instance.
        
        Args:
            instance_id: Instance OCID
        
        Returns:
            Instance details
        """
        try:
            api_call = lambda: self.compute_client.get_instance(instance_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            instance = response.data
            
            # Extract vCPUs and memory from shape_config
            vcpus = None
            memory_in_gbs = None
            if hasattr(instance, 'shape_config') and instance.shape_config:
                vcpus = instance.shape_config.ocpus if hasattr(instance.shape_config, 'ocpus') else None
                memory_in_gbs = instance.shape_config.memory_in_gbs if hasattr(instance.shape_config, 'memory_in_gbs') else None
            
            return {
                "id": instance.id,
                "display_name": instance.display_name,
                "shape": instance.shape,
                "lifecycle_state": instance.lifecycle_state,
                "availability_domain": instance.availability_domain,
                "time_created": str(instance.time_created) if instance.time_created else None,
                "region": instance.region if hasattr(instance, 'region') else None,
                "vcpus": vcpus,
                "memory_in_gbs": memory_in_gbs
            }
        except Exception as e:
            raise ValueError(f"Error getting instance: {str(e)}")

