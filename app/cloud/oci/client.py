"""OCI SDK wrapper and business logic."""

import tempfile
import os
from datetime import datetime, timedelta
import oci
from oci import usage_api, identity
from oci import retry
from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class OCIClient:
    """Wrapper for OCI SDK operations."""
    
    def __init__(self, user_id: int):
        """Initialize OCI client with user's configuration."""
        config_dict = get_oci_config_dict(user_id)
        if not config_dict:
            raise ValueError(f"No OCI configuration found for user_id: {user_id}")
        
        self.config = config_dict
        self.user_id = user_id
        self._temp_key_file = None
        self._rate_limiter = get_rate_limiter()
        self._init_clients()
    
    def _init_clients(self):
        """Initialize OCI SDK service clients.
        
        Reference: https://docs.oracle.com/en-us/iaas/tools/python/2.162.0/api/apm_config/client/oci.apm_config.ConfigClient.html
        
        The OCI SDK requires a file path for the private key (key_file), not the key content directly.
        Since we store the key as a string in the database, we create a temporary file with secure permissions.
        This temp file is cleaned up when the OCIClient object is destroyed.
        
        Security considerations:
        - File is created with mode 0o600 (read/write for owner only)
        - File is stored in system temp directory (secure by default)
        - File is automatically cleaned up on object destruction
        """
        try:
            # Create a temporary file with secure permissions (0o600 = owner read/write only)
            # Using mkstemp for better control over permissions
            fd, temp_path = tempfile.mkstemp(suffix='.pem', text=True)
            try:
                # Write the private key content
                with os.fdopen(fd, 'w') as f:
                    f.write(self.config["key_content"])
                
                # Set restrictive permissions: read/write for owner only (0o600)
                os.chmod(temp_path, 0o600)
                
                # Store the path for cleanup
                self._temp_key_file = temp_path
                
                # Create config dict for OCI SDK
                # Reference: SDK accepts a dict with keys: tenancy, user, fingerprint, key_file, region
                oci_config = {
                    "tenancy": self.config["tenancy"],
                    "user": self.config["user"],
                    "fingerprint": self.config["fingerprint"],
                    "key_file": temp_path,
                    "region": self.config["region"],
                }
                
                # Validate config before using it (per OCI SDK best practices)
                oci.config.validate_config(oci_config)
                
                # Initialize clients with validated config and SDK's default retry strategy
                # The SDK's DEFAULT_RETRY_STRATEGY automatically handles:
                # - HTTP 429 (rate limits) with exponential backoff and de-correlated jitter
                # - HTTP 5xx errors, timeouts, connection errors
                # - 8 total attempts with max 30s wait between calls
                # Reference: https://docs.oracle.com/en-us/iaas/tools/python/latest/sdk_behaviors/retries.html
                self.usage_client = usage_api.UsageapiClient(oci_config, retry_strategy=retry.DEFAULT_RETRY_STRATEGY)
                self.identity_client = identity.IdentityClient(oci_config, retry_strategy=retry.DEFAULT_RETRY_STRATEGY)
            except Exception:
                # Clean up temp file if something goes wrong before completion
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                raise
        except Exception as e:
            # Clean up temp file on error
            if hasattr(self, '_temp_key_file') and self._temp_key_file and os.path.exists(self._temp_key_file):
                try:
                    os.unlink(self._temp_key_file)
                except:
                    pass
            raise ValueError(f"Failed to initialize OCI client: {str(e)}")
    
    def __del__(self):
        """Clean up temporary key file when object is destroyed."""
        if hasattr(self, '_temp_key_file') and self._temp_key_file and os.path.exists(self._temp_key_file):
            try:
                # Overwrite file with zeros before deletion (optional security measure)
                # Note: This may not work on all filesystems, but adds extra security
                try:
                    with open(self._temp_key_file, 'r+b') as f:
                        f.seek(0)
                        f.write(b'\x00' * os.path.getsize(self._temp_key_file))
                except:
                    pass
                os.unlink(self._temp_key_file)
            except:
                pass
    
    def _make_api_call_with_rate_limit(self, api_call):
        """Make an API call with proactive rate limiting.
        
        The OCI SDK handles retries automatically via DEFAULT_RETRY_STRATEGY:
        - HTTP 429 errors are automatically retried with exponential backoff and de-correlated jitter
        - Up to 8 attempts with max 30s wait between calls
        - Total allowed elapsed time of 600 seconds
        
        Our rate limiter prevents hitting limits proactively, while SDK handles reactive retries.
        
        Args:
            api_call: Callable that makes the API call
        
        Returns:
            API response
        
        Raises:
            ValueError: If API call fails after all SDK retries
        """
        # Wait if needed to respect rate limits proactively (prevents hitting 429)
        # This also records the request
        self._rate_limiter.wait_if_needed(self.user_id)
        
        # Make the API call - SDK will handle retries automatically if needed
        try:
            return api_call()
        except Exception as e:
            # SDK has already retried, so if we get here, all retries failed
            raise ValueError(f"OCI API call failed: {str(e)}")
    
    def list_compartments(self, name_filter: str = None):
        """List all compartments accessible to the user.
        
        Reference: https://docs.oracle.com/en-us/iaas/tools/python/2.162.0/api/identity/client/oci.identity.IdentityClient.html
        
        Args:
            name_filter: Optional filter to search for compartments by name (case-insensitive)
        
        Returns:
            List of dictionaries with compartment info (id, name, description, lifecycle_state)
        """
        try:
            # Make API call with proactive rate limiting
            # SDK handles retries automatically via DEFAULT_RETRY_STRATEGY
            def api_call():
                return self.identity_client.list_compartments(
                    compartment_id=self.config["tenancy"],
                    access_level="ACCESSIBLE",
                    compartment_id_in_subtree=True
                )
            
            response = self._make_api_call_with_rate_limit(api_call)
            
            compartments = []
            for comp in response.data:
                # Filter by name if specified
                if name_filter:
                    if name_filter.lower() not in comp.name.lower():
                        continue
                
                compartments.append({
                    "id": comp.id,
                    "name": comp.name,
                    "description": comp.description,
                    "lifecycle_state": comp.lifecycle_state,
                })
            
            return compartments
        except Exception as e:
            raise ValueError(f"Error listing compartments: {str(e)}")
    
    def resolve_compartment_id(self, compartment_identifier: str) -> str:
        """Resolve compartment identifier to OCID.
        
        Args:
            compartment_identifier: Compartment OCID, name, or "root"
        
        Returns:
            Compartment OCID string
        """
        # Handle "root" or empty
        if not compartment_identifier or compartment_identifier.lower() == "root":
            return self.config["tenancy"]
        
        # If it's already an OCID (starts with "ocid1."), return as-is
        if compartment_identifier.startswith("ocid1."):
            return compartment_identifier
        
        # Otherwise, treat it as a name and search for it
        compartments = self.list_compartments()
        for comp in compartments:
            if comp["name"].lower() == compartment_identifier.lower():
                return comp["id"]
        
        # If not found, raise error
        raise ValueError(
            f"Compartment '{compartment_identifier}' not found. "
            f"Use list_oci_compartments to see available compartments."
        )
    
    def get_cost_data(self, compartment_id: str, start_date: str, end_date: str):
        """Get cost data for a compartment within date range.
        
        Args:
            compartment_id: OCI compartment OCID or name (use "root" for tenancy root)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            
        Returns:
            Dictionary with cost summary data
        """
        try:
            # Resolve compartment ID (handles OCID, name, or "root")
            compartment_id = self.resolve_compartment_id(compartment_id)
            
            # Parse date strings to datetime objects
            try:
                time_usage_started = datetime.strptime(start_date, "%Y-%m-%d")
                # For end_date, OCI Usage API uses EXCLUSIVE endTime
                # To include the full last day, we need to set it to the next day at 00:00:00
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                time_usage_ended = end_date_obj + timedelta(days=1)
            except ValueError as e:
                raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {str(e)}")
            
            # Create request details for Usage API
            # Reference: https://docs.oracle.com/en-us/iaas/tools/python/2.162.0/api/usage_api/client/oci.usage_api.UsageapiClient.html
            # 
            # compartment_depth behavior:
            # - Not set or 0: Only the specified compartment (no children)
            # - 1 or higher: Include child compartments at specified depth
            # 
            # For specific compartments: use compartment_depth=0 to get ONLY that compartment's costs
            # For root/tenancy: use higher depth to include all sub-compartments
            
            # Determine if querying root or specific compartment
            is_root_compartment = (compartment_id == self.config["tenancy"])
            
            # Create base request details
            # When querying specific compartments, we need to include compartmentId in group_by
            # because the API doesn't filter by compartment_id when grouping by service only
            if is_root_compartment:
                # For root, just group by service (all compartments)
                group_by_fields = ["service"]
            else:
                # For specific compartment, group by service AND compartmentId
                # This allows us to filter results client-side
                group_by_fields = ["service", "compartmentId"]
            
            request_details = usage_api.models.RequestSummarizedUsagesDetails(
                tenant_id=self.config["tenancy"],
                time_usage_started=time_usage_started,
                time_usage_ended=time_usage_ended,
                granularity="DAILY",
                query_type="COST",
                group_by=group_by_fields
            )
            
            if is_root_compartment:
                # For root compartment, include all child compartments
                # Note: OCI API allows maximum compartment_depth of 7
                request_details.compartment_depth = 7
            else:
                # For specific compartment, set compartment_id and depth
                # compartment_id must be set as property, not in constructor
                # Note: compartment_depth minimum is 1 (API requirement)
                request_details.compartment_id = compartment_id
                request_details.compartment_depth = 1  # Minimum depth required by API
            
            # Make API call with proactive rate limiting
            # SDK handles retries automatically via DEFAULT_RETRY_STRATEGY
            def api_call():
                return self.usage_client.request_summarized_usages(request_details)
            
            response = self._make_api_call_with_rate_limit(api_call)
            
            # Parse response
            items = response.data.items if response.data else []
            
            # If querying a specific compartment, filter items client-side
            # because the API returns all compartments when grouping by service
            if not is_root_compartment:
                items = [
                    item for item in items 
                    if hasattr(item, 'compartment_id') and item.compartment_id == compartment_id
                ]
            
            total_cost = 0.0
            cost_by_service = {}
            currency = "USD"  # Default, will try to get from response if available
            
            for item in items:
                # Get cost amount (computed_amount contains the cost)
                cost = float(item.computed_amount or 0)
                total_cost += cost
                
                # Get service name
                service = item.service or "Unknown"
                cost_by_service[service] = cost_by_service.get(service, 0) + cost
                
                # Try to get currency from the first item if available
                if hasattr(item, 'currency') and item.currency:
                    currency = item.currency
            
            return {
                "total_cost": total_cost,
                "currency": currency,
                "start_date": start_date,
                "end_date": end_date,
                "compartment_id": compartment_id,
                "cost_by_service": cost_by_service,
                "item_count": len(items)
            }
        except Exception as e:
            return {
                "error": str(e),
                "total_cost": 0.0,
                "cost_by_service": {}
            }

