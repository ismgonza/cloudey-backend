"""
Demo Mode Middleware - Anonymizes ALL API responses for presentations

Toggle with environment variable: DEMO_MODE=true
Easy rollback: Remove environment variable or delete this file
"""

import os
import json
import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse
import logging

logger = logging.getLogger(__name__)

# ⚠️ TOGGLE DEMO MODE WITH ENVIRONMENT VARIABLE
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# ⚙️ COST OBFUSCATION STRATEGY
# Choose one:
# 1. "multiply" - Multiply all costs by a factor (hides scale)
# 2. "add" - Add a constant to all costs (shifts scale)
# 3. "reduce" - Reduce costs by percentage (original behavior)
COST_STRATEGY = os.getenv("DEMO_COST_STRATEGY", "multiply")  # "multiply", "add", or "reduce"
COST_MULTIPLIER = float(os.getenv("DEMO_COST_MULTIPLIER", "2.0"))  # Default: 2x
COST_ADDITION = float(os.getenv("DEMO_COST_ADDITION", "1234.0"))  # Default: +$1234


def get_ocid_suffix(text):
    """Extract last 8 chars from OCID or hash the text if no OCID"""
    import hashlib
    
    # If it looks like an OCID, extract the last 8 chars
    if 'ocid1.' in str(text):
        # Extract just the hash part after the last dot
        parts = str(text).split('.')
        if len(parts) > 0:
            hash_part = parts[-1]
            return hash_part[-8:] if len(hash_part) >= 8 else hash_part
    
    # Otherwise, hash the name to get consistent 8 chars
    hash_obj = hashlib.md5(str(text).encode())
    return hash_obj.hexdigest()[:8]


def anonymize_compartment(name, ocid=None):
    """Map compartment to compartment-abc12345 format"""
    if not name or name == "Unknown":
        return name
    
    # If we have the OCID, use it; otherwise hash the name
    suffix = get_ocid_suffix(ocid if ocid else name)
    return f"compartment-{suffix}"


def anonymize_resource_name(name, resource_type="resource", ocid=None):
    """Map resource name to instance-abc12345, volume-xyz67890, etc."""
    if not name or name in ["Unknown", "N/A"]:
        return name
    
    # Determine type
    name_lower = name.lower()
    if "volume" in name_lower or "vol" in name_lower or resource_type == "volume":
        rtype = "volume"
    elif "load" in name_lower or "lb" in name_lower or resource_type == "lb":
        rtype = "loadbalancer"
    elif "bucket" in name_lower or resource_type == "bucket":
        rtype = "bucket"
    elif any(keyword in name_lower for keyword in ["instance", "server", "vm", "compute"]) or resource_type == "instance":
        rtype = "instance"
    else:
        rtype = "resource"
    
    # Use OCID if available, otherwise hash the name
    suffix = get_ocid_suffix(ocid if ocid else name)
    return f"{rtype}-{suffix}"


def obfuscate_cost(cost):
    """Obfuscate cost value using configured strategy"""
    # ⚠️ COST OBFUSCATION DISABLED - RETURN REAL COSTS
    # Only anonymize names, not costs
    return cost


def anonymize_value(value, key="", parent_data=None):
    """Recursively anonymize data structures"""
    if value is None:
        return value
    
    # Handle different types
    if isinstance(value, dict):
        # Pass the dict itself as parent_data for nested calls
        return {k: anonymize_value(v, k, parent_data=value) for k, v in value.items()}
    
    elif isinstance(value, list):
        # Check if this is a list of costs (numeric values in cost-related context)
        # Common patterns: 'months' array in cost data, 'values' in cost trends
        if value and all(isinstance(v, (int, float)) for v in value):
            # If parent_data suggests this is cost data, transform it
            if isinstance(parent_data, dict):
                # Check if parent has cost-related keys
                has_cost_context = any(
                    keyword in str(parent_data.keys()).lower() 
                    for keyword in ["cost", "compartment", "service", "resource", "total"]
                )
                # Check if key name suggests costs
                key_suggests_cost = key.lower() in ["months", "values", "data"] or "cost" in key.lower()
                
                if has_cost_context and key_suggests_cost:
                    return [obfuscate_cost(v) for v in value]
        
        # Otherwise, recursively process list items
        return [anonymize_value(item, key, parent_data=parent_data) for item in value]
    
    elif isinstance(value, str):
        # Try to find OCID in parent data for consistent anonymization
        ocid = None
        if isinstance(parent_data, dict):
            ocid = parent_data.get('ocid') or parent_data.get('resource_ocid') or parent_data.get('compartment_ocid')
        
        # Anonymize compartment names
        if any(keyword in key.lower() for keyword in ["compartment", "comp_name"]):
            return anonymize_compartment(value, ocid=ocid)
        
        # Anonymize resource names
        elif any(keyword in key.lower() for keyword in [
            "display_name", "resource_name", "name", "instance_name", 
            "volume_name", "lb_name", "server_name"
        ]) and key.lower() not in ["service_name", "shape_name", "region_name"]:
            # Don't anonymize service names, shapes, or regions
            return anonymize_resource_name(value, ocid=ocid)
        
        return value
    
    elif isinstance(value, (int, float)):
        # Obfuscate costs (but not counts, IDs, or percentages)
        if any(keyword in key.lower() for keyword in [
            "cost", "price", "spend", "saving", "total", "amount"
        ]) and "count" not in key.lower() and "percent" not in key.lower():
            return obfuscate_cost(value)
        
        return value
    
    else:
        return value


class DemoModeMiddleware(BaseHTTPMiddleware):
    """Middleware to anonymize all API responses"""
    
    async def dispatch(self, request, call_next):
        # Get response
        response = await call_next(request)
        
        # Only process if demo mode is enabled and it's a JSON response
        if not DEMO_MODE:
            return response
        
        # Skip non-JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response
        
        # Skip streaming responses (like chat SSE)
        if isinstance(response, StreamingResponse):
            return response
        
        # Read response body (we need to do this regardless)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        
        try:
            # Parse JSON
            data = json.loads(body.decode())
            
            # Anonymize data
            anonymized_data = anonymize_value(data)
            
            # Create new response with anonymized data
            new_body = json.dumps(anonymized_data).encode()
            
            # Update headers with correct content length
            new_headers = dict(response.headers)
            new_headers["content-length"] = str(len(new_body))
            
            return Response(
                content=new_body,
                status_code=response.status_code,
                headers=new_headers,
                media_type=response.media_type,
            )
        
        except Exception as e:
            logger.error(f"Demo mode anonymization error: {e}", exc_info=True)
            # Return original response with original body if anonymization fails
            original_headers = dict(response.headers)
            original_headers["content-length"] = str(len(body))
            
            return Response(
                content=body,
                status_code=response.status_code,
                headers=original_headers,
                media_type=response.media_type,
            )



