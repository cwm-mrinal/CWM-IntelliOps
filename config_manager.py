"""
Centralized configuration management for email addresses and sensitive data.
Replaces hardcoded values with environment variables and Secrets Manager.
"""
import os
import json
import boto3
import logging
from typing import Dict, List, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# Secrets Manager client
secrets_client = boto3.client('secretsmanager', region_name=os.getenv('AWS_REGION', 'ap-south-1'))

@lru_cache(maxsize=1)
def get_email_config() -> Dict[str, List[str]]:
    """
    Get email configuration from environment variables or Secrets Manager.
    Falls back to defaults only in development.
    """
    try:
        # Try to get from Secrets Manager first
        secret_name = os.getenv('EMAIL_CONFIG_SECRET', 'zoho-automation-email-config')
        response = secrets_client.get_secret_value(SecretId=secret_name)
        config = json.loads(response['SecretString'])
        logger.info("Email configuration loaded from Secrets Manager")
        return config
    except secrets_client.exceptions.ResourceNotFoundException:
        logger.warning("Email config secret not found, using environment variables")
        
        # Fallback to environment variables
        config = {
            'cc_emails': os.getenv('CC_EMAILS', '').split(','),
            'support_emails': os.getenv('SUPPORT_EMAILS', 'support@cloudworkmates.com').split(','),
            'escalation_emails': os.getenv('ESCALATION_EMAILS', '').split(','),
            'notification_emails': os.getenv('NOTIFICATION_EMAILS', '').split(',')
        }
        
        # Filter out empty strings
        config = {k: [email.strip() for email in v if email.strip()] for k, v in config.items()}
        
        if not any(config.values()):
            raise ValueError("No email configuration found in Secrets Manager or environment variables")
        
        return config
    except Exception as e:
        logger.error(f"Failed to load email configuration: {e}")
        raise

def get_cc_emails() -> List[str]:
    """Get CC email addresses for ticket responses"""
    return get_email_config().get('cc_emails', [])

def get_support_emails() -> List[str]:
    """Get support team email addresses"""
    return get_email_config().get('support_emails', ['support@cloudworkmates.com'])

def get_escalation_emails() -> List[str]:
    """Get escalation email addresses"""
    return get_email_config().get('escalation_emails', [])

def get_notification_emails() -> List[str]:
    """Get notification email addresses"""
    return get_email_config().get('notification_emails', [])

# Region mapping - centralized
REGION_MAP = {
    "Mumbai": "ap-south-1",
    "Hyderabad": "ap-south-2",
    "Osaka": "ap-northeast-3",
    "Seoul": "ap-northeast-2",
    "N. Virginia": "us-east-1",
    "Ohio": "us-east-2",
    "N. California": "us-west-1",
    "Oregon": "us-west-2",
    "Singapore": "ap-southeast-1",
    "Sydney": "ap-southeast-2",
    "Tokyo": "ap-northeast-1",
    "Canada": "ca-central-1",
    "Frankfurt": "eu-central-1",
    "Ireland": "eu-west-1",
    "London": "eu-west-2",
    "Paris": "eu-west-3",
    "Stockholm": "eu-north-1",
    "São Paulo": "sa-east-1"
}

def get_aws_region(region_name: str) -> Optional[str]:
    """Convert friendly region name to AWS region code"""
    return REGION_MAP.get(region_name, region_name if region_name in REGION_MAP.values() else None)

def get_all_aws_regions() -> List[str]:
    """Get list of all supported AWS regions"""
    return list(REGION_MAP.values())
