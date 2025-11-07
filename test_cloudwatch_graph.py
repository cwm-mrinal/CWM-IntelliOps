#!/usr/bin/env python3
"""
Test script for CloudWatch graph generation
This helps debug why graphs might not show data
"""

import json
import boto3
from datetime import datetime, timedelta

def test_cloudwatch_graph_generation():
    """
    Test CloudWatch graph generation with various scenarios
    """
    
    # Test case 1: Simple EC2 CPU metric
    test_cases = [
        {
            "name": "EC2 CPU Utilization",
            "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization",
            "dimensions": [{"name": "InstanceId", "value": "i-1234567890abcdef0"}],
            "statistic": "Average",
            "period": 300,
            "region": "ap-south-1"
        },
        {
            "name": "RDS Database Connections",
            "namespace": "AWS/RDS",
            "metric_name": "DatabaseConnections",
            "dimensions": [{"name": "DBInstanceIdentifier", "value": "my-database"}],
            "statistic": "Average",
            "period": 300,
            "region": "ap-south-1"
        },
        {
            "name": "Lambda Duration",
            "namespace": "AWS/Lambda",
            "metric_name": "Duration",
            "dimensions": [{"name": "FunctionName", "value": "my-function"}],
            "statistic": "Average",
            "period": 300,
            "region": "ap-south-1"
        }
    ]
    
    for test_case in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing: {test_case['name']}")
        print(f"{'='*60}")
        
        # Build dimension list
        dimension_kv_list = []
        for dim in test_case['dimensions']:
            dimension_kv_list.extend([dim['name'], dim['value']])
        
        # Create widget JSON
        widget = {
            "width": 600,
            "height": 400,
            "metrics": [
                [test_case['namespace'], test_case['metric_name']] + 
                dimension_kv_list + 
                [{"stat": test_case['statistic']}]
            ],
            "period": test_case['period'],
            "start": "-PT24H",
            "end": "PT0H",
            "title": test_case['name'],
            "view": "timeSeries",
            "region": test_case['region'],
            "timezone": "+0000"
        }
        
        print(f"\nWidget JSON:")
        print(json.dumps(widget, indent=2))
        
        # Try to get metric statistics to verify data exists
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=test_case['region'])
            
            dimension_list = []
            for dim in test_case['dimensions']:
                dimension_list.append({"Name": dim['name'], "Value": dim['value']})
            
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)
            
            response = cloudwatch.get_metric_statistics(
                Namespace=test_case['namespace'],
                MetricName=test_case['metric_name'],
                Dimensions=dimension_list,
                StartTime=start_time,
                EndTime=end_time,
                Period=test_case['period'],
                Statistics=[test_case['statistic']]
            )
            
            datapoints = response.get('Datapoints', [])
            print(f"\n✓ Found {len(datapoints)} datapoints")
            
            if datapoints:
                print(f"  Sample datapoint: {datapoints[0]}")
            else:
                print(f"  ⚠️ No data found - graph will be empty!")
            
            # Try to generate the image
            try:
                image_response = cloudwatch.get_metric_widget_image(
                    MetricWidget=json.dumps(widget)
                )
                print(f"✓ Successfully generated graph image ({len(image_response['MetricWidgetImage'])} bytes)")
            except Exception as e:
                print(f"✗ Failed to generate graph image: {e}")
                
        except Exception as e:
            print(f"✗ Error: {e}")

def test_alarm_extraction():
    """
    Test alarm detail extraction from sample ticket
    """
    print(f"\n{'='*60}")
    print("Testing Alarm Detail Extraction")
    print(f"{'='*60}")
    
    sample_ticket_subject = 'ALARM: "High CPU Usage" in Asia Pacific (Mumbai)'
    sample_ticket_body = """
AWS Account: 123456789012

MetricNamespace: AWS/EC2
MetricName: CPUUtilization
Dimensions: [{"name": "InstanceId", "value": "i-1234567890abcdef0"}]
Threshold: The alarm is in the ALARM state when the metric is GreaterThanThreshold 80.0
ComparisonOperator: GreaterThanThreshold
Statistic: Average
Period: 300
Unit: Percent
"""
    
    print(f"\nSample Ticket Subject:")
    print(sample_ticket_subject)
    print(f"\nSample Ticket Body:")
    print(sample_ticket_body)
    
    # Import the extraction function
    try:
        from monitor_alerts import extract_alarm_details
        
        result = extract_alarm_details(sample_ticket_subject, sample_ticket_body)
        
        print(f"\n✓ Extracted Details:")
        print(f"  Account ID: {result[0]}")
        print(f"  Region: {result[1]}")
        print(f"  Alarm Name: {result[2]}")
        print(f"  Namespace: {result[3]}")
        print(f"  Metric Name: {result[4]}")
        print(f"  Dimensions: {result[5]}")
        print(f"  Threshold: {result[7]}")
        print(f"  Comparison Operator: {result[8]}")
        print(f"  Statistic: {result[9]}")
        print(f"  Period: {result[10]}")
        print(f"  Unit: {result[11]}")
        
    except Exception as e:
        print(f"✗ Error extracting alarm details: {e}")

