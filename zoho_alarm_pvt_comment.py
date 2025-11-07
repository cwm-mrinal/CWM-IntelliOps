import requests
import json
import logging
import time
import boto3
import base64
import mimetypes

from typing import Optional
from requests.adapters import HTTPAdapter, Retry

from constants import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ORG_ID, REGION

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SECRET_NAME = "zoho-automation-secrets"
TOKEN_VALIDITY_SECONDS = 3600
TOKEN_BUFFER_SECONDS = 5

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.doc', '.docx', '.xlsx'}

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)


def get_secret(secret_name: str = SECRET_NAME, region_name: str = REGION) -> dict:
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def update_secret(secret_name: str, updated_data: dict, region_name: str = REGION) -> None:
    client = boto3.client("secretsmanager", region_name=region_name)
    client.put_secret_value(
        SecretId=secret_name,
        SecretString=json.dumps(updated_data)
    )


def get_access_token() -> str:
    logger.info("Retrieving access token from Secrets Manager...")
    secrets = get_secret()

    access_token = secrets.get("ACCESS_TOKEN")
    expiry_time = secrets.get("ACCESS_TOKEN_EXPIRY")
    current_time = int(time.time())

    if access_token and expiry_time and current_time < (expiry_time - TOKEN_BUFFER_SECONDS):
        logger.info("Using cached access token.")
        return access_token

    logger.info("Access token expired or missing. Refreshing from Zoho...")

    token_url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }

    response = session.post(token_url, params=params)
    if response.status_code != 200:
        logger.error(f"Failed to refresh token. Status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()

    new_token = response.json().get("access_token")
    if not new_token:
        raise Exception("No access token received in Zoho response.")

    secrets["ACCESS_TOKEN"] = new_token
    secrets["ACCESS_TOKEN_EXPIRY"] = current_time + TOKEN_VALIDITY_SECONDS
    update_secret(SECRET_NAME, secrets)

    logger.info("Access token refreshed and cached.")
    return new_token


def is_supported_file_type(filename: str) -> bool:
    extension = f".{filename.lower().rpartition('.')[-1]}"
    return extension in SUPPORTED_EXTENSIONS


def upload_attachment(ticket_id: str, image_bytes: bytes, image_filename: str) -> str:
    """
    Upload an attachment to the Zoho ticket and return the attachment ID.
    """
    access_token = get_access_token()
    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}/attachments"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
    }

    files = {
        'file': (image_filename, image_bytes, mimetypes.guess_type(image_filename)[0] or 'application/octet-stream')
    }

    logger.info(f"Uploading attachment {image_filename} to ticket {ticket_id}...")

    response = session.post(url, headers=headers, files=files)
    if response.status_code not in (200, 201):
        logger.error(f"Failed to upload attachment. Status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()

    attachment_info = response.json()

    # Handle both possible response formats from Zoho API
    if 'data' in attachment_info and isinstance(attachment_info['data'], list) and len(attachment_info['data']) > 0:
        attachment_id = attachment_info['data'][0].get('id')
    elif 'id' in attachment_info:
        attachment_id = attachment_info['id']
    else:
        raise Exception("Attachment ID not found in upload response.")

    logger.info(f"Attachment uploaded successfully with ID {attachment_id}")
    return str(attachment_id)


def add_private_comment_with_attachment(ticket_id: str, comment_text: str, image_base64: str, image_filename: str) -> dict:
    if not ticket_id or not image_base64 or not image_filename or not comment_text:
        raise ValueError("Missing required parameters: ticket_id, image_base64, image_filename, comment_text")

    if not is_supported_file_type(image_filename):
        raise ValueError(f"Unsupported file type for attachment: {image_filename}")

    # Decode base64 image bytes
    image_bytes = base64.b64decode(image_base64)

    # Step 1: Upload attachment and get attachment ID
    attachment_id = upload_attachment(ticket_id, image_bytes, image_filename)

    # Step 2: Post private comment referencing the attachment ID
    access_token = get_access_token()
    url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}/comments"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "orgId": ORG_ID,
        "Content-Type": "application/json"
    }

    comment_payload = {
        "isPublic": False,
        "attachmentIds": [attachment_id],
        "contentType": "html",
        "content": comment_text
    }

    logger.info(f"Posting private comment with attachment to ticket {ticket_id}...")

    response = session.post(url, headers=headers, json=comment_payload)
    if response.status_code not in (200, 201):
        logger.error(f"Failed to post comment. Status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()

    logger.info(f"Private comment posted successfully to ticket {ticket_id}")
    return response.json()
