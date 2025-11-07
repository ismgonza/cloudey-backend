"""OCI Object Storage operations."""

from typing import List, Dict, Optional
import oci
from oci import object_storage

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter


class ObjectStorageClient:
    """Client for OCI object storage operations."""
    
    def __init__(self, user_id: int):
        """Initialize object storage client for a specific user.
        
        Args:
            user_id: User ID to fetch OCI config for
        """
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the Object Storage client."""
        self.object_storage_client = object_storage.ObjectStorageClient(
            self.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY
        )
        
        # Get namespace
        try:
            self._rate_limiter.wait_if_needed(self.user_id)
            self.namespace = self.object_storage_client.get_namespace().data
        except Exception as e:
            raise ValueError(f"Error getting namespace: {str(e)}")
    
    def _make_api_call_with_rate_limit(self, api_call):
        """Make an API call with proactive rate limiting."""
        self._rate_limiter.wait_if_needed(self.user_id)
        try:
            return api_call()
        except Exception as e:
            raise ValueError(f"OCI API call failed: {str(e)}")
    
    def list_buckets(self, compartment_id: str) -> List[Dict]:
        """List all object storage buckets in a compartment.
        
        Args:
            compartment_id: Compartment OCID to list buckets from
        
        Returns:
            List of buckets with details
        """
        try:
            api_call = lambda: self.object_storage_client.list_buckets(
                namespace_name=self.namespace,
                compartment_id=compartment_id
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            buckets = []
            for bucket in response.data:
                buckets.append({
                    "name": bucket.name,
                    "namespace": bucket.namespace,
                    "compartment_id": bucket.compartment_id,
                    "time_created": str(bucket.time_created) if bucket.time_created else None,
                    "etag": bucket.etag if hasattr(bucket, 'etag') else None
                })
            
            return buckets
        except Exception as e:
            raise ValueError(f"Error listing buckets: {str(e)}")
    
    def get_bucket(self, bucket_name: str) -> Dict:
        """Get details of a specific object storage bucket.
        
        Args:
            bucket_name: Bucket name
        
        Returns:
            Bucket details including size and object count
        """
        try:
            api_call = lambda: self.object_storage_client.get_bucket(
                namespace_name=self.namespace,
                bucket_name=bucket_name
            )
            response = self._make_api_call_with_rate_limit(api_call)
            
            bucket = response.data
            return {
                "name": bucket.name,
                "namespace": bucket.namespace,
                "compartment_id": bucket.compartment_id,
                "time_created": str(bucket.time_created) if bucket.time_created else None,
                "public_access_type": bucket.public_access_type if hasattr(bucket, 'public_access_type') else None,
                "storage_tier": bucket.storage_tier if hasattr(bucket, 'storage_tier') else None,
                "approximate_count": bucket.approximate_count if hasattr(bucket, 'approximate_count') else None,
                "approximate_size": bucket.approximate_size if hasattr(bucket, 'approximate_size') else None
            }
        except Exception as e:
            raise ValueError(f"Error getting bucket: {str(e)}")

