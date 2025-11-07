import boto3
import botocore
import os
import json
import base64
import re
import random
import string
import time
import logging
from datetime import datetime
from botocore.exceptions import ClientError
from rapidfuzz import fuzz
from cross_account_role import assume_role
from constants import ACCOUNT_TABLE_NAME
from create_rdp_user_connect_profile import SSM_DOCUMENT_NAME, SSM_DOCUMENT_CONTENT
from constants import REGION, MODEL_ID

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

region_map = {
    "Mumbai": "ap-south-1", "Hyderabad": "ap-south-2", "Osaka": "ap-northeast-3", "Seoul": "ap-northeast-2",
    "N. Virginia": "us-east-1", "Ohio": "us-east-2", "N. California": "us-west-1", "Oregon": "us-west-2",
    "Singapore": "ap-southeast-1", "Sydney": "ap-southeast-2", "Tokyo": "ap-northeast-1", "Canada": "ca-central-1",
    "Frankfurt": "eu-central-1", "Ireland": "eu-west-1", "London": "eu-west-2", "Paris": "eu-west-3",
    "Stockholm": "eu-north-1", "São Paulo": "sa-east-1"
}

session = boto3.Session(region_name=REGION)
bedrock_runtime = session.client("bedrock-runtime")

SYSTEM_PROMPT = (
    "You are an expert IT automation assistant specializing in RDP user creation requests. "
    "Your task is to parse user requests and extract exactly three pieces of information:\n\n"
    
    "## EXTRACTION REQUIREMENTS:\n"
    "1) **server_name**: The target Windows server name (look for server names, hostnames, machine names)\n"
    "2) **usernames**: Complete list of all usernames to create (extract from various formats)\n"
    "3) **group_map**: Map each username to its assigned group/role (handle multiple assignment patterns)\n\n"
    
    "## PARSING GUIDELINES:\n"
    "• **Server identification**: Look for patterns like 'server named X', 'on server X', 'machine X', 'host X'\n"
    "• **Username extraction**: Handle formats like lists, bullet points, comma-separated, 'and' separated\n"
    "• **Group assignment**: Recognize patterns like 'assign X to Y group', 'X should be in Y', 'give X access to Y'\n"
    "• **Same group logic**: If all users get the same group, assign that group to each user individually\n"
    "• **Multiple groups**: If a user gets multiple groups, join them with commas\n"
    "• **Default handling**: If no specific groups mentioned, use empty string for each user\n\n"
    
    "## COMMON PATTERNS TO RECOGNIZE:\n"
    "• 'Create users X, Y, Z on server ABC with admin access'\n"
    "• 'Add john.doe and jane.smith to ServerName in Users group'\n"
    "• 'Please create: user1 (admin), user2 (users), user3 (admin)'\n"
    "• 'Server: XYZ, Users: A, B, C, Groups: admin for A, users for B and C'\n\n"
    
    "## OUTPUT FORMAT:\n"
    "Respond with ONLY valid JSON in this exact structure:\n\n"
    "{\n"
    '  "server_name": "extracted_server_name",\n'
    '  "usernames": ["user1", "user2", "user3"],\n'
    '  "group_map": {\n'
    '    "user1": "group1",\n'
    '    "user2": "group2",\n'
    '    "user3": "group1"\n'
    "  }\n"
    "}\n\n"
    
    "## CRITICAL RULES:\n"
    "• Return ONLY the JSON response - no explanations, no additional text\n"
    "• Ensure JSON is valid and properly formatted\n"
    "• Use exact usernames as provided (preserve case, special characters)\n"
    "• If server name unclear, make best guess from context\n"
    "• If groups unclear, use empty string \"\" for affected users\n"
    "• Always include all three fields even if some are empty\n"
    "• Handle edge cases gracefully (typos, unusual formatting, mixed languages)\n\n"
    
    "## MISSING INFORMATION HANDLING:\n"
    "If any required information (server name or usernames) is missing or cannot be determined, "
    "respond with ONLY this question (no JSON):\n\n"
    "\"Can you please provide the missing information? Specifically, I need the server name, usernames, or group assignments.\"\n\n"
    
    "## VALIDATION CHECKLIST:\n"
    "Before responding, verify:\n"
    "✓ Server name extracted and non-empty\n"
    "✓ At least one username in the list\n"
    "✓ Every username has corresponding group_map entry\n"
    "✓ JSON syntax is valid\n"
    "✓ No extra text outside JSON block"
)

