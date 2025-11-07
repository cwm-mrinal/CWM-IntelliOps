import requests
import re
import json
import logging
import time
import boto3
from constants import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ORG_ID, REGION

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
SECRET_NAME = "zoho-automation-secrets"
TOKEN_VALIDITY_SECONDS = 3600


def get_secret(secret_name=SECRET_NAME, region_name=REGION):
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def update_secret(secret_name, updated_data, region_name=REGION):
    client = boto3.client("secretsmanager", region_name=region_name)
    client.put_secret_value(
        SecretId=secret_name,
        SecretString=json.dumps(updated_data)
    )


def get_access_token():
    logger.info("Retrieving access token from Secrets Manager...")
    secrets = get_secret()

    access_token = secrets.get("ACCESS_TOKEN")
    expiry_time = secrets.get("ACCESS_TOKEN_EXPIRY")
    current_time = int(time.time())

    if access_token and expiry_time and current_time < expiry_time:
        logger.info("Using cached access token.")
        return access_token

    logger.info("Access token missing or expired. Requesting new token from Zoho...")

    token_url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }

    try:
        response = requests.post(token_url, params=params)
        response.raise_for_status()
        new_token = response.json().get("access_token")

        if not new_token:
            raise Exception("No access token in Zoho response.")

        secrets["ACCESS_TOKEN"] = new_token
        secrets["ACCESS_TOKEN_EXPIRY"] = current_time + TOKEN_VALIDITY_SECONDS
        update_secret(SECRET_NAME, secrets)

        logger.info("New access token retrieved and cached.")
        return new_token

    except requests.RequestException as e:
        logger.error("Failed to retrieve access token: %s", str(e))
        raise Exception(f"Failed to retrieve access token: {str(e)}")


def extract_email(address):
    match = re.search(r'[\w\.-]+@[\w\.-]+', address)
    return match.group(0) if match else address


def send_email_reply(ticket_id, from_emails, to_emails, cc_emails, reply_text):
    logger.info("Preparing to send email reply to ticket ID: %s", ticket_id)

    try:
        access_token = get_access_token()
    except Exception as e:
        logger.error("Access token error: %s", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Access token error: {str(e)}"})
        }

    # Input validation
    if not from_emails or len(from_emails) != 1:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "from_emails must contain exactly one email address."})
        }
    if not to_emails or not isinstance(to_emails, list):
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "to_emails must be a non-empty list."})
        }

    
    cc_emails = cc_emails or []

    support_email = "support@cloudworkmates.com"

    # Set CC to only aman.s
    cc_email = "aman.s@cloudworkmates.com"

    payload = {
        "channel": "EMAIL",
        "fromEmailAddress": support_email,
        "to": extract_email(to_emails[0]),
        "contentType": "html",
        "content": reply_text,
        "cc": cc_email
    }

    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}/sendReply"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
        "Content-Type": "application/json"
    }

    try:
        logger.info("Sending reply with payload: %s", json.dumps(payload))
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        logger.info("Email reply sent successfully. Response: %s", response.text)
        return {
            "statusCode": response.status_code,
            "body": response.json()
        }

    except requests.RequestException as e:
        error_message = str(e)
        response_body = ""

        if e.response is not None:
            response_body = e.response.text
            logger.error("Error response status: %s", e.response.status_code)
            logger.error("Error response body: %s", response_body)

        logger.error("Error sending email reply: %s", error_message)

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": error_message,
                "response": response_body
            })
        }
