import boto3
import json
import os

def get_secret(secret_name, region_name="ap-south-1"):
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])

# Load secrets
secrets = get_secret("zoho-automation-secrets")

AGENT_ARNS = {
    "cost_optimization": secrets.get("AGENT_ARNS_cost_optimization"),
    "security": secrets.get("AGENT_ARNS_security"),
    "alarm": secrets.get("AGENT_ARNS_alarm"),
    "custom": secrets.get("AGENT_ARNS_custom"),
    "os": secrets.get("AGENT_ARNS_os-infra"),
    "main": secrets.get("AGENT_ARNS_main"),
}

AGENT_ALIASES = {
    "main": secrets.get("AGENT_ALIASES_main"),
    "cost_optimization": secrets.get("AGENT_ALIASES_cost_optimization"),
    "security": secrets.get("AGENT_ALIASES_security"),
    "alarm": secrets.get("AGENT_ALIASES_alarm"),
    "os": secrets.get("AGENT_ALIASES_os-infra"),
    "custom": secrets.get("AGENT_ALIASES_custom"),
}
DLQ_URL = secrets.get("DLQ_URL")
LAMBDA_HANDLER_ARN = secrets.get("LAMBDA_HANDLER_ARN")
CLIENT_ID = secrets.get("CLIENT_ID")
CLIENT_SECRET = secrets.get("CLIENT_SECRET")
REFRESH_TOKEN = secrets.get("REFRESH_TOKEN")
REFRESH_TOKEN_TEAM = secrets.get("REFRESH_TOKEN_TEAM")
DevOps_TeamId = secrets.get("DevOps_TeamId")
ENT_Linux_TeamId = secrets.get("ENT_Linux_TeamId")
SMB_Linux_TeamId = secrets.get("SMB_Linux_TeamId")
ENT_Windows_TeamId = secrets.get("ENT_Windows_TeamId")
SMB_Windows_TeamId = secrets.get("SMB_Windows_TeamId")
Database_TeamId = secrets.get("Database_TeamId")
Uptime_TeamId = secrets.get("Uptime_TeamId")
ORG_ID = secrets.get("ORG_ID")
REGION = secrets.get("REGION")
MODEL_ID = secrets.get("MODEL_ID")
ACCOUNT_TABLE_NAME = secrets.get("ACCOUNT_TABLE_NAME")
TEAM_TABLE_NAME = secrets.get("TEAM_TABLE_NAME")
EMBED_MODEL_ID = secrets.get("EMBED_MODEL_ID")
EMBED_TABLE_NAME = secrets.get("EMBED_TABLE_NAME")
ACCOUNT_RESTRICTION_TABLE_NAME = secrets.get("ACCOUNT_RESTRICTION_TABLE_NAME")