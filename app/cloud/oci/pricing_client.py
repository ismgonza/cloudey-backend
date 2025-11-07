"""OCI Pricing API Client.

Uses Oracle Cloud Cost Estimator API to fetch service pricing information.
Reference: https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/signingup_topic-Estimating_Costs.htm
API: https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/
"""

import json
import logging
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class OCIPricingClient:
    """Client for OCI Cost Estimator API.
    
    The OCI Cost Estimator API provides pricing information for OCI services.
    No authentication required for public pricing data.
    """
    
    # OCI Cost Estimator API endpoint
    BASE_URL = "https://apexapps.oracle.com/pls/apex/cetools/api/v1"
    
    def __init__(self):
        """Initialize OCI Pricing client."""
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def get_products(self, part_number: Optional[str] = None) -> List[Dict]:
        """Get OCI product catalog with pricing.
        
        Args:
            part_number: Optional specific part number to filter
        
        Returns:
            List of OCI products with pricing
        """
        try:
            url = f"{self.BASE_URL}/products/"
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            products = data.get('items', [])
            
            if part_number:
                products = [p for p in products if p.get('partNumber') == part_number]
            
            logger.info(f"Retrieved {len(products)} OCI products")
            return products
            
        except Exception as e:
            logger.error(f"Error fetching OCI products: {str(e)}")
            return []
    
    def get_compute_pricing(
        self,
        shape: Optional[str] = None,
        region: Optional[str] = None
    ) -> List[Dict]:
        """Get OCI Compute pricing.
        
        Args:
            shape: Optional shape filter (e.g., 'VM.Standard.E4.Flex')
            region: Optional region filter
        
        Returns:
            List of compute shapes with pricing
        """
        try:
            products = self.get_products()
            
            # Filter for compute products
            compute_products = []
            for product in products:
                # Check if it's a compute product
                product_type = product.get('currICResourceName', '').lower()
                if 'compute' not in product_type and 'instance' not in product_type:
                    continue
                
                # Apply filters
                if shape and shape not in product.get('displayName', ''):
                    continue
                
                if region and region not in product.get('availableIn', []):
                    continue
                
                compute_products.append({
                    'part_number': product.get('partNumber'),
                    'name': product.get('displayName'),
                    'description': product.get('currICDescription'),
                    'unit_price': product.get('pricingUnit'),
                    'currency': product.get('currency', 'USD'),
                    'billing_model': product.get('billingModel'),
                    'available_in': product.get('availableIn', [])
                })
            
            return compute_products[:50]  # Limit results
            
        except Exception as e:
            logger.error(f"Error fetching OCI compute pricing: {str(e)}")
            return []
    
    def get_storage_pricing(self, storage_type: Optional[str] = None) -> List[Dict]:
        """Get OCI Storage pricing.
        
        Args:
            storage_type: Optional type filter ('block', 'object', 'file')
        
        Returns:
            List of storage services with pricing
        """
        try:
            products = self.get_products()
            
            # Filter for storage products
            storage_products = []
            for product in products:
                product_type = product.get('currICResourceName', '').lower()
                
                # Check if it's storage
                if not any(t in product_type for t in ['storage', 'block', 'object', 'file']):
                    continue
                
                # Apply type filter
                if storage_type and storage_type.lower() not in product_type:
                    continue
                
                storage_products.append({
                    'part_number': product.get('partNumber'),
                    'name': product.get('displayName'),
                    'type': product_type,
                    'unit_price': product.get('pricingUnit'),
                    'currency': product.get('currency', 'USD'),
                    'billing_model': product.get('billingModel')
                })
            
            return storage_products[:50]
            
        except Exception as e:
            logger.error(f"Error fetching OCI storage pricing: {str(e)}")
            return []
    
    def compare_regions(self, service_name: str) -> Dict[str, List[Dict]]:
        """Compare pricing across OCI regions for a service.
        
        Args:
            service_name: Service name to compare
        
        Returns:
            Dictionary mapping regions to their pricing
        """
        try:
            products = self.get_products()
            
            # Group by region
            region_pricing = {}
            
            for product in products:
                if service_name.lower() not in product.get('displayName', '').lower():
                    continue
                
                regions = product.get('availableIn', [])
                unit_price = product.get('pricingUnit')
                
                for region in regions:
                    if region not in region_pricing:
                        region_pricing[region] = []
                    
                    region_pricing[region].append({
                        'product': product.get('displayName'),
                        'price': unit_price,
                        'currency': product.get('currency', 'USD')
                    })
            
            return region_pricing
            
        except Exception as e:
            logger.error(f"Error comparing OCI regions: {str(e)}")
            return {}
    
    def estimate_monthly_cost(
        self,
        resources: List[Dict[str, any]]
    ) -> Dict:
        """Estimate monthly cost for a list of resources.
        
        Args:
            resources: List of resources with quantities
                      e.g., [{'type': 'compute', 'shape': 'VM.Standard.E4.Flex', 'ocpus': 2, 'hours': 730}]
        
        Returns:
            Estimated monthly cost breakdown
        """
        try:
            products = self.get_products()
            total_cost = 0.0
            breakdown = []
            
            for resource in resources:
                resource_type = resource.get('type')
                
                # Find matching product in pricing
                matching_product = None
                for product in products:
                    if resource_type in product.get('currICResourceName', '').lower():
                        matching_product = product
                        break
                
                if matching_product:
                    unit_price = float(matching_product.get('pricingUnit', 0))
                    quantity = resource.get('quantity', 1)
                    hours = resource.get('hours', 730)  # Default: 730 hours/month
                    
                    cost = unit_price * quantity * hours
                    total_cost += cost
                    
                    breakdown.append({
                        'resource': resource_type,
                        'unit_price': unit_price,
                        'quantity': quantity,
                        'hours': hours,
                        'cost': cost
                    })
            
            return {
                'total_monthly_cost': round(total_cost, 2),
                'currency': 'USD',
                'breakdown': breakdown
            }
            
        except Exception as e:
            logger.error(f"Error estimating monthly cost: {str(e)}")
            return {'error': str(e)}

