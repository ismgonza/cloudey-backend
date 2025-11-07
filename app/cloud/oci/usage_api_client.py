"""OCI Usage API operations for cost data."""

import tempfile
import os
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import oci
from oci import usage_api
from oci import retry

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter
from app.cloud.cache import get_cache  # Shared cache for all cloud providers

logger = logging.getLogger(__name__)


def _calculate_smart_ttl(end_date: str) -> int:
    """Calculate appropriate cache TTL based on data recency.
    
    Historical data (older than yesterday) is cached longer since it won't change.
    Recent data has shorter TTL in case of updates.
    
    Args:
        end_date: End date in YYYY-MM-DD format
    
    Returns:
        TTL in seconds
    """
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    data_end = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    if data_end < yesterday:
        # Historical data (>1 day old): cache for 1 hour
        return 3600
    else:
        # Recent data (yesterday or today): cache for 5 minutes
        return 300


class UsageApiClient:
    """Client for OCI Usage API operations (cost data)."""
    
    def __init__(self, user_id: int):
        """Initialize usage API client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        config_dict = get_oci_config_dict(user_id)
        if not config_dict:
            raise ValueError(f"No OCI configuration found for user_id: {user_id}")
        
        self.config = config_dict
        self.user_id = user_id
        self._temp_key_file = None
        self._rate_limiter = get_rate_limiter()
        self._cache = get_cache()
        self._init_client()
    
    def _init_client(self):
        """Initialize OCI SDK usage API client.
        
        The OCI SDK requires a file path for the private key (key_file), not the key content directly.
        Since we store the key as a string in the database, we create a temporary file with secure permissions.
        This temp file is cleaned up when the object is destroyed.
        """
        try:
            # Create a temporary file with secure permissions (0o600 = owner read/write only)
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
                oci_config = {
                    "tenancy": self.config["tenancy"],
                    "user": self.config["user"],
                    "fingerprint": self.config["fingerprint"],
                    "key_file": temp_path,
                    "region": self.config["region"],
                }
                
                # Validate config before using it
                oci.config.validate_config(oci_config)
                
                # Initialize usage API client with retry strategy
                self.usage_client = usage_api.UsageapiClient(
                    oci_config,
                    retry_strategy=retry.DEFAULT_RETRY_STRATEGY
                )
            except Exception:
                # Clean up temp file if something goes wrong
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
            raise ValueError(f"Failed to initialize OCI usage API client: {str(e)}")
    
    def __del__(self):
        """Clean up temporary key file when object is destroyed."""
        if hasattr(self, '_temp_key_file') and self._temp_key_file and os.path.exists(self._temp_key_file):
            try:
                # Overwrite file with zeros before deletion (optional security measure)
                with open(self._temp_key_file, 'wb') as f:
                    f.write(b'\x00' * 4096)
                os.unlink(self._temp_key_file)
            except Exception:
                pass  # Best effort cleanup
    
    def _make_api_call_with_rate_limit(self, api_call, timeout: int = 30):
        """Make an API call with proactive rate limiting and timeout.
        
        The OCI SDK handles retries automatically via DEFAULT_RETRY_STRATEGY.
        This method only does proactive rate limiting before the call.
        
        Args:
            api_call: Callable that makes the API call
            timeout: Timeout in seconds (default: 30)
        """
        self._rate_limiter.wait_if_needed(self.user_id)
        try:
            # Note: OCI SDK doesn't have a direct timeout parameter in most methods
            # The timeout is handled at the HTTP client level via the SDK's config
            # For now, we'll rely on SDK's default timeouts and retry strategy
            return api_call()
        except Exception as e:
            raise ValueError(f"OCI API call failed: {str(e)}")
    
    def get_cost_data(
        self,
        compartment_id: str,
        start_date: str,
        end_date: str,
        granularity: str = "DAILY",
        group_by_resource: bool = False
    ) -> Dict:
        """Fetch cost data for a compartment within a date range.
        
        Args:
            compartment_id: Compartment OCID or "root" for tenancy level
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)
            granularity: DAILY, MONTHLY, or TOTAL
            group_by_resource: If True, group costs by individual resource (resourceId)
        
        Returns:
            Dictionary with total_cost and breakdown by service or resource
        """
        start_time = time.time()
        
        # Check cache first
        cached_result = self._cache.get(
            self.user_id,
            "get_cost_data",
            compartment_id=compartment_id,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            group_by_resource=group_by_resource
        )
        if cached_result is not None:
            logger.info(f"Cache hit for cost_data (user={self.user_id}, took {time.time()-start_time:.2f}s)")
            return cached_result
        
        logger.info(f"Fetching cost data from OCI API (user={self.user_id}, compartment={compartment_id}, dates={start_date} to {end_date})")
        
        try:
            # Parse dates
            time_usage_started = datetime.strptime(start_date, "%Y-%m-%d")
            
            # For end_date, add one day since the API's time_usage_ended is exclusive
            # e.g., if user wants costs for "2024-01-31", we need to set end to "2024-02-01"
            # so the API includes all of 2024-01-31 (00:00:00 to 23:59:59)
            time_usage_ended_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            time_usage_ended = time_usage_ended_dt
            
            # Determine if this is a root (tenancy) or specific compartment query
            is_root_compartment = (compartment_id == self.config["tenancy"])
            
            # Build group_by fields based on query type
            if group_by_resource:
                # Group by resource to get per-resource costs
                # Include service and resourceId for detailed breakdown
                group_by_fields = ["service", "resourceId"]
                if not is_root_compartment:
                    group_by_fields.append("compartmentId")
            else:
                # Standard service-level grouping
                if is_root_compartment:
                    group_by_fields = ["service"]
                else:
                    group_by_fields = ["service", "compartmentId"]
            
            # Build the request
            request_details = usage_api.models.RequestSummarizedUsagesDetails(
                tenant_id=self.config["tenancy"],
                time_usage_started=time_usage_started,
                time_usage_ended=time_usage_ended,
                granularity=granularity,
                query_type="COST",
                group_by=group_by_fields
            )
            
            # Set compartment depth based on query type
            if is_root_compartment:
                # For root, get all compartments (max depth is 7)
                request_details.compartment_depth = 7
            else:
                # For specific compartment, set it as a property (NOT in constructor)
                # and use depth=1 to get only that compartment
                request_details.compartment_id = compartment_id
                request_details.compartment_depth = 1
            
            # Make the API call with rate limiting
            api_call = lambda: self.usage_client.request_summarized_usages(request_details)
            response = self._make_api_call_with_rate_limit(api_call)
            
            # Process the response
            items = response.data.items if response.data else []
            
            # For specific compartments, filter results client-side to ensure accuracy
            # (The API sometimes returns other compartments even with compartment_id set)
            if not is_root_compartment:
                items = [
                    item for item in items 
                    if hasattr(item, 'compartment_id') and item.compartment_id == compartment_id
                ]
            
            # Calculate total cost and breakdown
            total_cost = 0.0
            breakdown = {}
            
            for item in items:
                # Handle None values from OCI API (happens with zero-cost or no data)
                computed_amount = getattr(item, 'computed_amount', None)
                cost = float(computed_amount) if computed_amount is not None else 0.0
                total_cost += cost
                
                if group_by_resource:
                    # Group by resource ID
                    resource_id = getattr(item, 'resource_id', 'Unknown')
                    service_name = getattr(item, 'service', 'Unknown')
                    
                    # Create a unique key combining service and resource
                    key = f"{service_name}:{resource_id}"
                    
                    if key in breakdown:
                        breakdown[key]['cost'] += cost
                    else:
                        breakdown[key] = {
                            'service': service_name,
                            'resource_id': resource_id,
                            'cost': cost
                        }
                else:
                    # Group by service name only
                    service_name = getattr(item, 'service', 'Unknown')
                    if service_name in breakdown:
                        breakdown[service_name] += cost
                    else:
                        breakdown[service_name] = cost
            
            # Sort by cost (highest first)
            if group_by_resource:
                sorted_breakdown = sorted(
                    breakdown.values(),
                    key=lambda x: x['cost'],
                    reverse=True
                )
                result = {
                    "total_cost": round(total_cost, 2),
                    "currency": "USD",
                    "start_date": start_date,
                    "end_date": end_date,
                    "compartment_id": compartment_id,
                    "grouped_by": "resource",
                    "resource_breakdown": [
                        {
                            "service": item['service'],
                            "resource_id": item['resource_id'],
                            "cost": round(item['cost'], 2)
                        }
                        for item in sorted_breakdown
                    ]
                }
            else:
                sorted_breakdown = sorted(
                    breakdown.items(),
                    key=lambda x: x[1],
                    reverse=True
                )
                result = {
                    "total_cost": round(total_cost, 2),
                    "currency": "USD",
                    "start_date": start_date,
                    "end_date": end_date,
                    "compartment_id": compartment_id,
                    "grouped_by": "service",
                    "service_breakdown": [
                        {"service": name, "cost": round(cost, 2)}
                        for name, cost in sorted_breakdown
                    ]
                }
            
            # Cache the result with smart TTL (historical data cached longer)
            cache_ttl = _calculate_smart_ttl(end_date)
            self._cache.set(
                self.user_id,
                "get_cost_data",
                result,
                ttl=cache_ttl,
                compartment_id=compartment_id,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                group_by_resource=group_by_resource
            )
            logger.debug(f"Cached with TTL={cache_ttl}s (historical: {cache_ttl > 300})")
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ COST DATA FETCHED")
            logger.info(f"   Time: {elapsed_time:.2f}s")
            logger.info(f"   Items: {len(items)}")
            logger.info(f"   Total cost: ${result['total_cost']:.2f}")
            
            return result
        except Exception as e:
            raise ValueError(f"Error fetching cost data: {str(e)}")

