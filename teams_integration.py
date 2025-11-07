import logging
import json
import boto3
import re
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr
from send_teams_webhook import send_to_teams_webhook, send_basic_teams_webhook
from rapidfuzz import fuzz
from constants import ACCOUNT_TABLE_NAME , TEAM_TABLE_NAME

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)
team_table = dynamodb.Table(TEAM_TABLE_NAME)

SUPPORT_EMAILS = [
    "support@cloudworkmates.com",
    "support@2demo2cloudworkmates.zohodesk.in"
]

def similarity(a, b):
    return fuzz.token_sort_ratio(a.lower(), b.lower()) / 100.0

def get_timestamp():
    return datetime.now(timezone.utc).isoformat()

def clean_email_address(email):
    """
    Extracts just the email address from formats like '"Name" <email@domain.com>'
    """
    match = re.search(r'[\w\.-]+@[\w\.-]+', email)
    return match.group(0).lower() if match else email.lower()

def send_alarm_to_uptime_team(team_name, subject, ticket_id, reply_text, from_email=None, to_emails=None, cc_emails=None):
    try:
        logger.info(f"Fetching Teams webhook for team: {team_name}")
        response = team_table.scan(FilterExpression=Attr("TeamName").eq(team_name))
        items = response.get("Items", [])
        if not items:
            raise ValueError(f"Team '{team_name}' not found in CWM-Team-Details-Table")

        webhook_url = items[0].get("TeamsURL")
        if not webhook_url:
            raise ValueError(f"No WebhookUrl found for team '{team_name}'")

        return send_basic_teams_webhook(
            webhook_url,
            subject,
            reply_text,
            team_name,
            ticket_id
        )

    except Exception as e:
        logger.error("Error sending alarm to Uptime Team: %s", str(e), exc_info=True)
        raise

def extract_emails_from_string(s):
    # Split on commas, then clean each email string
    parts = [p.strip() for p in s.split(",") if p.strip()]
    emails = [clean_email_address(p) for p in parts]
    return emails 

