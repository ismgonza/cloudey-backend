"""
OCI Monitoring Client

Fetches metrics from OCI Monitoring service for resource utilization analysis.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import oci
from oci import monitoring

from app.cloud.oci.config import get_oci_config_dict
from app.cloud.oci.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)


class MonitoringClient:
    """Client for OCI Monitoring service."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.config = get_oci_config_dict(user_id)
        self._rate_limiter = get_rate_limiter()
        self._init_client()
    
    def _init_client(self):
        """Initialize the OCI Monitoring client."""
        self.monitoring_client = monitoring.MonitoringClient(
            self.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY
        )
    
    def _make_api_call_with_rate_limit(self, api_call):
        """Execute API call with rate limiting."""
        self._rate_limiter.wait_if_needed(self.user_id)
        try:
            return api_call()
        except Exception as e:
            logger.error(f"OCI Monitoring API call failed: {str(e)}")
            raise ValueError(f"OCI Monitoring API call failed: {str(e)}")
    
    def get_instance_metrics(
        self,
        compartment_id: str,
        instance_ocid: str,
        metric_names: List[str],
        days: int = 7
    ) -> Dict[str, float]:
        """
        Get metrics for a compute instance over the specified period.
        
        Args:
            compartment_id: Compartment OCID
            instance_ocid: Instance OCID
            metric_names: List of metric names (e.g., ['CpuUtilization', 'MemoryUtilization'])
            days: Number of days to look back (default 7)
        
        Returns:
            Dictionary with metric_name -> average_value
        """
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            results = {}
            
            for metric_name in metric_names:
                # Build MQL query for compute metrics
                query = f"{metric_name}[1h]{{resourceId = \"{instance_ocid}\"}}.mean()"
                
                query_details = monitoring.models.SummarizeMetricsDataDetails(
                    namespace="oci_computeagent",
                    query=query,
                    start_time=start_time,
                    end_time=end_time,
                    resolution="1h"
                )
                
                api_call = lambda qd=query_details, cid=compartment_id: (
                    self.monitoring_client.summarize_metrics_data(
                        compartment_id=cid,
                        summarize_metrics_data_details=qd
                    )
                )
                
                response = self._make_api_call_with_rate_limit(api_call)
                
                # Extract average value from response
                if response.data and len(response.data) > 0:
                    metric_data = response.data[0]
                    if metric_data.aggregated_datapoints:
                        # Calculate average across all datapoints
                        values = [dp.value for dp in metric_data.aggregated_datapoints if dp.value is not None]
                        if values:
                            results[metric_name] = sum(values) / len(values)
                        else:
                            results[metric_name] = 0.0
                    else:
                        results[metric_name] = 0.0
                else:
                    results[metric_name] = 0.0
                
                logger.debug(f"Instance {instance_ocid} - {metric_name}: {results.get(metric_name, 0.0):.2f}%")
            
            return results
            
        except Exception as e:
            logger.error(f"Error fetching instance metrics for {instance_ocid}: {str(e)}")
            # Return zeros if metrics unavailable
            return {metric_name: 0.0 for metric_name in metric_names}
    
    def get_load_balancer_metrics(
        self,
        compartment_id: str,
        lb_ocid: str,
        metric_names: List[str],
        days: int = 7
    ) -> Dict[str, float]:
        """
        Get metrics for a load balancer over the specified period.
        
        Args:
            compartment_id: Compartment OCID
            lb_ocid: Load Balancer OCID
            metric_names: List of metric names (e.g., ['ActiveConnections', 'RequestsPerSecond'])
            days: Number of days to look back (default 7)
        
        Returns:
            Dictionary with metric_name -> average_value
        """
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            results = {}
            
            for metric_name in metric_names:
                # Build MQL query for load balancer metrics
                query = f"{metric_name}[1h]{{resourceId = \"{lb_ocid}\"}}.mean()"
                
                query_details = monitoring.models.SummarizeMetricsDataDetails(
                    namespace="oci_lbaas",
                    query=query,
                    start_time=start_time,
                    end_time=end_time,
                    resolution="1h"
                )
                
                api_call = lambda qd=query_details, cid=compartment_id: (
                    self.monitoring_client.summarize_metrics_data(
                        compartment_id=cid,
                        summarize_metrics_data_details=qd
                    )
                )
                
                response = self._make_api_call_with_rate_limit(api_call)
                
                # Extract average value from response
                if response.data and len(response.data) > 0:
                    metric_data = response.data[0]
                    if metric_data.aggregated_datapoints:
                        # Calculate average across all datapoints
                        values = [dp.value for dp in metric_data.aggregated_datapoints if dp.value is not None]
                        if values:
                            results[metric_name] = sum(values) / len(values)
                        else:
                            results[metric_name] = 0.0
                    else:
                        results[metric_name] = 0.0
                else:
                    results[metric_name] = 0.0
                
                logger.debug(f"Load Balancer {lb_ocid} - {metric_name}: {results.get(metric_name, 0.0):.2f}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error fetching load balancer metrics for {lb_ocid}: {str(e)}")
            # Return zeros if metrics unavailable
            return {metric_name: 0.0 for metric_name in metric_names}
    
    def batch_get_instance_metrics(
        self,
        compartment_id: str,
        instance_ocids: List[str],
        metric_names: List[str] = ['CpuUtilization', 'MemoryUtilization'],
        days: int = 7
    ) -> Dict[str, Dict[str, float]]:
        """
        Get metrics for multiple instances efficiently.
        
        Args:
            compartment_id: Compartment OCID
            instance_ocids: List of instance OCIDs
            metric_names: Metrics to fetch
            days: Days to look back
        
        Returns:
            Dictionary with instance_ocid -> {metric_name -> value}
        """
        results = {}
        
        for instance_ocid in instance_ocids:
            try:
                metrics = self.get_instance_metrics(
                    compartment_id=compartment_id,
                    instance_ocid=instance_ocid,
                    metric_names=metric_names,
                    days=days
                )
                results[instance_ocid] = metrics
            except Exception as e:
                logger.error(f"Error fetching metrics for instance {instance_ocid}: {str(e)}")
                results[instance_ocid] = {name: 0.0 for name in metric_names}
        
        return results
    
    def batch_get_load_balancer_metrics(
        self,
        compartment_id: str,
        lb_ocids: List[str],
        metric_names: List[str] = ['ActiveConnections', 'RequestsPerSecond'],
        days: int = 7
    ) -> Dict[str, Dict[str, float]]:
        """
        Get metrics for multiple load balancers efficiently.
        
        Args:
            compartment_id: Compartment OCID
            lb_ocids: List of load balancer OCIDs
            metric_names: Metrics to fetch
            days: Days to look back
        
        Returns:
            Dictionary with lb_ocid -> {metric_name -> value}
        """
        results = {}
        
        for lb_ocid in lb_ocids:
            try:
                metrics = self.get_load_balancer_metrics(
                    compartment_id=compartment_id,
                    lb_ocid=lb_ocid,
                    metric_names=metric_names,
                    days=days
                )
                results[lb_ocid] = metrics
            except Exception as e:
                logger.error(f"Error fetching metrics for load balancer {lb_ocid}: {str(e)}")
                results[lb_ocid] = {name: 0.0 for name in metric_names}
        
        return results