def generate_password(length=10):
    characters = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(random.choice(characters) for _ in range(length))


def extract_email_address(email_input):
    """
    Extract the actual email address from a formatted string or list like:
    '"Mrinal Bhoumick"<mrinal.b@cloudworkmates.com>' or 
    '['"Mrinal Bhoumick"<mrinal.b@cloudworkmates.com>']' or
    ['mrinal.b@cloudworkmates.com']
    """
    if not email_input:
        return None
    
    # If it's a list, take the first element
    if isinstance(email_input, list):
        if len(email_input) == 0:
            return None
        email_string = email_input[0]
    else:
        email_string = email_input
    
    # Convert to string if it's not already
    email_string = str(email_string)
    
    # Remove brackets and quotes from the beginning and end
    cleaned = email_string.strip('[]"\'')
    
    # Extract email using regex - look for email pattern inside angle brackets or standalone
    email_pattern = r'<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    match = re.search(email_pattern, cleaned)
    
    if match:
        # Return the email from angle brackets or the standalone email
        return match.group(1) if match.group(1) else match.group(2)
    
    return None

def parse_ticket_for_tsplus(ticket_body):
    """
    Parses the ticket body for TSPlus details.
    1) First tries Claude Sonnet 4 via Bedrock.
    2) Falls back to regex-based extraction with RapidFuzz if Claude fails.
    Returns: server_name, usernames list, and group_map dict.
    """
    inference_profile_arn = MODEL_ID
    max_retries = 3
    retry_delay_seconds = 2
    max_tokens = 25000

    logger.info("Parsing ticket body with Claude Sonnet 4 via Bedrock.")

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": f"{SYSTEM_PROMPT}\n\nUser Request:\n{ticket_body}"
            }
        ]
    }

    # -------- Try Claude first --------
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(json.dumps({"event": "invoke_model_attempt", "attempt": attempt}))

            response = bedrock_runtime.invoke_model(
                modelId=inference_profile_arn,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )

            response_body = json.loads(response["body"].read())
            model_text = response_body["content"][0]["text"]
            logger.info(json.dumps({"event": "model_raw_output", "text": model_text}))

            parsed = json.loads(model_text)

            server_name = parsed.get("server_name", "").strip()
            usernames = parsed.get("usernames", [])
            group_map = parsed.get("group_map", {})

            if not server_name or not usernames:
                raise ValueError("Incomplete extraction: missing server_name or usernames")

            logger.info(
                "Parsed using Claude: server_name=%s, usernames=%s, group_map=%s",
                server_name, usernames, group_map
            )
            return server_name, usernames, group_map

        except Exception as e:
            logger.warning(json.dumps({
                "event": "invoke_model_error",
                "attempt": attempt,
                "error": str(e)
            }))
            if attempt == max_retries:
                logger.info("Claude failed after retries; falling back to regex parsing.")
            else:
                time.sleep(retry_delay_seconds)

    # -------- Fallback to regex --------
    logger.info("Fallback: Parsing ticket with regex & RapidFuzz.")

    ticket_body_norm = ticket_body.replace('\r\n', '\n').replace('\r', '\n')
    ticket_body_norm = re.sub(r'\n+', '\n', ticket_body_norm).strip()
    ticket_body_norm = re.sub(
        r'(Regards,|Thanks,|Best,|Sincerely,).*$', '', ticket_body_norm,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Server name extraction
    server_patterns = [
        r"server named ([^\s:,;.!?]+)",
        r"server is ([^\s:,;.!?]+)",
        r"server[:\s]+([^\s;,]+)",
        r"on server ([^\s:,;.!?]+)",
        r"server\s*=\s*([^\s,;:.]+)",
    ]

    server_name = ""
    for line in ticket_body_norm.split('\n'):
        line_clean = line.strip()
        if not line_clean:
            continue

        if any(fuzz.partial_ratio(line_clean.lower(), kw) > 80 for kw in [
            "server named", "server is", "server:"
        ]):
            for pattern in server_patterns:
                match = re.search(pattern, line_clean, re.IGNORECASE)
                if match:
                    server_name = match.group(1).strip().strip(".,;:")
                    logger.debug("Server name matched with pattern %s: %s", pattern, server_name)
                    break
        if server_name:
            break

    if not server_name:
        logger.error("Server name not found in ticket body (regex fallback).")
        raise Exception("Server name not found in ticket body")

    # Usernames extraction
    STOPWORDS = {
        'could', 'you', 'the', 'rdp', 'server', 'named', 'create', 'following',
        'users', 'assign', 'group', 'groups', 'also', 'all', 'three', 'and', 'to', 'be',
        'on', 'please', 'kindly', 'should', 'with', 'team', 'for', 'request'
    }

    usernames = []
    user_block_match = re.search(
        r"(?:create|following).*?users.*?:([\s\S]+?)(?:assign|map|to|$)",
        ticket_body_norm, re.IGNORECASE
    )
    if user_block_match:
        user_block = user_block_match.group(1)
        for line in user_block.strip().split('\n'):
            for token in re.split(r'[,;\s]+', line.strip()):
                cleaned = re.sub(r'[^\w\-_.@]', '', token.strip())
                if cleaned and cleaned.lower() not in STOPWORDS and len(cleaned) > 2:
                    usernames.append(cleaned)

    if not usernames:
        logger.error("No valid usernames found in ticket body (regex fallback).")
        raise Exception("No valid usernames found in ticket body")

    logger.debug("Extracted usernames: %s", usernames)

    # Group assignment extraction
    group_map = {user: "" for user in usernames}
    group_patterns = [
        r"assign (.*?) (?:group|role|access) to (.*?)(?:\s+and|\s*,|\s*$)",
        r"(.*?) should be assigned to (.*?) (?:group|role|access)",
        r"(.*?) assigned to (.*?) (?:group|role|access)",
        r"give (.*?) access to (.*?) (?:group|role)",
        r"add (.*?) to (.*?) (?:group|role|access)",
        r"(.*?)[:\s]+(.*?) (?:group|role|access)",
    ]

    for line in ticket_body_norm.split('\n'):
        line_clean = line.strip()
        if not line_clean:
            continue

        if any(fuzz.partial_ratio(line_clean.lower(), kw) > 80 for kw in [
            "assign", "map", "should be assigned", "add", "give access"
        ]):
            for pattern in group_patterns:
                matches = re.findall(pattern, line_clean, re.IGNORECASE)
                for match in matches:
                    if len(match) == 2:
                        if "assign" in pattern and "to" in pattern:
                            groups_text, users_text = match
                        else:
                            users_text, groups_text = match

                        groups_text = re.sub(r'^(also|please|kindly)\s+', '', groups_text.strip(), flags=re.IGNORECASE)
                        groups = [re.sub(r'[\s\.,;]+$', '', g.strip()) for g in re.split(r'\s+and\s+|,\s*|;', groups_text.strip()) if g.strip()]
                        users = [re.sub(r'[^\w\-_.@]', '', u.strip()) for u in re.split(r'\s+and\s+|,\s*|;', users_text.strip()) if u.strip()]

                        if 'respectively' in ticket_body_norm.lower() and len(users) == len(groups):
                            for u, g in zip(users, groups):
                                if u in group_map:
                                    group_map[u] = g
                        else:
                            for u in users:
                                if u in group_map:
                                    group_map[u] = ','.join(groups)

    logger.info("Parsed via regex: server_name=%s, usernames=%s, group_map=%s", server_name, usernames, group_map)
    
    return server_name, usernames, group_map

def get_account_details_from_email(email):
    """
    Query DynamoDB to get account ID and allowed regions from customer email.
    """
    try:
        response = account_table.scan(
            FilterExpression="contains(CustomerEmailIds, :email)",
            ExpressionAttributeValues={":email": email}
        )
        
        logger.info("DynamoDB scan response: %s", response)
        
        for item in response.get("Items", []):
            # Parse regions - handle both comma-separated string and the region mapping
            regions_str = item.get("Regions", "")
            if regions_str:
                region_names = [r.strip() for r in regions_str.split(",") if r.strip()]
                # Convert region names to AWS region codes if needed
                aws_regions = []
                for region_name in region_names:
                    if region_name in region_map:
                        aws_regions.append(region_map[region_name])
                    else:
                        # If it's already an AWS region code, use it directly
                        aws_regions.append(region_name)
                
                return {
                    "AccountId": item["AccountId"],
                    "Regions": aws_regions
                }
        
        return None
        
    except Exception as e:
        logger.error("Error querying DynamoDB: %s", str(e))
        return None

def create_tsplus_users_from_ticket(ticket_body: str, from_email: str = None):
    """
    Parses ticket body, assumes role if needed, creates (or uses existing) SSM document,
    waits, and creates RDP users on the specified Windows server.
    Now includes S3 upload functionality for .connect files.
    """
    logger.info("Starting TSPlus user creation from ticket body.")

    server_name, usernames, group_map = parse_ticket_for_tsplus(ticket_body)
    logger.info("Parsed server_name=%s, usernames=%s", server_name, usernames)

    if from_email:
        actual_email = extract_email_address(from_email)
        logger.info("Original email: %s, Extracted: %s", from_email, actual_email)
        if not actual_email:
            raise Exception(f"Could not extract valid email from: {from_email}")
        
        account_info = get_account_details_from_email(actual_email)
        if not account_info:
            raise Exception(f"No account found for email: {actual_email}")

        account_id = account_info["AccountId"]
        aws_region = account_info["Regions"][0]
        logger.info("Found account info: AccountId=%s, Region=%s", account_id, aws_region)

        session = assume_role(account_id)
        ec2 = session.client("ec2", region_name=aws_region)
        ssm = session.client("ssm", region_name=aws_region)
    else:
        ec2 = boto3.client("ec2")
        ssm = boto3.client("ssm")

    # Create or use existing SSM document
    try:
        logger.info("Creating SSM document: %s", SSM_DOCUMENT_NAME)
        ssm.create_document(
            Content=SSM_DOCUMENT_CONTENT,
            Name=SSM_DOCUMENT_NAME,
            DocumentType="Command",
            DocumentFormat="YAML",
        )
        logger.info("SSM document '%s' created successfully.", SSM_DOCUMENT_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "DocumentAlreadyExists":
            logger.info("SSM document '%s' already exists. Using existing document.", SSM_DOCUMENT_NAME)
        else:
            logger.error("Failed to create SSM document: %s", e)
            raise

    logger.info("Waiting 5 seconds for document propagation...")
    time.sleep(5)

    # Find instance
    reservations = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': [server_name]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    ).get("Reservations", [])

    if not reservations or not reservations[0].get("Instances"):
        raise Exception(f"No running instance found with Name tag: {server_name}")

    instance = reservations[0]["Instances"][0]
    instance_id = instance["InstanceId"]
    private_ip = instance["PrivateIpAddress"]
    logger.info("Found instance: ID=%s, PrivateIP=%s", instance_id, private_ip)

    # Shared ENV values
    common_groups = os.getenv("CommonGroups", "")
    must_change = os.getenv("UserMustChange", "")
    can_change = os.getenv("UserCanChange", "")
    never_expires = os.getenv("PasswordNeverExpires", "")
    disabled = os.getenv("AccountDisabled", "")
    display_mode = os.getenv("DisplayMode", "")
    printer_action = os.getenv("PrinterAction", "")
    printer_scale = os.getenv("PrinterScale", "")
    
    # S3 config
    s3_bucket_name = os.getenv("S3_BUCKET_NAME")
    s3_prefix = os.getenv("S3_PREFIX", "tsplus-connect-files")
    if not s3_bucket_name:
        logger.warning("S3_BUCKET_NAME not set. .connect files will not be uploaded to S3.")
    else:
        logger.info("S3 configuration: Bucket=%s, Prefix=%s", s3_bucket_name, s3_prefix)

    # Prepare user data
    passwords = {user: generate_password() for user in usernames}
    users = []
    for user in usernames:
        users.append({
            "Username": user,
            "PasswordPlain": passwords[user],
            "ServerIP": private_ip,
            "UserMustChange": must_change,
            "UserCanChange": can_change,
            "PasswordNeverExpires": never_expires,
            "AccountDisabled": disabled,
            "CommonGroups": common_groups,
            "Groups": group_map.get(user, ""),
            "DisplayMode": display_mode,
            "PrinterAction": printer_action,
            "PrinterScale": printer_scale
        })

    users_json_b64 = base64.b64encode(json.dumps(users).encode("utf-8")).decode("utf-8")
    logger.info("Final SSM Payload (base64): %s", users_json_b64)

    ssm_parameters = {"UsersJsonBase64": [users_json_b64]}
    if s3_bucket_name:
        ssm_parameters["S3BucketName"] = [s3_bucket_name]
        ssm_parameters["S3Prefix"] = [s3_prefix]

    try:
        response = ssm.send_command(
            DocumentName=SSM_DOCUMENT_NAME,
            InstanceIds=[instance_id],
            Parameters=ssm_parameters,
        )
        command_id = response["Command"]["CommandId"]
        logger.info("SSM command sent successfully: CommandId=%s", command_id)
    except ClientError as e:
        logger.error("Failed to send SSM command: %s", e)
        raise

    # Wait for SSM command output
    try:
        stdout, stderr = wait_for_ssm_command_and_get_output(ssm, instance_id, command_id)
        logger.info("SSM command output fetched successfully.")
    except Exception as e:
        logger.error("Error waiting for SSM command output: %s", e, exc_info=True)
        stdout, stderr = None, None

    user_credentials = []
    for user in usernames:
        user_credentials.append({
            "Username": user,
            "Password": passwords[user],
            "Groups": group_map.get(user, ""),
            "ServerIP": private_ip
        })

    return {
        "statusCode": 200,
        "message": "TSPlus SSM command completed",
        "CommandId": command_id,
        "InstanceID": instance_id,
        "ServerName": server_name,
        "UserCredentials": user_credentials,
        "UsersCreated": users,
        "S3Configuration": {
            "BucketName": s3_bucket_name,
            "Prefix": s3_prefix,
            "Enabled": bool(s3_bucket_name)
        },
        "SSMOutput": stdout
    }

def wait_for_ssm_command_and_get_output(ssm_client, instance_id, command_id, max_attempts=30, delay=5):
    """
    Waits for the SSM command execution to finish and retrieves stdout/stderr.
    Retries on InvocationDoesNotExist since it often takes a few seconds for
    command invocations to propagate.
    """
    attempt = 0
    while attempt < max_attempts:
        try:
            response = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            status = response["Status"]
            logger.debug("Attempt %d: SSM command status: %s", attempt + 1, status)

            if status in ["Pending", "InProgress", "Delayed"]:
                time.sleep(delay)
                attempt += 1
            elif status in ["Success", "Cancelled", "Failed", "TimedOut", "Cancelling"]:
                stdout = response.get("StandardOutputContent", "")
                stderr = response.get("StandardErrorContent", "")
                logger.info("SSM command finished with status %s", status)
                return stdout, stderr
            else:
                logger.warning("Unknown SSM command status: %s", status)
                time.sleep(delay)
                attempt += 1

        except botocore.exceptions.ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "InvocationDoesNotExist":
                logger.debug("InvocationDoesNotExist: waiting for command invocation to register...")
                time.sleep(2)
                attempt += 1
            else:
                logger.error("Unexpected error waiting for SSM command: %s", e, exc_info=True)
                raise

    raise TimeoutError(f"SSM command did not complete within {max_attempts * delay} seconds")

def get_account_details_from_email(email):
    """
    Query DynamoDB to get account ID and allowed regions from customer email.
    """
    try:
        response = account_table.scan(
            FilterExpression="contains(CustomerEmailIds, :email)",
            ExpressionAttributeValues={":email": email}
        )
        
        logger.info("DynamoDB scan response: %s", response)
        
        for item in response.get("Items", []):
            # Parse regions - handle both comma-separated string and the region mapping
            regions_str = item.get("Regions", "")
            if regions_str:
                region_names = [r.strip() for r in regions_str.split(",") if r.strip()]
                # Convert region names to AWS region codes if needed
                aws_regions = []
                for region_name in region_names:
                    if region_name in region_map:
                        aws_regions.append(region_map[region_name])
                    else:
                        # If it's already an AWS region code, use it directly
                        aws_regions.append(region_name)
                
                return {
                    "AccountId": item["AccountId"],
                    "Regions": aws_regions
                }
        
        return None
        
    except Exception as e:
        logger.error("Error querying DynamoDB: %s", str(e))
        return None