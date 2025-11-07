"""OCI Compartment operations."""

from typing import List, Dict, Optional
import oci
from oci import identity

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class CompartmentClient:
    """Client for OCI compartment operations."""
    
    def __init__(self, user_id: int):
        """Initialize compartment client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the Identity client."""
        self.identity_client = identity.IdentityClient(
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
    
    def list_compartments(self, include_root: bool = True) -> List[Dict[str, str]]:
        """List all compartments in the tenancy.
        
        Args:
            include_root: Whether to include the root compartment
        
        Returns:
            List of compartments with id, name, and description
        """
        try:
            tenancy_id = self.config["tenancy"]
            
            # Get all compartments
            api_call = lambda: self.identity_client.list_compartments(
                compartment_id=tenancy_id,
                compartment_id_in_subtree=True,
                access_level="ACCESSIBLE"
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            compartments = []
            
            # Add root compartment if requested
            if include_root:
                api_call = lambda: self.identity_client.get_tenancy(tenancy_id)
                root_response = self._make_api_call_with_rate_limit(api_call)
                compartments.append({
                    "id": root_response.data.id,
                    "name": root_response.data.name,
                    "description": root_response.data.description or "Root compartment"
                })
            
            # Add all sub-compartments
            for compartment in response.data:
                if compartment.lifecycle_state == "ACTIVE":
                    compartments.append({
                        "id": compartment.id,
                        "name": compartment.name,
                        "description": compartment.description or ""
                    })
            
            return compartments
        except Exception as e:
            raise ValueError(f"Error listing compartments: {str(e)}")
    
    def resolve_compartment_id(self, compartment_identifier: str) -> str:
        """Resolve a compartment name or partial OCID to a full OCID.
        
        Args:
            compartment_identifier: Compartment name, OCID, or "root"
        
        Returns:
            Full compartment OCID
        """
        # If it's "root", return tenancy OCID
        if compartment_identifier.lower() == "root":
            return self.config["tenancy"]
        
        # If it looks like an OCID, return it
        if compartment_identifier.startswith("ocid1.compartment."):
            return compartment_identifier
        
        # Otherwise, search by name
        compartments = self.list_compartments(include_root=True)
        
        # Try exact match first
        for comp in compartments:
            if comp["name"].lower() == compartment_identifier.lower():
                return comp["id"]
        
        # Try partial match
        matches = [
            comp for comp in compartments
            if compartment_identifier.lower() in comp["name"].lower()
        ]
        
        if len(matches) == 1:
            return matches[0]["id"]
        elif len(matches) > 1:
            names = [m["name"] for m in matches]
            raise ValueError(
                f"Multiple compartments match '{compartment_identifier}': {', '.join(names)}"
            )
        else:
            raise ValueError(f"No compartment found matching '{compartment_identifier}'")
    
    def get_compartment(self, compartment_id: str) -> Dict[str, str]:
        """Get details of a specific compartment.
        
        Args:
            compartment_id: Compartment OCID
        
        Returns:
            Compartment details
        """
        try:
            # Handle root compartment
            if compartment_id == self.config["tenancy"]:
                api_call = lambda: self.identity_client.get_tenancy(compartment_id)
                response = self._make_api_call_with_rate_limit(api_call)
                return {
                    "id": response.data.id,
                    "name": response.data.name,
                    "description": response.data.description or "Root compartment",
                    "lifecycle_state": "ACTIVE"
                }
            
            # Get regular compartment
            api_call = lambda: self.identity_client.get_compartment(compartment_id)
            response = self._make_api_call_with_rate_limit(api_call)
            
            return {
                "id": response.data.id,
                "name": response.data.name,
                "description": response.data.description or "",
                "lifecycle_state": response.data.lifecycle_state
            }
        except Exception as e:
            raise ValueError(f"Error getting compartment: {str(e)}")

