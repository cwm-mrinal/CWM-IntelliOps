import boto3
import re
import json
import time
from botocore.exceptions import ClientError
import logging
from cross_account_role import assume_role
from constants import ACCOUNT_TABLE_NAME
from constants import REGION, MODEL_ID

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region_map = {
    "Mumbai": "ap-south-1", "Hyderabad": "ap-south-2", "Osaka": "ap-northeast-3", "Seoul": "ap-northeast-2",
    "N. Virginia": "us-east-1", "Ohio": "us-east-2", "N. California": "us-west-1", "Oregon": "us-west-2",
    "Singapore": "ap-southeast-1", "Sydney": "ap-southeast-2", "Tokyo": "ap-northeast-1", "Canada": "ca-central-1",
    "Frankfurt": "eu-central-1", "Ireland": "eu-west-1", "London": "eu-west-2", "Paris": "eu-west-3",
    "Stockholm": "eu-north-1", "São Paulo": "sa-east-1"
}

session = boto3.Session(region_name=REGION)
bedrock_runtime = session.client("bedrock-runtime")

SG_SYSTEM_PROMPT = (
    "You are an expert AWS cloud assistant. Extract exactly these seven fields from the user's request to modify a security group:\n\n"
    
    "1) **Ports**: A list of integer ports (e.g., [22, 80]).\n"
    "2) **Direction**: 'inbound' or 'outbound' (accept synonyms like ingress/egress).\n"
    "3) **SecurityGroupId**: The security group ID (e.g., sg-xxxxxxxxxxxxxxxxx).\n"
    "4) **SecurityGroupName**: The name of the security group if provided.\n"
    "5) **CIDR**: The IP range in CIDR notation.\n"
    "6) **Protocol**: Protocol like 'tcp', 'udp', or 'icmp'.\n"
    "7) **Revoke**: Boolean true/false indicating whether to remove/revoke the rule.\n\n"
    
    "## OUTPUT FORMAT:\n"
    "{\n"
    '  "Ports": [22, 443],\n'
    '  "Direction": "inbound",\n'
    '  "SecurityGroupId": "sg-xxxxxxxxxxxxxxxxx",\n'
    '  "SecurityGroupName": "my-sg",\n'
    '  "CIDR": "0.0.0.0/0",\n'
    '  "Protocol": "tcp",\n'
    '  "Revoke": false\n'
    "}\n\n"
    
    "## RULES:\n"
    "- If ports are not specified, return Ports as [null].\n"
    "- If CIDR not specified, default to '0.0.0.0/0' for IPv4 or '::/0' for IPv6.\n"
    "- If SecurityGroupId not found, use empty string.\n"
    "- Always return valid JSON with all fields.\n\n"
    
    "## MISSING INFORMATION HANDLING:\n"
    "If any of the required fields (Ports, Direction, SecurityGroupId, CIDR, Protocol, or Revoke) cannot be determined, respond with ONLY this question (no JSON):\n\n"
    "\"Can you please provide the missing information? Specifically, I need the ports, direction (inbound/outbound), security group ID, CIDR, protocol, or whether to revoke the rule.\"\n\n"
    
    "## VALIDATION CHECKLIST:\n"
    "Before responding, verify:\n"
    "✓ JSON syntax is valid\n"
    "✓ All seven fields (Ports, Direction, SecurityGroupId, SecurityGroupName, CIDR, Protocol, Revoke) are included\n"
    "✓ No extra text outside the JSON block or question prompt"
)

def extract_email(raw_email):
    match = re.search(r'[\w\.-]+@[\w\.-]+', raw_email)
    return match.group(0) if match else raw_email

def get_account_details_from_email(email):
    response = account_table.scan(
        FilterExpression="contains(CustomerEmailIds, :email)",
        ExpressionAttributeValues={":email": email}
    )
    for item in response.get("Items", []):
        return {
            "AccountId": item["AccountId"],
            "Regions": [r.strip() for r in item["Regions"].split(",") if r.strip()]
        }
    return None

def extract_sg_details(message):
    """
    Extracts Security Group modification details from a free-form message.
    Tries Claude first via Bedrock, then falls back to regex-based parsing.
    Returns dict with Ports, Direction, SecurityGroupId, SecurityGroupName, CIDR, Protocol, Revoke.
    """

    inference_profile_arn = MODEL_ID
    max_retries = 3
    retry_delay_seconds = 2
    max_tokens = 2000

    logger.info("Starting SG extraction with Claude Sonnet via Bedrock for message: %s", message)

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": f"{SG_SYSTEM_PROMPT}\n\nUser Request:\n{message}"
            }
        ]
    }

    # Try Claude first
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

            # Validate required fields exist
            if "Ports" in parsed and "Direction" in parsed:
                logger.info("Successfully parsed via Claude: %s", json.dumps(parsed, indent=2))
                return parsed
            else:
                raise ValueError("Claude returned incomplete SG details")

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

    # Fallback: regex-based extraction
    logger.info("Fallback: parsing SG details with regex.")

    msg_lower = message.lower().replace("=\n", "").replace("=\r\n", "")

    # Ports
    port_matches = re.findall(r'\bport[s]?\s*([\d, ]+)', msg_lower)
    ports = set()
    for match in port_matches:
        ports.update([int(p.strip()) for p in match.split(',') if p.strip().isdigit()])
    ports = list(ports) or [None]

    # Direction
    direction_match = re.search(r'\b(inbound|outbound|ingress|egress)\b', msg_lower)
    direction = "inbound"
    if direction_match:
        direction = "inbound" if direction_match.group(1) in ["inbound", "ingress"] else "outbound"

    # SecurityGroupId and SecurityGroupName
    sg_id_match = re.search(r'\b(sg-[0-9a-f]{17})\b', msg_lower)
    sg_id = sg_id_match.group(1) if sg_id_match else ""

    sg_name_match = re.search(r'(?:security group(?: named| name)?|sg(?: group)?)[\s:]*([\w\-]+)', msg_lower)
    sg_name = sg_name_match.group(1) if (not sg_id and sg_name_match) else ""

    # CIDR
    cidr_match = re.search(r'((?:\d{1,3}\.){3}\d{1,3}/\d{1,2}|::/\d{1,3}|[a-fA-F0-9:]+/\d{1,3})', msg_lower)
    cidr_ip = cidr_match.group(1) if cidr_match else ("::/0" if ":" in msg_lower else "0.0.0.0/0")

    # Revoke
    revoke = bool(re.search(r'\b(remove|delete|revoke|block)\b', msg_lower))

    # Protocol
    protocol = "icmp" if re.search(r'\b(ping|icmp)\b', msg_lower) else "tcp"

    result = {
        "Ports": ports,
        "Direction": direction,
        "SecurityGroupId": sg_id,
        "SecurityGroupName": sg_name,
        "CIDR": cidr_ip,
        "Protocol": protocol,
        "Revoke": revoke
    }

    logger.info("Fallback extraction completed with result: %s", json.dumps(result, indent=2))
    return result

