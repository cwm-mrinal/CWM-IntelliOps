# This code is designed to monitor AWS CloudWatch alarms and add screenshots as private comments in Zoho tickets.
# Enhanced version with beautiful, visually appealing graphs with proper labeling and threshold indicators.
import re
import ast
import json
import base64
import logging
import boto3
from html import unescape
import quopri
from datetime import datetime, timedelta
from zoho_alarm_pvt_comment import add_private_comment_with_attachment
from cross_account_role import assume_role

region_map = {
    "United States (N. Virginia)": "us-east-1",
    "United States (Ohio)": "us-east-2",
    "United States (N. California)": "us-west-1",
    "United States (Oregon)": "us-west-2",
    "Asia Pacific (Hyderabad)": "ap-south-2",
    "Asia Pacific (Mumbai)": "ap-south-1",
    "Asia Pacific (Osaka)": "ap-northeast-3",
    "Asia Pacific (Seoul)": "ap-northeast-2",
    "Asia Pacific (Singapore)": "ap-southeast-1",
    "Asia Pacific (Sydney)": "ap-southeast-2",
    "Asia Pacific (Tokyo)": "ap-northeast-1",
    "Canada (Central)": "ca-central-1",
    "Europe (Frankfurt)": "eu-central-1",
    "Europe (Ireland)": "eu-west-1",
    "Europe (London)": "eu-west-2",
    "Europe (Paris)": "eu-west-3",
    "Europe (Stockholm)": "eu-north-1",
    "South America (São Paulo)": "sa-east-1"
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def extract_alarm_details(ticket_subject: str, ticket_body: str):
    # Extract account ID
    account_id_match = re.search(r"AWS Account:\s*(\d{12})", ticket_body)
    account_id = account_id_match.group(1) if account_id_match else None

    # Extract region
    region_match = re.search(r'in\s+([\w\s\-\(\)]+)', ticket_subject, re.IGNORECASE)
    if not region_match:
        region_match = re.search(r'in the ([\w\s\-\(\)]+) region', ticket_body, re.IGNORECASE)
    region = region_match.group(1).strip() if region_match else None
    if region and region in region_map:
        region = region_map[region] 

    # Decode ticket body
    try:
        decoded_body = quopri.decodestring(ticket_body).decode('utf-8')
    except UnicodeDecodeError:
        decoded_body = quopri.decodestring(ticket_body).decode('latin1')
    clean_body = unescape(decoded_body) 

    # Extract alarm name
    alarm_name_match = re.search(r'ALARM:\s*"([^"]+)"', ticket_subject)
    if not alarm_name_match:
        alarm_name_match = re.search(r'- Name:\s*([^\r\n]+)', ticket_body)
    alarm_name = alarm_name_match.group(1).strip() if alarm_name_match else None

    # Extract namespace
    namespace_match = re.search(r"MetricNamespace:\s*([\w\/\-]+)", ticket_body)
    namespace = namespace_match.group(1) if namespace_match else None

    # Extract metric name
    metric_name_match = re.search(r"MetricName:\s*([\w %]+)", ticket_body)
    metric_name = metric_name_match.group(1).strip() if metric_name_match else "CPUUtilization"

    # Extract threshold from descriptive Threshold section in ticket body
    threshold_block_match = re.search(
        r"Threshold:\s*[-\s]*The alarm is in the ALARM state when the metric is (\w+) ([\d.]+)",
        clean_body, re.IGNORECASE | re.DOTALL
    )
    if threshold_block_match:
        comparison_operator = threshold_block_match.group(1)
        threshold = float(threshold_block_match.group(2))
    else:
        # fallback: simple threshold patterns
        threshold_match = re.search(
            r"Threshold[\s:=]*\s*([\d.]+)", clean_body, re.IGNORECASE
        )
        threshold = float(threshold_match.group(1)) if threshold_match else None

    # Extract comparison operator
    operator_match = re.search(r"ComparisonOperator:\s*(\w+)", ticket_body)
    comparison_operator = operator_match.group(1) if operator_match else "GreaterThanThreshold"

    # Extract statistic
    statistic_match = re.search(r"Statistic:\s*(\w+)", ticket_body)
    statistic = statistic_match.group(1) if statistic_match else "Average"

    # Extract period
    period_match = re.search(r"Period:\s*(\d+)", ticket_body)
    period = int(period_match.group(1)) if period_match else 300

    # Extract unit
    unit_match = re.search(r"Unit:\s*(\w+)", ticket_body)
    unit = unit_match.group(1) if unit_match else None

    dimensions = []
    main_identifier = None

    # Helper function
    def add_dimension(name, value):
        nonlocal main_identifier
        name, value = name.strip(), value.strip()
        dimensions.append({"name": name, "value": value})
        if name in ["InstanceId", "LoadBalancer", "DBInstanceIdentifier", "FunctionName"] and not main_identifier:
            main_identifier = value

    # === Format 1: JSON-style list
    match = re.search(r"Dimensions:\s*(\[.*?\])", clean_body, re.DOTALL)
    if match:
        try:
            dim_str = match.group(1).replace("'", '"')
            dim_list = json.loads(dim_str)
            for dim in dim_list:
                name = dim.get("name") or dim.get("Name")
                value = dim.get("value") or dim.get("Value")
                if name and value:
                    add_dimension(name, value)
        except Exception:
            try:
                dim_list = ast.literal_eval(match.group(1))
                for dim in dim_list:
                    name = dim.get("name") or dim.get("Name")
                    value = dim.get("value") or dim.get("Value")
                    if name and value:
                        add_dimension(name, value)
            except Exception:
                pass

    # === Format 2: Bracketed key=value
    if not dimensions:
        for key, val in re.findall(r'\[([^\]=]+)=\s*([^\]]+)\]', clean_body):
            add_dimension(key, val)

    # === Format 3: Inline comma-separated Dimensions: key=value, key2=value2
    if not dimensions:
        inline_match = re.search(r"Dimensions:\s*([^\r\n]+)", clean_body)
        if inline_match:
            dim_parts = inline_match.group(1).split(",")
            for part in dim_parts:
                if "=" in part:
                    key, val = part.split("=", 1)
                    add_dimension(key, val)

    # === Format 4: Escaped JSON string
    if not dimensions:
        json_match = re.search(r'(\[\{\\?"name\\?"\s*:\s*\\?".+?\\?".+?\}])', clean_body)
        if json_match:
            try:
                json_str = json_match.group(1).replace('\\"', '"')
                dim_list = json.loads(json_str)
                for dim in dim_list:
                    add_dimension(dim.get("name", ""), dim.get("value", ""))
            except Exception:
                pass

    # === Format 5: Multiline key = value
    if not dimensions:
        multiline_pairs = re.findall(r'^\s*([A-Za-z0-9]+)\s*=\s*([^\r\n]+)', clean_body, re.MULTILINE)
        for key, val in multiline_pairs:
            add_dimension(key, val)

    # === Format 6: Key: Value pairs (avoid known non-dim fields)
    if not dimensions:
        kv_pairs = re.findall(r'^\s*([A-Za-z0-9]+)\s*:\s*([^\r\n]+)', clean_body, re.MULTILINE)
        for key, val in kv_pairs:
            if key.lower() not in ['name', 'timestamp', 'period', 'statistic', 'unit', 'threshold', 'metricnamespace', 'metricname']:
                add_dimension(key, val)

    # === Final fallback: inferred namespace
    if not namespace:
        namespace = "AWS/EC2"

    logger.info(
        f"Extracted alarm details: AccountId={account_id}, Region={region}, "
        f"AlarmName={alarm_name}, Namespace={namespace}, MetricName={metric_name}, "
        f"Dimensions={dimensions}, MainIdentifier={main_identifier}, "
        f"Threshold={threshold}, ComparisonOperator={comparison_operator}, "
        f"Statistic={statistic}, Period={period}, Unit={unit}"
    )

    return (account_id, region, alarm_name, namespace, metric_name, dimensions, 
            main_identifier, threshold, comparison_operator, statistic, period, unit)

def get_metric_unit_label(namespace, metric_name, unit=None):
    """Get appropriate unit label for metrics"""
    if unit:
        return unit
    
    # Common metric units mapping
    unit_mapping = {
        "CPUUtilization": "Percent",
        "DiskReadOps": "Count/Second",
        "DiskWriteOps": "Count/Second",
        "NetworkIn": "Bytes",
        "NetworkOut": "Bytes",
        "StatusCheckFailed": "Count",
        "RequestCount": "Count",
        "TargetResponseTime": "Seconds",
        "HTTPCode_Target_2XX_Count": "Count",
        "HTTPCode_Target_4XX_Count": "Count",
        "HTTPCode_Target_5XX_Count": "Count",
        "HealthyHostCount": "Count",
        "UnHealthyHostCount": "Count",
        "Duration": "Milliseconds",
        "Errors": "Count",
        "Invocations": "Count",
        "Throttles": "Count",
        "DatabaseConnections": "Count",
        "ReadLatency": "Seconds",
        "WriteLatency": "Seconds",
        "ReadIOPS": "Count/Second",
        "WriteIOPS": "Count/Second"
    }
    
    return unit_mapping.get(metric_name, "Count")

def get_metric_color_scheme(namespace, metric_name):
    """Get appropriate color scheme based on metric type"""
    color_schemes = {
        "CPUUtilization": "#FF6B6B",  # Red for CPU
        "MemoryUtilization": "#4ECDC4",  # Teal for Memory
        "DiskReadOps": "#45B7D1",  # Blue for Disk
        "DiskWriteOps": "#96CEB4",  # Green for Disk
        "NetworkIn": "#FFEAA7",  # Yellow for Network
        "NetworkOut": "#DDA0DD",  # Purple for Network
        "Duration": "#FF7675",  # Light Red for Duration
        "Errors": "#E17055",  # Orange-Red for Errors
        "RequestCount": "#00B894",  # Green for Requests
        "DatabaseConnections": "#6C5CE7"  # Purple for DB
    }
    
    return color_schemes.get(metric_name, "#74B9FF")  # Default blue

def create_enhanced_metric_widget(alarm_details):
    """Create an enhanced, visually appealing metric widget that complies with AWS API"""
    (alarm_name, region, namespace, metric_name, dimensions, 
     threshold, comparison_operator, statistic, period, unit) = alarm_details

    # Convert list of dicts to flattened key-value pairs
    dimension_kv_list = []
    for dim in dimensions:
        if isinstance(dim, dict) and "name" in dim and "value" in dim:
            dimension_kv_list.extend([dim["name"], dim["value"]])
        else:
            for key, value in dim.items():
                if key not in ["name", "value"]:
                    dimension_kv_list.extend([key, value])

    # Get unit label
    unit_label = get_metric_unit_label(namespace, metric_name, unit)

    # Build metrics array - AWS API requires EXACT format
    # Format: [[namespace, metric_name, dim_name1, dim_value1, dim_name2, dim_value2, ...]]
    # NO additional options or configurations in the metrics array
    metrics = [[namespace, metric_name] + dimension_kv_list]

    # Create dimension labels for title
    dim_labels = []
    for dim in dimensions:
        if isinstance(dim, dict) and "name" in dim and "value" in dim:
            dim_labels.append(f"{dim['name']}: {dim['value']}")

    # Enhanced title with resource information
    enhanced_title = f"CloudWatch Alarm: {alarm_name}"
    if dim_labels:
        enhanced_title += f" | {' | '.join(dim_labels[:2])}"

    # Create basic widget structure (AWS API compliant)
    widget = {
        "width": 600,
        "height": 400,
        "metrics": metrics,
        "period": period,
        "stat": statistic.title() if statistic else "Average",  # Ensure proper case
        "start": "-PT3H",  # Show 3 hours of data
        "end": "PT0H",
        "title": enhanced_title,
        "view": "timeSeries",
        "region": region
    }

    # Add threshold annotation if threshold exists (AWS supported format)
    if threshold is not None:
        operator_symbols = {
            "GreaterThanThreshold": ">",
            "GreaterThanOrEqualToThreshold": ">=",
            "LessThanThreshold": "<",
            "LessThanOrEqualToThreshold": "<="
        }
        
        operator_symbol = operator_symbols.get(comparison_operator, ">")
        
        # Add annotations in AWS supported format
        widget["annotations"] = {
            "horizontal": [{
                "label": f"Alarm Threshold ({operator_symbol} {threshold} {unit_label})",
                "value": threshold
            }]
        }
        
        # Add y-axis configuration
        widget["yAxis"] = {
            "left": {
                "min": 0 if metric_name in ["CPUUtilization", "MemoryUtilization"] else None
            }
        }

    return json.dumps(widget)

def get_cloudwatch_alarm_image(account_id, region, alarm_name, namespace, metric_name, 
                               dimensions, threshold=None, comparison_operator=None, 
                               statistic="Average", period=300, unit=None):
    """Get enhanced CloudWatch alarm image with beautiful styling"""
    session = assume_role(account_id)
    cloudwatch = session.client('cloudwatch', region_name=region)

    alarm_details = (alarm_name, region, namespace, metric_name, dimensions, 
                    threshold, comparison_operator, statistic, period, unit)
    
    metric_widget_str = create_enhanced_metric_widget(alarm_details)
    
    logger.info(f"Fetching enhanced CloudWatch metric widget image with widget: {metric_widget_str}")
    
    try:
        response = cloudwatch.get_metric_widget_image(MetricWidget=metric_widget_str)
        logger.info("Successfully fetched enhanced CloudWatch metric image.")
        return response['MetricWidgetImage']
    except Exception as e:
        logger.error(f"Error fetching metric widget image: {e}")
        # Fallback to simpler widget if enhanced version fails
        simple_widget = create_simple_fallback_widget(alarm_details)
        response = cloudwatch.get_metric_widget_image(MetricWidget=simple_widget)
        return response['MetricWidgetImage']

def create_simple_fallback_widget(alarm_details):
    """Create a simple fallback widget if enhanced version fails"""
    (alarm_name, region, namespace, metric_name, dimensions, 
     threshold, comparison_operator, statistic, period, unit) = alarm_details
    
    dimension_kv_list = []
    for dim in dimensions:
        if isinstance(dim, dict) and "name" in dim and "value" in dim:
            dimension_kv_list.extend([dim["name"], dim["value"]])

    # Simple AWS compliant metrics format
    metrics = [[namespace, metric_name] + dimension_kv_list]

    widget = {
        "width": 600,
        "height": 400,
        "metrics": metrics,
        "period": period,
        "start": "-PT1H",
        "end": "PT0H",
        "title": f"CloudWatch Alarm: {alarm_name}",
        "view": "timeSeries",
        "region": region
    }

    return json.dumps(widget)

def lambda_handler(event, context):
    logger.info("Enhanced monitor_alerts Lambda invoked.")
    try:
        body = event.get('body')

        if isinstance(body, str):
            try:
                logger.debug(f"Raw body before JSON parsing: {body[:1200]}")
                sanitized_body = re.sub(r'[\x00-\x1F\x7F]', '', body)
                body = json.loads(sanitized_body)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": f"Invalid JSON body: {str(e)}"})
                }

        ticket_id = str(body.get("ticketId"))
        ticket_subject = body.get("ticketSubject", "")
        ticket_body = body.get("ticketBody", "")

        # Extract enhanced alarm details
        (account_id, region, alarm_name, namespace, metric_name, dimensions, 
         main_identifier, threshold, comparison_operator, statistic, period, unit) = extract_alarm_details(ticket_subject, ticket_body)

        # Normalize statistic case
        statistic = statistic.title() if statistic else "Average"

        if not all([account_id, region, alarm_name]):
            error_msg = "Missing required alarm details: account_id, region, or alarm_name."
            logger.error(error_msg)
            return {"statusCode": 400, "body": json.dumps({"error": error_msg})}

        logger.info(f"Processing alarm with normalized statistic: {statistic}")

        # Get enhanced image with all styling and threshold information
        image_bytes = get_cloudwatch_alarm_image(
            account_id, region, alarm_name, namespace, metric_name, dimensions,
            threshold, comparison_operator, statistic, period, unit
        )
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        comment_text = f"Private Comment: Attached CloudWatch Alarm Screenshot for alarm '{alarm_name}' in region {region}." 

        zoho_response = add_private_comment_with_attachment(
            ticket_id=ticket_id,
            comment_text=comment_text,
            image_base64=image_base64,
            image_filename=f"{alarm_name.replace(' ', '_')}_Dashboard.png"
        )

        logger.info(f"Successfully added enhanced private comment to Zoho ticket {ticket_id}. Zoho response: {zoho_response}")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Successfully added enhanced CloudWatch alarm dashboard as private comment",
                "ticketId": ticket_id,
                "features": [
                    "Enhanced visual styling",
                    "Threshold indicators",
                    "3-hour data view",
                    "AWS-compliant formatting",
                    "Professional annotations"
                ]
            }),
        }

    except Exception as e:
        logger.error(f"Exception in enhanced monitor_alerts Lambda: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }