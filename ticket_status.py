import requests
import json
import logging
import time
import boto3
from constants import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ORG_ID, REGION

# Logger configuration
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

        secrets["ACCESS_TOKEN"] = new_token
        secrets["ACCESS_TOKEN_EXPIRY"] = current_time + TOKEN_VALIDITY_SECONDS
        update_secret(SECRET_NAME, secrets)

        logger.info("New access token retrieved and cached.")
        return new_token

    except requests.RequestException as e:
        logger.error("Failed to retrieve access token: %s", str(e))
        raise Exception(f"Failed to retrieve access token: {str(e)}")

def update_ticket_status(ticket_id):
    """
    Updates the status of a Zoho Desk ticket to 'Assigned'.
    """
    if not ticket_id:
        logger.warning("Missing 'ticket_id'.")
        return {"error": "Missing ticket_id"}

    try:
        access_token = get_access_token()
        logger.info("Access token retrieved successfully.")
    except Exception as e:
        return {"error": str(e)}

    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
        "Content-Type": "application/json"
    }
    payload = {
        "status": "Assigned"
    }

    logger.info("Updating ticket ID %s to status 'Assigned'...", ticket_id)

    try:
        response = requests.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info("Ticket status updated successfully.")
        return response.json()

    except requests.RequestException as e:
        logger.error("Error updating ticket status: %s", str(e))
        return {"error": str(e)}
