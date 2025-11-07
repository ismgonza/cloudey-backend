"""OCI PostgreSQL Database operations."""

from typing import List, Dict, Optional
import oci
from oci import psql

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class PostgresqlClient:
    """Client for OCI PostgreSQL Database operations."""
    
    def __init__(self, user_id: int):
        """Initialize PostgreSQL client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the PostgreSQL client."""
        self.psql_client = psql.PostgresqlClient(
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
    
    def list_db_systems(self, compartment_id: str) -> List[Dict]:
        """List all PostgreSQL database systems in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list PostgreSQL systems from
        
        Returns:
            List of PostgreSQL systems with details
        """
        try:
            api_call = lambda: self.psql_client.list_db_systems(
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            db_systems = []
            for db_system in response.data.items:
                # Get storage details
                storage_iops = None
                storage_size_gbs = None
                if hasattr(db_system, 'storage_details') and db_system.storage_details:
                    storage_iops = getattr(db_system.storage_details, 'iops', None)
                    if hasattr(db_system.storage_details, 'system_type'):
                        storage_size_gbs = getattr(db_system.storage_details, 'system_storage_size_in_gbs', None)
                
                db_systems.append({
                    "id": db_system.id,
                    "display_name": db_system.display_name,
                    "compartment_id": db_system.compartment_id,
                    "shape": db_system.shape,
                    "instance_count": db_system.instance_count,
                    "storage_details_iops": storage_iops,
                    "storage_details_size_in_gbs": storage_size_gbs,
                    "lifecycle_state": db_system.lifecycle_state,
                    "time_created": str(db_system.time_created) if db_system.time_created else None
                })
            
            return db_systems
        except Exception as e:
            raise ValueError(f"Error listing PostgreSQL systems: {str(e)}")
    
    def get_db_system(self, db_system_id: str) -> Dict:
        """Get details of a specific PostgreSQL database system.
        
        Args:
            db_system_id: PostgreSQL system OCID
        
        Returns:
            PostgreSQL system details
        """
        try:
            api_call = lambda: self.psql_client.get_db_system(db_system_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            db_system = response.data
            
            # Get storage details
            storage_iops = None
            storage_size_gbs = None
            if hasattr(db_system, 'storage_details') and db_system.storage_details:
                storage_iops = getattr(db_system.storage_details, 'iops', None)
                if hasattr(db_system.storage_details, 'system_type'):
                    storage_size_gbs = getattr(db_system.storage_details, 'system_storage_size_in_gbs', None)
            
            return {
                "id": db_system.id,
                "display_name": db_system.display_name,
                "compartment_id": db_system.compartment_id,
                "shape": db_system.shape,
                "instance_count": db_system.instance_count,
                "storage_details_iops": storage_iops,
                "storage_details_size_in_gbs": storage_size_gbs,
                "lifecycle_state": db_system.lifecycle_state,
                "time_created": str(db_system.time_created) if db_system.time_created else None,
                "freeform_tags": db_system.freeform_tags,
                "defined_tags": db_system.defined_tags
            }
        except Exception as e:
            raise ValueError(f"Error getting PostgreSQL system details: {str(e)}")
