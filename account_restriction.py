import re
import json
import boto3
import logging
from botocore.exceptions import ClientError
from constants import ACCOUNT_RESTRICTION_TABLE_NAME, REGION
from ticket_assign import assign_ticket_to_team
from ticket_status import update_ticket_status
from teams_integration import handle_custom, send_alarm_to_uptime_team

# Logger setup
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB Table Resource
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(ACCOUNT_RESTRICTION_TABLE_NAME)

def extract_account_id_from_message(decoded_message: str) -> str | None:
    """
    Extract 12-digit AWS AccountId:
    - Priority 1: text patterns like 'AWS Account : 123456789012'
    - Priority 2: if not found, look for 'accountId' in JSON messages.
    """
    # Priority 1: regex pattern
    match = re.search(r"AWS\s+Account\s*:\s*(\d{12})", decoded_message, re.IGNORECASE)
    if match:
        account_id = match.group(1)
        logger.info(f"Extracted AWS AccountId from text: {account_id}")
        return account_id

    # Priority 2: JSON parsing
    try:
        message_json = json.loads(decoded_message)
        if isinstance(message_json, dict) and "accountId" in message_json:
            account_id = message_json["accountId"]
            if isinstance(account_id, str) and re.fullmatch(r"\d{12}", account_id):
                logger.info(f"Extracted AWS AccountId from JSON: {account_id}")
                return account_id
    except json.JSONDecodeError:
        pass  # Not JSON or invalid JSON, nothing found

    logger.warning("No valid AWS AccountId found in ticket body. Will treat as client.")
    return None

def is_account_supported(account_id: str) -> bool:
    """
    Check if the AWS AccountId is present in the DynamoDB restriction table.
    """
    try:
        response = table.get_item(Key={"AccountId": account_id})
        exists = "Item" in response
        logger.info(f"AccountId {account_id} is {'supported' if exists else 'not supported'}")
        return exists
    except ClientError as e:
        logger.error(f"DynamoDB error for AccountId {account_id}: {e.response['Error']['Message']}")
        return False

def handle_account_restriction_from_body(
    ticket_id: str,
    ticket_subject: str,
    ticket_body_message: str,
    from_emails: list[str],
    to_emails: list[str],
    cc_emails: list[str]
) -> dict:
    """
    Determines if a ticket's account is supported. If unsupported, route to Uptime team.
    If no account is found, continue with client flow.
    Returns a dictionary containing:
        - response (optional HTTP response)
        - account_found (bool)
    """
    account_id = extract_account_id_from_message(ticket_body_message)

    # No account ID found, treat as Client
    if not account_id:
        logger.warning("No AccountId found — continuing with Client flow.")
        return {
            "response": None,
            "account_found": False
        }

    # Account ID found but not supported
    if not is_account_supported(account_id):
        logger.warning(f"Access denied for unsupported AccountId: {account_id}")

        assign_ticket_to_team(str(ticket_id), "Uptime Team")
        update_ticket_status(str(ticket_id))

        uptime_resp = send_alarm_to_uptime_team(
            team_name="Uptime Team",
            subject=ticket_subject,
            ticket_id=str(ticket_id),
            reply_text="",
            from_email=from_emails,
            to_emails=to_emails,
            cc_emails=cc_emails,
        )
        logger.info("Uptime Team notification response: %s", uptime_resp)

        return {
            "response": {
                "statusCode": 403,
                "body": f"AccountId {account_id} is not supported. Ticket has been routed to Uptime Team."
            },
            "account_found": True
        }

    # Account is valid and supported
    return {
        "response": None,
        "account_found": True
    }
