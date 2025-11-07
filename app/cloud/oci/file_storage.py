"""OCI File Storage operations."""

from typing import List, Dict, Optional
import oci
from oci import file_storage

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class FileStorageClient:
    """Client for OCI File Storage operations."""
    
    def __init__(self, user_id: int):
        """Initialize File Storage client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the File Storage client."""
        self.fs_client = file_storage.FileStorageClient(
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
    
    def list_file_systems(self, compartment_id: str, availability_domain: str) -> List[Dict]:
        """List all file systems in a compartment and availability domain.
        
        Args:
            compartment_id: Compartment OCID to list file systems from
            availability_domain: Availability domain name
        
        Returns:
            List of file systems with details
        """
        try:
            api_call = lambda: self.fs_client.list_file_systems(
                compartment_id=compartment_id,
                availability_domain=availability_domain
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            file_systems = []
            for fs in response.data:
                file_systems.append({
                    "id": fs.id,
                    "display_name": fs.display_name,
                    "compartment_id": fs.compartment_id,
                    "availability_domain": fs.availability_domain,
                    "metered_bytes": fs.metered_bytes,
                    "lifecycle_state": fs.lifecycle_state,
                    "time_created": str(fs.time_created) if fs.time_created else None
                })
            
            return file_systems
        except Exception as e:
            raise ValueError(f"Error listing file systems: {str(e)}")
    
    def get_file_system(self, file_system_id: str) -> Dict:
        """Get details of a specific file system.
        
        Args:
            file_system_id: File system OCID
        
        Returns:
            File system details
        """
        try:
            api_call = lambda: self.fs_client.get_file_system(file_system_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            fs = response.data
            return {
                "id": fs.id,
                "display_name": fs.display_name,
                "compartment_id": fs.compartment_id,
                "availability_domain": fs.availability_domain,
                "metered_bytes": fs.metered_bytes,
                "lifecycle_state": fs.lifecycle_state,
                "time_created": str(fs.time_created) if fs.time_created else None,
                "freeform_tags": fs.freeform_tags,
                "defined_tags": fs.defined_tags
            }
        except Exception as e:
            raise ValueError(f"Error getting file system details: {str(e)}")
