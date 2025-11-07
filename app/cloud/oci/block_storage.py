"""OCI Block Storage operations."""

from typing import List, Dict, Optional
import oci
from oci import core

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class BlockStorageClient:
    """Client for OCI block storage operations."""
    
    def __init__(self, user_id: int):
        """Initialize block storage client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the BlockStorage client."""
        self.blockstorage_client = core.BlockstorageClient(
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
    
    def list_volumes(self, compartment_id: str) -> List[Dict]:
        """List all block volumes in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list volumes from
        
        Returns:
            List of volumes with details
        """
        try:
            api_call = lambda: self.blockstorage_client.list_volumes(
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            volumes = []
            for volume in response.data:
                volumes.append({
                    "id": volume.id,
                    "display_name": volume.display_name,
                    "size_in_gbs": volume.size_in_gbs,
                    "lifecycle_state": volume.lifecycle_state,
                    "availability_domain": volume.availability_domain,
                    "time_created": str(volume.time_created) if volume.time_created else None
                })
            
            return volumes
        except Exception as e:
            raise ValueError(f"Error listing volumes: {str(e)}")
    
    def list_boot_volumes(self, availability_domain: str, compartment_id: str) -> List[Dict]:
        """List all boot volumes in a compartment and availability domain.
        
        Args:
            availability_domain: Availability domain to filter by
            compartment_id: Compartment OCID to list boot volumes from
        
        Returns:
            List of boot volumes with details
        """
        try:
            api_call = lambda: self.blockstorage_client.list_boot_volumes(
                availability_domain=availability_domain,
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            boot_volumes = []
            for bv in response.data:
                boot_volumes.append({
                    "id": bv.id,
                    "display_name": bv.display_name,
                    "size_in_gbs": bv.size_in_gbs,
                    "lifecycle_state": bv.lifecycle_state,
                    "availability_domain": bv.availability_domain,
                    "time_created": str(bv.time_created) if bv.time_created else None
                })
            
            return boot_volumes
        except Exception as e:
            raise ValueError(f"Error listing boot volumes: {str(e)}")
    
    def get_volume(self, volume_id: str) -> Dict:
        """Get details of a specific block volume.
        
        Args:
            volume_id: Volume OCID
        
        Returns:
            Volume details
        """
        try:
            api_call = lambda: self.blockstorage_client.get_volume(volume_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            volume = response.data
            return {
                "id": volume.id,
                "display_name": volume.display_name,
                "size_in_gbs": volume.size_in_gbs,
                "lifecycle_state": volume.lifecycle_state,
                "availability_domain": volume.availability_domain,
                "time_created": str(volume.time_created) if volume.time_created else None,
                "is_hydrated": volume.is_hydrated if hasattr(volume, 'is_hydrated') else None
            }
        except Exception as e:
            raise ValueError(f"Error getting volume: {str(e)}")

