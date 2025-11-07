import boto3
import time
import botocore
import re
import json
import logging
from html import unescape
import quopri 
import ast
from cross_account_role import assume_role
from Universal_Linux_Command import system_command as linux_command
from Universal_Windows_Command import system_command as windows_command
from send_tree_image_to_zoho import send_tree_output_to_zoho
from constants import REGION, MODEL_ID

# Logger Configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
SSM_DOCUMENT_WINDOWS = "AWS-RunPowerShellScript"
SSM_DOCUMENT_LINUX = "AWS-RunShellScript"

comprehend_client = boto3.client("comprehend")

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

def detect_instance_os_type(instance_id, region, credentials=None):
    if credentials:
        ssm = credentials.client('ssm', region_name=region)
    else:
        ssm = boto3.client('ssm', region_name=region)

    try:
        paginator = ssm.get_paginator('describe_instance_information')
        for page in paginator.paginate():
            for instance_info in page.get("InstanceInformationList", []):
                if instance_info["InstanceId"] == instance_id:
                    return instance_info["PlatformType"]  # "Windows" or "Linux"
    except botocore.exceptions.ClientError as e:
        raise RuntimeError(f"Failed to detect OS: {str(e)}")

    raise ValueError(f"SSM-managed instance not found: {instance_id}")

def send_command_to_instance(instance_id, region, credentials=None):
    if credentials:
        ssm = credentials.client('ssm', region_name=region)
    else:
        ssm = boto3.client('ssm', region_name=region)

    logger.info(f"Detecting OS type for instance: {instance_id}")
    platform_type = detect_instance_os_type(instance_id, region, credentials)
    logger.info(f"Platform detected: {platform_type}")

    if platform_type == "Windows":
        command = windows_command
        document = SSM_DOCUMENT_WINDOWS
    else:
        command = linux_command
        document = SSM_DOCUMENT_LINUX

    try:
        response = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName=document,
            Parameters={"commands": [command]},
            TimeoutSeconds=60
        )
        command_id = response["Command"]["CommandId"]
        logger.info(f"Command sent. Command ID: {command_id}")
    except botocore.exceptions.ClientError as e:
        logger.error(f"Failed to send command: {str(e)}")
        raise

    max_attempts = 18
    delay = 10  # seconds
    for attempt in range(1, max_attempts + 1):
        try:
            time.sleep(delay)
            output = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
            status = output.get('Status')
            logger.info(f"[Attempt {attempt}/{max_attempts}] Command status: {status}")
            
            if status in ['Success', 'Cancelled', 'Failed', 'TimedOut', 'Undeliverable', 'Terminated']:
                logger.info(f"Command finished with status: {status}")
                break
        except botocore.exceptions.ClientError as e:
            logger.warning(f"Attempt {attempt}: Unable to get command status: {str(e)}")
            continue
    else:
        raise TimeoutError(f"Command did not complete within {max_attempts * delay} seconds.")

    return output.get('StandardOutputContent', ''), output.get('StandardErrorContent', '')

def sanitize_tree_output(raw_output):
    clean_output = re.sub(r'[^\x00-\x7F]+', ' ', raw_output)
    return clean_output.strip()

def detect_aws_service(text: str) -> str | None:
    try:
        response = comprehend_client.detect_entities(Text=text, LanguageCode='en')
        
        # Mapping of keywords to CloudWatch Namespaces
        service_keywords = {
            'EC2': 'AWS/EC2',
            'RDS': 'AWS/RDS',
            'ALB': 'AWS/ApplicationELB',
            'ELB': 'AWS/ELB',
            'LoadBalancer': 'AWS/ApplicationELB',
            'Lambda': 'AWS/Lambda',
            'S3': 'AWS/S3',
            'DynamoDB': 'AWS/DynamoDB',
            'SNS': 'AWS/SNS',
            'SQS': 'AWS/SQS',
            'ECS': 'AWS/ECS',
            'EKS': 'AWS/EKS',
            'CloudFront': 'AWS/CloudFront',
            'Redshift': 'AWS/Redshift',
            'ES': 'AWS/ES',
            'OpenSearch': 'AWS/ES',
            'Kinesis': 'AWS/Kinesis',
            'ApiGateway': 'AWS/ApiGateway',
            'Route53': 'AWS/Route53',
            'CloudWatch': 'AWS/CloudWatch',
            'Backup': 'AWS/Backup',
            'IAM': 'AWS/IAM',
            'Fargate': 'AWS/ECS',
            'EMR': 'AWS/ElasticMapReduce'
        }

        logger.info(f"[Comprehend] Detected entities: {response['Entities']}")

        for entity in response['Entities']:
            if entity['Type'] in ['ORGANIZATION', 'COMMERCIAL_ITEM', 'TITLE']:
                for keyword, namespace in service_keywords.items():
                    if keyword.lower() in entity['Text'].lower():
                        logger.info(f"[Comprehend] Matched keyword: {keyword} -> Namespace: {namespace}")
                        return namespace

        logger.warning("[Comprehend] No AWS service matched.")
        return None

    except Exception as e:
        logger.warning(f"[Comprehend] Entity detection failed: {e}")
        return None