def generate_troubleshooting_guide():
    """
    Generate a troubleshooting guide for common issues
    """
    print(f"\n{'='*60}")
    print("CloudWatch Graph Troubleshooting Guide")
    print(f"{'='*60}")
    
    guide = """
Common Issues and Solutions:

1. GRAPH IS EMPTY (No Data Showing)
   Causes:
   - Metric has no data in the specified time range
   - Dimensions are incorrect (wrong InstanceId, etc.)
   - Namespace is wrong (AWS/EC2 vs EC2)
   - Statistic name is incorrect (must be: Average, Sum, Minimum, Maximum, SampleCount)
   - Resource is not sending metrics (stopped instance, deleted resource)
   
   Solutions:
   ✓ Verify metric exists: AWS Console → CloudWatch → Metrics
   ✓ Check dimension values match exactly (case-sensitive)
   ✓ Increase time range (use -PT24H instead of -PT3H)
   ✓ Verify resource is active and sending metrics
   ✓ Check if metric has detailed monitoring enabled (EC2)

2. WIDGET GENERATION FAILS
   Causes:
   - Invalid JSON format
   - Unsupported widget parameters
   - Missing required fields
   - Invalid region
   
   Solutions:
   ✓ Validate JSON syntax
   ✓ Use only AWS-supported parameters
   ✓ Include all required fields: metrics, period, start, end, region
   ✓ Verify region code is correct (ap-south-1, not Mumbai)

3. DIMENSIONS NOT MATCHING
   Causes:
   - Dimension names are case-sensitive
   - Extra spaces in dimension values
   - Wrong dimension type (InstanceId vs InstanceName)
   
   Solutions:
   ✓ Use exact dimension names from alarm (InstanceId, not instanceId)
   ✓ Strip whitespace from dimension values
   ✓ Verify dimension exists in CloudWatch console

4. STATISTIC ISSUES
   Causes:
   - Wrong statistic name
   - Case sensitivity
   - Unsupported statistic for metric
   
   Solutions:
   ✓ Use proper case: Average (not average or AVERAGE)
   ✓ Valid statistics: Average, Sum, Minimum, Maximum, SampleCount
   ✓ For percentiles use: p99, p95, p90, etc.

5. TIME RANGE ISSUES
   Causes:
   - Time range too short (no data points)
   - Time range too long (too many data points)
   - Wrong time format
   
   Solutions:
   ✓ Use ISO 8601 duration format: -PT6H (6 hours), -PT24H (24 hours)
   ✓ Start with 24 hours to ensure data visibility
   ✓ Adjust based on metric period (5min period = 300 seconds)

6. CROSS-ACCOUNT ACCESS ISSUES
   Causes:
   - Role assumption fails
   - Insufficient permissions
   - Wrong account ID
   
   Solutions:
   ✓ Verify IAM role has cloudwatch:GetMetricWidgetImage permission
   ✓ Check role trust relationship allows assumption
   ✓ Verify account ID is correct (12 digits)

DEBUGGING STEPS:
1. Check CloudWatch Logs for detailed error messages
2. Verify metric exists in AWS Console manually
3. Test with simple widget first (no annotations, basic metric)
4. Increase time range progressively (1h → 6h → 24h)
5. Verify all extracted dimensions match alarm configuration
6. Test metric data query separately (get_metric_statistics)
7. Check if alarm itself shows data in AWS Console

BEST PRACTICES:
✓ Always verify metric data exists before generating widget
✓ Use longer time ranges (12-24 hours) for better visibility
✓ Include fallback mechanisms for widget generation
✓ Log all widget JSON for debugging
✓ Add data point count to ticket comments
✓ Include metric details in error messages
"""
    
    print(guide)

if __name__ == "__main__":
    print("CloudWatch Graph Testing and Troubleshooting Tool")
    print("="*60)
    
    # Run tests
    test_alarm_extraction()
    test_cloudwatch_graph_generation()
    generate_troubleshooting_guide()
    
    print(f"\n{'='*60}")
    print("Testing Complete!")
    print(f"{'='*60}")