def find_security_group_id(ec2_client, group_name):
    try:
        response = ec2_client.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [group_name]}]
        )
        if response["SecurityGroups"]:
            return response["SecurityGroups"][0]["GroupId"]
    except Exception as e:
        print(f"Error fetching SG by name: {e}")
    return None

def rule_exists(existing_permissions, port, protocol, cidr):
    for perm in existing_permissions:
        if perm["IpProtocol"] != protocol:
            continue
        from_port = perm.get("FromPort", -1)
        to_port = perm.get("ToPort", -1)
        ip_ranges = perm.get("IpRanges", [])
        ipv6_ranges = perm.get("Ipv6Ranges", [])
        if from_port == port and to_port == port:
            for ip_range in ip_ranges:
                if ip_range.get("CidrIp") == cidr:
                    return True
            for ipv6_range in ipv6_ranges:
                if ipv6_range.get("CidrIpv6") == cidr:
                    return True
    return False

def update_security_group(ec2, sg_id, details):
    existing_permissions = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]
    existing_permissions = existing_permissions["IpPermissions"] if details["Direction"] == "inbound" else existing_permissions["IpPermissionsEgress"]

    for port in details["Ports"]:
        ip_permission = {
            "IpProtocol": details["Protocol"],
            "FromPort": port if port is not None else -1,
            "ToPort": port if port is not None else -1,
            "IpRanges": [{"CidrIp": details["CIDR"]}] if ":" not in details["CIDR"] else [],
            "Ipv6Ranges": [{"CidrIpv6": details["CIDR"]}] if ":" in details["CIDR"] else [],
        }

        exists = rule_exists(existing_permissions, port, details["Protocol"], details["CIDR"])
        if details["Revoke"]:
            try:
                if details["Direction"] == "inbound":
                    ec2.revoke_security_group_ingress(GroupId=sg_id, IpPermissions=[ip_permission])
                else:
                    ec2.revoke_security_group_egress(GroupId=sg_id, IpPermissions=[ip_permission])
            except Exception as e:
                print(f"Error revoking rule: {e}")
        elif not exists:
            if details["Direction"] == "inbound":
                ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[ip_permission])
            else:
                ec2.authorize_security_group_egress(GroupId=sg_id, IpPermissions=[ip_permission])

def lambda_handler(event, context):
    message = event.get("message", "")
    body = event.get("body", {})
    from_emails = body.get("fromEmail", [])

    if not from_emails:
        return {"statusCode": 400, "status": "error", "message": "Missing sender email."}

    cleaned_emails = [extract_email(email) for email in from_emails]

    for clean_email in cleaned_emails:
        account_data = get_account_details_from_email(clean_email)
        if not account_data:
            continue

        account_id = account_data["AccountId"]
        regions = account_data["Regions"]
        extracted = extract_sg_details(message)

        if not extracted["SecurityGroupId"] and not extracted["SecurityGroupName"]:
            return {
                "statusCode": 400,
                "status": "error",
                "message": "Security Group name or ID not provided.",
                "details": extracted
            }

        for region in regions:
            try:
                aws_region = region_map.get(region)
                if not aws_region:
                    continue

                session = assume_role(account_id)
                ec2 = session.client("ec2", region_name=aws_region)

                sg_id = extracted["SecurityGroupId"]
                if not sg_id and extracted["SecurityGroupName"]:
                    sg_id = find_security_group_id(ec2, extracted["SecurityGroupName"])
                    if not sg_id:
                        continue

                update_security_group(ec2, sg_id, extracted)

                return {
                    "statusCode": 200,
                    "status": "success",
                    "message": f"Security group updated in {region}",
                    "details": {
                        "SecurityGroupId": sg_id,
                        "Region": region,
                        "AccountId": account_id,
                        **extracted
                    }
                }

            except Exception as e:
                return {
                    "statusCode": 500,
                    "status": "error",
                    "message": f"Error updating SG in {region}",
                    "error": str(e),
                    "region": region
                }

    return {
        "statusCode": 404,
        "status": "error",
        "message": "No matching account found.",
        "emails": cleaned_emails
    }