def extract_alarm_details(ticket_subject: str, ticket_body: str):
    """
    Enhanced alarm details extraction using Claude 4 via Bedrock with regex fallback.

    Args:
        ticket_subject: The subject line of the alarm notification
        ticket_body: The body content of the alarm notification

    Returns:
        tuple: (account_id, region, alarm_name, namespace, metric_name, dimensions, main_identifier)
    """
    # Initialize Bedrock client
    session = boto3.Session(region_name=REGION)
    bedrock_runtime = session.client("bedrock-runtime")

    # Claude 4 system prompt for alarm extraction
    SYSTEM_PROMPT = (
        "You are an expert AWS CloudWatch alarm analyst specializing in parsing alarm notification details. "
        "Your task is to extract exactly seven pieces of information from alarm notifications:\n\n"
        
        "## EXTRACTION REQUIREMENTS:\n"
        "1) **account_id**: 12-digit AWS account ID (look for patterns like 'AWS Account: 123456789012')\n"
        "2) **region**: AWS region name (look for 'in region X', 'in the X region', standardize to AWS format)\n"
        "3) **alarm_name**: CloudWatch alarm name (look for 'ALARM:', 'Name:', alarm identifiers)\n"
        "4) **namespace**: AWS service namespace (look for 'MetricNamespace:', infer from context if missing)\n"
        "5) **metric_name**: CloudWatch metric name (look for 'MetricName:', default to 'CPUUtilization')\n"
        "6) **dimensions**: List of dimension objects with 'name' and 'value' fields\n"
        "7) **main_identifier**: Primary resource identifier from dimensions (InstanceId, LoadBalancer, etc.)\n\n"
        
        "## PARSING GUIDELINES:\n"
        "• **Account ID**: Extract 12-digit numbers following 'AWS Account', 'Account ID', or similar\n"
        "• **Region**: Convert human-readable region names to AWS format (e.g., 'US East (N. Virginia)' → 'us-east-1')\n"
        "• **Alarm Name**: Extract from ALARM: tags, Name: fields, or subject line patterns\n"
        "• **Namespace**: Look for MetricNamespace, infer from service context (EC2→AWS/EC2, RDS→AWS/RDS)\n"
        "• **Metric Name**: Extract from MetricName field, default to 'CPUUtilization' if missing\n"
        "• **Dimensions**: Handle multiple formats - JSON arrays, key=value pairs, bracketed format\n"
        "• **Main Identifier**: Extract primary resource ID from dimensions (InstanceId, DBInstanceIdentifier, etc.)\n\n"
        
        "## DIMENSION PARSING PATTERNS:\n"
        "• JSON format: [{'name': 'InstanceId', 'value': 'i-12345'}]\n"
        "• Key-value: [InstanceId=i-12345]\n"
        "• Inline: Dimensions: InstanceId=i-12345, LoadBalancer=my-lb\n"
        "• Multiline: InstanceId: i-12345\\nLoadBalancer: my-lb\n"
        "• Dictionary: {InstanceId: i-12345}\n\n"
        
        "## REGION MAPPING:\n"
        "Convert these common formats to AWS region codes:\n"
        "• 'US East (N. Virginia)' → 'us-east-1'\n"
        "• 'US West (Oregon)' → 'us-west-2'\n"
        "• 'Europe (Ireland)' → 'eu-west-1'\n"
        "• 'Asia Pacific (Tokyo)' → 'ap-northeast-1'\n\n"
        
        "## NAMESPACE INFERENCE:\n"
        "If MetricNamespace is missing, infer from context:\n"
        "• EC2 instances, CPU, disk → 'AWS/EC2'\n"
        "• RDS, database → 'AWS/RDS'\n"
        "• Lambda functions → 'AWS/Lambda'\n"
        "• Load balancers → 'AWS/ELB' or 'AWS/ApplicationELB'\n\n"
        
        "## OUTPUT FORMAT:\n"
        "Respond with ONLY valid JSON in this exact structure:\n\n"
        "{\n"
        '  "account_id": "123456789012",\n'
        '  "region": "us-east-1",\n'
        '  "alarm_name": "extracted_alarm_name",\n'
        '  "namespace": "AWS/EC2",\n'
        '  "metric_name": "CPUUtilization",\n'
        '  "dimensions": [\n'
        '    {"name": "InstanceId", "value": "i-12345"},\n'
        '    {"name": "LoadBalancer", "value": "my-lb"}\n'
        '  ],\n'
        '  "main_identifier": "i-12345"\n'
        "}\n\n"
        
        "## CRITICAL RULES:\n"
        "• Return ONLY the JSON response - no explanations, no additional text\n"
        "• Ensure JSON is valid and properly formatted\n"
        "• Use null for missing values, empty array [] for dimensions if none found\n"
        "• Main identifier should be the first important resource ID found in dimensions\n"
        "• Handle quoted-printable encoding and HTML entities in input\n"
        "• Preserve exact case and formatting of extracted values\n\n"
        
        "## MISSING INFORMATION HANDLING:\n"
        "If critical information is missing, still provide the JSON with null values rather than failing.\n"
        "Use reasonable defaults and inference where possible.\n\n"
        
        "## VALIDATION CHECKLIST:\n"
        "Before responding, verify:\n"
        "✓ JSON syntax is valid\n"
        "✓ All required fields present (use null if missing)\n"
        "✓ Dimensions array properly formatted\n"
        "✓ No extra text outside JSON block\n"
        "✓ Account ID is 12 digits if present\n"
        "✓ Region follows AWS naming convention"
    )

    # Claude extraction parameters
    inference_profile_arn = MODEL_ID
    max_retries = 3
    retry_delay_seconds = 2
    max_tokens = 8000

    logger.info("Attempting alarm extraction with Claude 4 via Bedrock.")

    combined_input = f"SUBJECT: {ticket_subject}\n\nBODY:\n{ticket_body}"
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": f"{SYSTEM_PROMPT}\n\nAlarm Notification:\n{combined_input}"
            }
        ]
    }

    # Try Claude first with retries
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Claude extraction attempt {attempt}")

            response = bedrock_runtime.invoke_model(
                modelId=inference_profile_arn,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )

            response_body = json.loads(response["body"].read())
            model_text = response_body["content"][0]["text"].strip()

            logger.info(f"Claude raw output: {model_text}")

            # Parse Claude's JSON response
            parsed = json.loads(model_text)

            account_id = parsed.get("account_id")
            region = parsed.get("region")
            alarm_name = parsed.get("alarm_name")
            namespace = parsed.get("namespace")
            metric_name = parsed.get("metric_name", "CPUUtilization")
            dimensions = parsed.get("dimensions", [])
            main_identifier = parsed.get("main_identifier")

            logger.info(
                f"Claude extraction successful: account_id={account_id}, region={region}, "
                f"alarm_name={alarm_name}, namespace={namespace}, metric_name={metric_name}, "
                f"dimensions={dimensions}, main_identifier={main_identifier}"
            )

            return account_id, region, alarm_name, namespace, metric_name, dimensions, main_identifier

        except Exception as e:
            logger.warning(f"Claude attempt {attempt} failed: {str(e)}")
            if attempt < max_retries:
                time.sleep(retry_delay_seconds)

    # === REGEX FALLBACK EXTRACTION ===
    logger.info("Claude failed, using regex fallback extraction.")

    account_id_match = re.search(r"AWS Account:\s*(\d{12})", ticket_body)
    account_id = account_id_match.group(1) if account_id_match else None

    region_match = re.search(r"in\s+([\w\-\(\)\s]+)", ticket_subject, re.IGNORECASE)
    if not region_match:
        region_match = re.search(r"in the ([\w\-\(\)\s]+) region", ticket_body, re.IGNORECASE)
    region = region_match.group(1).strip() if region_match else None
    if region and region in region_map:
        region = region_map[region]

    alarm_name_match = re.search(r'ALARM:\s*"([^"]+)"', ticket_subject)
    if not alarm_name_match:
        alarm_name_match = re.search(r'- Name:\s*([^\r\n]+)', ticket_body)
    alarm_name = alarm_name_match.group(1).strip() if alarm_name_match else None

    namespace_match = re.search(r"MetricNamespace:\s*([\w\/\-]+)", ticket_body)
    namespace = namespace_match.group(1) if namespace_match else None

    metric_name_match = re.search(r"MetricName:\s*([\w %]+)", ticket_body)
    metric_name = metric_name_match.group(1).strip() if metric_name_match else "CPUUtilization"

    # Decode body
    try:
        decoded_body = quopri.decodestring(ticket_body).decode('utf-8')
    except UnicodeDecodeError as e:
        logger.warning(f"UTF-8 decode failed: {e}. Falling back to latin1.")
        decoded_body = quopri.decodestring(ticket_body).decode('latin1')
    clean_body = unescape(decoded_body)

    dimensions = []
    main_identifier = None

    # Helper for adding dimension
    def add_dimension(name, value):
        nonlocal main_identifier
        name, value = name.strip(), value.strip()
        dimensions.append({"name": name, "value": value})
        if name in ["InstanceId", "LoadBalancer", "DBInstanceIdentifier", "FunctionName"] and not main_identifier:
            main_identifier = value

    # === Format 1: List of dictionaries - Enhanced pattern
    # Look for "Dimensions:" followed by a list structure
    dimension_list_match = re.search(r"Dimensions:\s*(\[.*?\])", clean_body, re.DOTALL)
    if dimension_list_match:
        try:
            # Handle both single quotes and potential escaping
            dimension_str = dimension_list_match.group(1)
            # Replace single quotes with double quotes for valid JSON
            dimension_str = dimension_str.replace("'", '"')
            dimension_list = json.loads(dimension_str)
            for dim in dimension_list:
                if isinstance(dim, dict):
                    # Handle both 'name'/'value' and 'Name'/'Value' keys
                    name = dim.get("name") or dim.get("Name", "")
                    value = dim.get("value") or dim.get("Value", "")
                    if name and value:
                        add_dimension(name, value)
            logger.info(f"Parsed Dimensions from list format: {dimensions}")
        except Exception as e:
            logger.warning(f"Failed to parse list-style dimensions with JSON: {e}")
            # Fallback: try ast.literal_eval for Python-style lists
            try:
                dimension_list = ast.literal_eval(dimension_list_match.group(1))
                for dim in dimension_list:
                    if isinstance(dim, dict):
                        name = dim.get("name") or dim.get("Name", "")
                        value = dim.get("value") or dim.get("Value", "")
                        if name and value:
                            add_dimension(name, value)
                logger.info(f"Parsed Dimensions from list format (ast): {dimensions}")
            except Exception as e2:
                logger.warning(f"Failed to parse list-style dimensions with ast: {e2}")

    # === Format 2: Individual dictionary patterns (fallback for Format 1)
    if not dimensions:
        # Match individual {key: value} patterns
        dict_patterns = re.findall(r"\{\s*['\"]?(\w+)['\"]?\s*:\s*['\"]?([^'\"}\s]+)['\"]?\s*\}", clean_body)
        if dict_patterns:
            for key, value in dict_patterns:
                add_dimension(key, value)
            logger.info(f"Parsed Dimensions from individual dict patterns: {dimensions}")

    # === Format 3: [key=value] bracketed format
    if not dimensions:
        dimension_pairs = re.findall(r'\[([^\]=]+)=\s*([^\]]+)\]', clean_body)
        for key, value in dimension_pairs:
            add_dimension(key, value)
        if dimension_pairs:
            logger.info(f"Parsed Dimensions from bracketed key=value format: {dimensions}")

    # === Format 4: Dimensions: key=value, key2=value2 inline format
    if not dimensions:
        inline_dim_match = re.search(r"Dimensions:\s*([^[\r\n]+)", clean_body)
        if inline_dim_match and not inline_dim_match.group(1).strip().startswith('['):
            inline_dims = inline_dim_match.group(1).split(",")
            for dim in inline_dims:
                if "=" in dim:
                    key, value = dim.split("=", 1)
                    add_dimension(key, value)
            logger.info(f"Parsed Dimensions from inline format: {dimensions}")

    # === Format 5: Escaped JSON string
    if not dimensions:
        json_match = re.search(r'(\[\{\\?"name\\?"\s*:\s*\\?".+?\\?".+?\}])', clean_body)
        if json_match:
            try:
                json_str = json_match.group(1).replace('\\"', '"')
                parsed = json.loads(json_str)
                for dim in parsed:
                    add_dimension(dim.get("name", ""), dim.get("value", ""))
                logger.info(f"Parsed Dimensions from JSON string format: {dimensions}")
            except Exception as e:
                logger.warning(f"Failed to parse JSON string dimensions: {e}")

    # === Format 6: Multiline dimensions like: InstanceId = i-xxx
    if not dimensions:
        multiline_pairs = re.findall(r'^\s*([A-Za-z0-9]+)\s*=\s*([^\r\n]+)', clean_body, re.MULTILINE)
        for key, value in multiline_pairs:
            add_dimension(key, value)
        if multiline_pairs:
            logger.info(f"Parsed Dimensions from multiline format: {dimensions}")

    # === Format 7: Key-Value pairs in lines (alternative multiline format)
    if not dimensions:
        # Look for patterns like "InstanceId: i-12345" or "LoadBalancer: my-lb"
        kv_pairs = re.findall(r'^\s*([A-Za-z0-9]+)\s*:\s*([^\r\n]+)', clean_body, re.MULTILINE)
        for key, value in kv_pairs:
            # Skip common alarm fields that aren't dimensions
            if key.lower() not in ['name', 'timestamp', 'period', 'statistic', 'unit', 'threshold']:
                add_dimension(key, value)
        if kv_pairs:
            logger.info(f"Parsed Dimensions from key-value pairs format: {dimensions}")

    # === Fallback Namespace
    if not namespace:
        inferred_namespace = detect_aws_service(f"{alarm_name} {ticket_subject} {ticket_body}")
        namespace = inferred_namespace if inferred_namespace else "AWS/EC2"
        logger.info(f"Namespace inferred: {namespace}")

    logger.info(
        f"Extracted alarm details: AccountId={account_id}, Region={region}, AlarmName={alarm_name}, "
        f"Namespace={namespace}, MetricName={metric_name}, Dimensions={dimensions}, MainIdentifier={main_identifier}"
    )

    return account_id, region, alarm_name, namespace, metric_name, dimensions, main_identifier

def lambda_handler(event, context):
    try:
        subject = event.get("ticket_subject", "")
        body = event.get("ticket_body", "") 
        ticket_id = event.get("ticket_id", "")

        account_id, region, alarm_name, namespace, metric_name, dimensions, instance_id = extract_alarm_details(subject, body)

        if not account_id or not region:
            return {"status": "error", "message": "Missing account ID or region."}

        if not instance_id:
            return {"status": "error", "message": "InstanceId not found in alarm dimensions."}

        credentials = assume_role(account_id)

        logger.info(f"Sending command to instance: {instance_id}")
        output, error = send_command_to_instance(instance_id, region, credentials)
        clean_output = sanitize_tree_output(output)[:3000]
        clean_error = sanitize_tree_output(error) 

        # Send the directory tree/system report image to Zoho
        zoho_response = send_tree_output_to_zoho(ticket_id=event["ticket_id"], clean_output=clean_output)

        return {
            "status": "success",
            "instance_id": instance_id,
            "stdout": clean_output,
            "stderr": clean_error,
            "zoho_response": zoho_response
        }

    except Exception:
        logger.exception("Unhandled error in Lambda handler")
        return {
            "status": "error",
            "message": "An unexpected error occurred."
        }
