"""AWS Pricing API Client.

Uses AWS Price List API to fetch service pricing information.
Reference: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Price_List_Service.html

Requires AWS credentials (Access Key ID + Secret Access Key) to use boto3 SDK.
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Check if boto3 is available
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not installed. AWS pricing API will be limited.")


class AWSPricingClient:
    """Client for AWS Price List API.
    
    The AWS Price List API provides pricing information for AWS services.
    Uses boto3 SDK with AWS credentials for efficient querying.
    
    To use this client, you need AWS credentials:
    - Set AWS_ACCESS_KEY_ID environment variable
    - Set AWS_SECRET_ACCESS_KEY environment variable
    OR
    - Configure AWS CLI (aws configure)
    """
    
    def __init__(self, aws_access_key_id: Optional[str] = None, aws_secret_access_key: Optional[str] = None):
        """Initialize AWS Pricing client.
        
        Args:
            aws_access_key_id: AWS Access Key ID (optional, uses env var if not provided)
            aws_secret_access_key: AWS Secret Access Key (optional, uses env var if not provided)
        """
        self.has_credentials = False
        self.pricing_client = None
        
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 not available. Install with: pip install boto3")
            return
        
        try:
            # Initialize boto3 pricing client (us-east-1 only for pricing API)
            if aws_access_key_id and aws_secret_access_key:
                self.pricing_client = boto3.client(
                    'pricing',
                    region_name='us-east-1',
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key
                )
            else:
                # Use default credentials (from env vars or AWS CLI config)
                self.pricing_client = boto3.client('pricing', region_name='us-east-1')
            
            # Test credentials
            self.pricing_client.describe_services(MaxResults=1)
            self.has_credentials = True
            logger.info("AWS Pricing client initialized successfully")
            
        except NoCredentialsError:
            logger.warning("No AWS credentials found. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")
        except ClientError as e:
            logger.warning(f"AWS credentials invalid: {str(e)}")
        except Exception as e:
            logger.error(f"Error initializing AWS Pricing client: {str(e)}")
    
    def describe_services(self, service_code: Optional[str] = None) -> List[Dict]:
        """Get list of AWS services with pricing information.
        
        Args:
            service_code: Optional specific service code (e.g., 'AmazonEC2')
        
        Returns:
            List of available services
        """
        try:
            # AWS Price List Service API
            url = f"{self.BASE_URL}/services"
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            services = data.get('Services', [])
            
            if service_code:
                services = [s for s in services if s.get('ServiceCode') == service_code]
            
            logger.info(f"Retrieved {len(services)} AWS services")
            return services
            
        except Exception as e:
            logger.error(f"Error fetching AWS services: {str(e)}")
            return []
    
    def get_products(
        self,
        service_code: str,
        filters: Optional[List[Dict]] = None,
        max_results: int = 100
    ) -> List[Dict]:
        """Get product pricing for a specific AWS service.
        
        WARNING: AWS bulk pricing files can be very large (multi-GB).
        This method is currently disabled to prevent hanging.
        
        Args:
            service_code: AWS service code (e.g., 'AmazonEC2', 'AmazonRDS')
            filters: Optional filters for products
            max_results: Maximum number of results to return
        
        Returns:
            List of products with pricing
        """
        # AWS bulk pricing files are too large (7GB+) and cause hangs
        # Would need AWS credentials to use the query API instead
        logger.warning(f"AWS bulk pricing API disabled (files are too large). Service: {service_code}")
        return []
    
    def get_ec2_pricing(self, region: str = 'us-east-1', instance_type: str = None) -> Dict:
        """Get EC2 instance pricing for a specific region using boto3.
        
        Args:
            region: AWS region (e.g., 'us-east-1', 'us-west-2')
            instance_type: Optional specific instance type (e.g., 't3.micro')
        
        Returns:
            Dictionary with EC2 pricing information
        """
        if not self.has_credentials or not self.pricing_client:
            logger.warning("AWS credentials not configured")
            return {
                'region': region,
                'instance_type': instance_type,
                'products': [],
                'error': 'AWS credentials required. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.'
            }
        
        try:
            location = self._region_to_location(region)
            
            # Build filters for the query
            filters = [
                {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': 'AmazonEC2'},
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': location},
                {'Type': 'TERM_MATCH', 'Field': 'productFamily', 'Value': 'Compute Instance'},
                {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
                {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
            ]
            
            if instance_type:
                filters.append({'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type})
            
            logger.info(f"Querying AWS pricing for EC2 in {region}")
            
            # Get products
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=filters,
                MaxResults=10
            )
            
            products = []
            for price_item in response.get('PriceList', []):
                price_data = json.loads(price_item)
                product = price_data.get('product', {})
                attributes = product.get('attributes', {})
                
                # Extract on-demand pricing
                terms = price_data.get('terms', {})
                on_demand = terms.get('OnDemand', {})
                
                price_per_hour = None
                for term_data in on_demand.values():
                    for price_dimension in term_data.get('priceDimensions', {}).values():
                        price_usd = price_dimension.get('pricePerUnit', {}).get('USD')
                        if price_usd:
                            price_per_hour = float(price_usd)
                            break
                
                products.append({
                    'instance_type': attributes.get('instanceType'),
                    'vcpu': attributes.get('vcpu'),
                    'memory': attributes.get('memory'),
                    'storage': attributes.get('storage', 'EBS only'),
                    'network_performance': attributes.get('networkPerformance'),
                    'price_per_hour': price_per_hour
                })
            
            logger.info(f"Retrieved {len(products)} EC2 pricing records")
            
            return {
                'region': region,
                'instance_type': instance_type,
                'products': products
            }
            
        except ClientError as e:
            logger.error(f"AWS API error: {str(e)}")
            return {'error': f"AWS API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Error fetching EC2 pricing: {str(e)}")
            return {'error': str(e)}
    
    def _region_to_location(self, region: str) -> str:
        """Convert AWS region code to location name.
        
        Args:
            region: AWS region code
        
        Returns:
            Location name used in pricing API
        """
        region_map = {
            'us-east-1': 'US East (N. Virginia)',
            'us-east-2': 'US East (Ohio)',
            'us-west-1': 'US West (N. California)',
            'us-west-2': 'US West (Oregon)',
            'eu-west-1': 'EU (Ireland)',
            'eu-central-1': 'EU (Frankfurt)',
            'ap-southeast-1': 'Asia Pacific (Singapore)',
            'ap-northeast-1': 'Asia Pacific (Tokyo)',
        }
        return region_map.get(region, region)
    
    def compare_instance_costs(
        self,
        instance_types: List[str],
        region: str = 'us-east-1'
    ) -> List[Dict]:
        """Compare costs of different instance types.
        
        Args:
            instance_types: List of instance types to compare
            region: AWS region
        
        Returns:
            List of instances with pricing comparison
        """
        try:
            comparisons = []
            
            for instance_type in instance_types:
                pricing = self.get_ec2_pricing(region, instance_type)
                if pricing.get('products'):
                    product = pricing['products'][0]
                    comparisons.append({
                        'instance_type': instance_type,
                        'region': region,
                        'vcpu': product.get('vcpu'),
                        'memory': product.get('memory'),
                        'network': product.get('network_performance')
                    })
            
            return comparisons
            
        except Exception as e:
            logger.error(f"Error comparing instances: {str(e)}")
            return []

