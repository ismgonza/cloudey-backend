"""OCI Database operations."""

from typing import List, Dict, Optional
import oci
from oci import database

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class DatabaseClient:
    """Client for OCI Database operations."""
    
    def __init__(self, user_id: int):
        """Initialize Database client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the Database client."""
        self.db_client = database.DatabaseClient(
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
        """List all database systems in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list database systems from
        
        Returns:
            List of database systems with details
        """
        try:
            api_call = lambda: self.db_client.list_db_systems(
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            db_systems = []
            for db_system in response.data:
                db_systems.append({
                    "id": db_system.id,
                    "display_name": db_system.display_name,
                    "compartment_id": db_system.compartment_id,
                    "shape": db_system.shape,
                    "database_edition": db_system.database_edition,
                    "lifecycle_state": db_system.lifecycle_state,
                    "availability_domain": db_system.availability_domain,
                    "cpu_core_count": db_system.cpu_core_count,
                    "data_storage_size_in_gbs": db_system.data_storage_size_in_gbs,
                    "time_created": str(db_system.time_created) if db_system.time_created else None
                })
            
            return db_systems
        except Exception as e:
            raise ValueError(f"Error listing database systems: {str(e)}")
    
    def get_db_system(self, db_system_id: str) -> Dict:
        """Get details of a specific database system.
        
        Args:
            db_system_id: Database system OCID
        
        Returns:
            Database system details
        """
        try:
            api_call = lambda: self.db_client.get_db_system(db_system_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            db_system = response.data
            return {
                "id": db_system.id,
                "display_name": db_system.display_name,
                "compartment_id": db_system.compartment_id,
                "shape": db_system.shape,
                "database_edition": db_system.database_edition,
                "lifecycle_state": db_system.lifecycle_state,
                "availability_domain": db_system.availability_domain,
                "cpu_core_count": db_system.cpu_core_count,
                "data_storage_size_in_gbs": db_system.data_storage_size_in_gbs,
                "time_created": str(db_system.time_created) if db_system.time_created else None,
                "freeform_tags": db_system.freeform_tags,
                "defined_tags": db_system.defined_tags
            }
        except Exception as e:
            raise ValueError(f"Error getting database system details: {str(e)}")
