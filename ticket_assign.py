import requests
import json
import logging
import boto3
import time
from constants import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN_TEAM, DevOps_TeamId, ENT_Linux_TeamId, SMB_Linux_TeamId, ENT_Windows_TeamId, SMB_Windows_TeamId, Database_TeamId, Uptime_TeamId, ORG_ID, REGION

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

    access_token = secrets.get("ACCESS_TOKEN_TEAM")
    expiry_time = secrets.get("ACCESS_TOKEN_TEAM_EXPIRY")
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
        "refresh_token": REFRESH_TOKEN_TEAM
    }

    try:
        response = requests.post(token_url, params=params)
        response.raise_for_status()
        new_token = response.json().get("access_token")

        if not new_token:
            raise Exception("No access token in Zoho response.")

        secrets["ACCESS_TOKEN_TEAM"] = new_token
        secrets["ACCESS_TOKEN_TEAM_EXPIRY"] = current_time + TOKEN_VALIDITY_SECONDS
        update_secret(SECRET_NAME, secrets)

        logger.info("New access token retrieved and cached.")
        return new_token

    except requests.RequestException as e:
        logger.error("Failed to retrieve access token: %s", str(e))
        raise Exception(f"Failed to retrieve access token: {str(e)}")


def assign_ticket_to_team(ticket_id, team_name):
    logger.info("Assigning ticket %s to team %s", ticket_id, team_name)

    team_map = {
        "DevOps Team": DevOps_TeamId,
        "Enterprise Linux Team": ENT_Linux_TeamId,
        "SMB Linux Team": SMB_Linux_TeamId,
        "Enterprise Windows Team": ENT_Windows_TeamId,
        "SMB Windows Team": SMB_Windows_TeamId,
        "Database Team": Database_TeamId,
        "Uptime Team": Uptime_TeamId,
    }

    team_id = team_map.get(team_name)
    if not team_id:
        logger.error("Unknown team name: %s", team_name)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unknown team name: {team_name}"})
        }

    try:
        access_token = get_access_token()
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
        "Content-Type": "application/json"
    }

    payload = {
        "teamId": team_id,
        "assigneeId": ""
    }

    try:
        response = requests.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info("Ticket successfully assigned to %s", team_name)
        return {
            "statusCode": response.status_code,
            "body": response.json()
        }
    except requests.RequestException as e:
        logger.error("Error assigning ticket: %s", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
