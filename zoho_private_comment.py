import requests
import json
import logging
import time
import boto3
from constants import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ORG_ID

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
SECRET_NAME = "zoho-automation-secrets"
REGION = "ap-south-1"
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
    """
    Retrieve cached Zoho access token or fetch a new one if expired or missing.
    """
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

        # Update token and expiry in Secrets Manager
        secrets["ACCESS_TOKEN"] = new_token
        secrets["ACCESS_TOKEN_EXPIRY"] = current_time + TOKEN_VALIDITY_SECONDS
        update_secret(SECRET_NAME, secrets)

        logger.info("New access token retrieved and cached.")
        return new_token

    except requests.RequestException as e:
        logger.error("Failed to retrieve access token: %s", str(e))
        raise Exception(f"Failed to retrieve access token: {str(e)}")

def lambda_handler(event, context=None):
    """
    AWS Lambda handler to post a private comment to a Zoho Desk ticket.
    Expects 'ticketId' and 'reply' in the event input.
    """
    logger.info("Lambda triggered with event: %s", json.dumps(event))

    ticket_id = event.get("ticketId")
    comment_text = event.get("reply")

    if not ticket_id or not comment_text:
        logger.warning("Missing 'ticketId' or 'reply'.")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing 'ticketId' or 'reply' in event"})
        }

    try:
        access_token = get_access_token()
        logger.info("Access token retrieved successfully: %s",access_token)
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}/comments"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
        "Content-Type": "application/json"
    }
    payload = {
        "content": comment_text
    }

    logger.info("Posting comment to ticket ID: %s", ticket_id)

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info("Comment successfully posted.")

        return {
            "statusCode": response.status_code,
            "body": response.json()
        }
    except requests.RequestException as e:
        logger.error("Error posting comment: %s", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