def handle_custom(email, subject, body, reply, ticket_id, from_email=None, to_emails=None, cc_emails=None, image_analysis=None, zoho_account_id=None):
    try:
        # Normalize emails
        if isinstance(from_email, list):
            from_email = from_email[0] if from_email else None
        if isinstance(from_email, str):
            from_email = clean_email_address(from_email)
        else:
            from_email = None

        if isinstance(to_emails, list) and len(to_emails) == 1 and "," in to_emails[0]:
            to_emails = extract_emails_from_string(to_emails[0])
        else:
            to_emails = [clean_email_address(e) for e in (to_emails or [])]

        if isinstance(cc_emails, list) and len(cc_emails) == 1 and "," in cc_emails[0]:
            cc_emails = extract_emails_from_string(cc_emails[0])
        else:
            cc_emails = [clean_email_address(e) for e in (cc_emails or [])]

        logger.info(f"Parsed email fields - FROM: {from_email}, TO: {to_emails}, CC: {cc_emails}")

        # Case 1: Support email bypass
        if all(email in SUPPORT_EMAILS for email in to_emails):
            logger.info("Support email detected in toEmails; skipping validation.")
            send_alarm_to_uptime_team("Uptime Team", subject, ticket_id, reply)
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "sent",
                    "message": "Notification sent to Teams (support email bypass).",
                    "teamName": "Uptime Team",
                    "timestamp": get_timestamp()
                }),
                "headers": {"Content-Type": "application/json"}
            }

        # Step 0: Try Zoho Account ID lookup if provided
        items = []
        if zoho_account_id:
            logger.info(f"Looking up account using Zoho_Account_Id: {zoho_account_id}")
            response = account_table.scan(
                FilterExpression=Attr("Zoho_Account_Id").eq(zoho_account_id)
            )
            items = response.get("Items", [])

            if items:
                logger.info(f"Found {len(items)} account(s) for Zoho_Account_Id: {zoho_account_id}")
            else:
                logger.warning(f"No account found for Zoho_Account_Id: {zoho_account_id}, falling back to from_email logic.")

        # Step 1: If Zoho lookup failed or not provided, fall back to from_email validation
        if not items:
            if not from_email:
                logger.warning("No from_email provided, and Zoho_Account_Id lookup failed.")
                return {
                    "statusCode": 403,
                    "body": json.dumps({
                        "status": "denied",
                        "message": "Account validation failed. Contact support.",
                        "reason": "Missing from_email and invalid Zoho_Account_Id",
                        "timestamp": get_timestamp()
                    }),
                    "headers": {"Content-Type": "application/json"}
                }

            response = account_table.scan(FilterExpression=Attr("CustomerEmailIds").contains(from_email))
            items = response.get("Items", [])

            # Step 2: Fuzzy match if no exact match
            if not items:
                logger.warning(f"No exact match for from_email: {from_email}, trying fuzzy match.")
                response = account_table.scan()
                for item in response.get("Items", []):
                    customer_emails_raw = item.get("CustomerEmailIds", "")
                    customer_emails = [email.strip().lower() for email in customer_emails_raw.split(",") if email.strip()]
                    for ce in customer_emails:
                        if from_email in ce or ce in from_email or similarity(ce, from_email) > 0.8:
                            items.append(item)
                            break

        # Step 3: Deny if no match
        if not items:
            logger.warning(f"No match found for Zoho_Account_Id or from_email: {from_email}")
            return {
                "statusCode": 403,
                "body": json.dumps({
                    "status": "denied",
                    "message": "Account validation failed. Contact support.",
                    "reason": "No matching account found",
                    "from_email": from_email,
                    "timestamp": get_timestamp()
                }),
                "headers": {"Content-Type": "application/json"}
            }

        # Step 4: Score matching teams
        scored_teams = []
        for item in items:
            team_name = item.get("TeamName")
            team_emails = item.get("TeamEmailIds", [])
            if not team_name or not team_emails:
                continue

            score = 0
            for email in to_emails:
                if email in SUPPORT_EMAILS:
                    continue
                for te in team_emails:
                    if email == te:
                        score += 10
                    elif email in te or te in email:
                        score += 5
                    elif similarity(email, te) > 0.8:
                        score += 3
                    elif re.search(rf"{re.escape(te.split('@')[0])}", email):
                        score += 2
                    elif email.split('@')[-1] == te.split('@')[-1]:
                        score += 1

            if score > 0:
                scored_teams.append((score, team_name, item))

        # Step 5: No team found
        if not scored_teams:
            logger.warning("No matching team found after scoring.")
            return {
                "statusCode": 403,
                "body": json.dumps({
                    "status": "denied",
                    "message": "Account validation failed. Contact support.",
                    "reason": "No matching team found",
                    "timestamp": get_timestamp()
                }),
                "headers": {"Content-Type": "application/json"}
            }

        # Step 6: Use best scoring team
        best_score, best_team_name, best_account = max(scored_teams, key=lambda x: x[0])
        team_response = team_table.get_item(Key={"TeamName": best_team_name})
        team_item = team_response.get("Item")

        if not team_item or not team_item.get("TeamsURL"):
            logger.error(f"TeamsURL missing for team: {best_team_name}")
            return {
                "statusCode": 500,
                "body": json.dumps({
                    "error": "TeamsURL not found for the team.",
                    "teamName": best_team_name,
                    "timestamp": get_timestamp()
                }),
                "headers": {"Content-Type": "application/json"}
            }

        # Step 7: Send to Teams
        send_to_teams_webhook(
            team_item["TeamsURL"],
            subject,
            body,
            reply,
            best_account.get("AccountId"),
            best_account.get("AccountName"),
            best_team_name,
            ticket_id,
            best_account.get("TeamId"),
            image_analysis=image_analysis
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "sent",
                "message": "Notification sent to Teams.",
                "teamName": best_team_name,
                "accountId": best_account.get("AccountId"),
                "score": best_score,
                "image_analysis": image_analysis,
                "timestamp": get_timestamp()
            }),
            "headers": {"Content-Type": "application/json"}
        }

    except Exception as e:
        logger.error("Exception in processing: %s", str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Internal server error during notification.",
                "image_analysis": image_analysis,
                "exception": str(e),
                "timestamp": get_timestamp()
            }),
            "headers": {"Content-Type": "application/json"}
        }