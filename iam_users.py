import json
import boto3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME
from cross_account_role import assume_role

# Configure logging
logger = logging.getLogger(__name__)

# Region mapping for converting region names to AWS region codes
region_map = {
    "Mumbai": "ap-south-1", "Hyderabad": "ap-south-2", "Osaka": "ap-northeast-3", "Seoul": "ap-northeast-2",
    "N. Virginia": "us-east-1", "Ohio": "us-east-2", "N. California": "us-west-1", "Oregon": "us-west-2",
    "Singapore": "ap-southeast-1", "Sydney": "ap-southeast-2", "Tokyo": "ap-northeast-1", "Canada": "ca-central-1",
    "Frankfurt": "eu-central-1", "Ireland": "eu-west-1", "London": "eu-west-2", "Paris": "eu-west-3",
    "Stockholm": "eu-north-1", "São Paulo": "sa-east-1"
}

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

def extract_email_address(email_input):
    """
    Extract the actual email address from a formatted string or list like:
    '"Mrinal Bhoumick"<mrinal.b@cloudworkmates.com>' or 
    '['"Mrinal Bhoumick"<mrinal.b@cloudworkmates.com>']' or
    ['mrinal.b@cloudworkmates.com']
    """
    if not email_input:
        return None
    
    # If it's a list, take the first element
    if isinstance(email_input, list):
        if len(email_input) == 0:
            return None
        email_string = email_input[0]
    else:
        email_string = email_input
    
    # Convert to string if it's not already
    email_string = str(email_string)
    
    # Remove brackets and quotes from the beginning and end
    cleaned = email_string.strip('[]"\'')
    
    # Extract email using regex - look for email pattern inside angle brackets or standalone
    email_pattern = r'<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    match = re.search(email_pattern, cleaned)
    
    if match:
        # Return the email from angle brackets or the standalone email
        return match.group(1) if match.group(1) else match.group(2)
    
    return None

def get_account_details_from_email(email):
    """
    Query DynamoDB to get account ID and allowed regions from customer email.
    """
    try:
        
        response = account_table.scan(
            FilterExpression="contains(CustomerEmailIds, :email)",
            ExpressionAttributeValues={":email": email}
        )
        
        logger.info("DynamoDB scan response: %s", response)
        
        for item in response.get("Items", []):
            # Parse regions - handle both comma-separated string and the region mapping
            regions_str = item.get("Regions", "")
            if regions_str:
                region_names = [r.strip() for r in regions_str.split(",") if r.strip()]
                # Convert region names to AWS region codes if needed
                aws_regions = []
                for region_name in region_names:
                    if region_name in region_map:
                        aws_regions.append(region_map[region_name])
                    else:
                        # If it's already an AWS region code, use it directly
                        aws_regions.append(region_name)
                
                return {
                    "AccountId": item["AccountId"],
                    "Regions": aws_regions
                }
        
        return None
        
    except Exception as e:
        logger.error("Error querying DynamoDB: %s", str(e))
        return None

class IAMUserManager:
    def __init__(self, account_id: str = None, cross_account_session: boto3.Session = None):
        """Initialize IAM User Manager with cross-account session for IAM operations"""
        # Bedrock operations use the main account session
        self.bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
        
        # IAM operations use cross-account session
        if cross_account_session:
            self.iam_session = cross_account_session
        elif account_id:
            self.iam_session = assume_role(account_id)
        else:
            raise ValueError("Either account_id or cross_account_session must be provided")
            
        self.iam = self.iam_session.client('iam')
        self.account_id = account_id
        
    def parse_ticket_for_iam_user(self, ticket_body: str) -> Dict:
        """
        Parse ticket body to extract IAM user creation details using Claude AI
        """
        system_prompt = """
        You are an expert AWS IAM automation assistant. Parse the ticket body to extract IAM user creation details.
        
        Extract the following information and return as JSON:
        {
            "iam_username": "string - the requested username",
            "permissions": ["array of permission strings"],
            "policies": ["array of policy names/ARNs"],
            "mfa_required": boolean (default true unless explicitly stated no),
            "reset_password": boolean,
            "rotate_keys_days": integer (default 90),
            "additional_requirements": "any other special requirements"
        }
        
        Rules:
        - MFA should default to true unless customer explicitly says no
        - Rotate keys should default to 90 days from creation
        - Extract any specific AWS policies mentioned
        - Look for permission requirements (ReadOnly, PowerUser, Admin, etc.)
        - Return valid JSON only
        """
        
        inference_profile_arn = MODEL_ID
        max_retries = 3
        max_tokens = 4000
        
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": f"{system_prompt}\n\nTicket Body:\n{ticket_body}"
                }
            ]
        }
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Parsing IAM user request with Claude - Attempt {attempt}")
                
                response = self.bedrock_runtime.invoke_model(
                    modelId=inference_profile_arn,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(payload).encode("utf-8")
                )
                
                response_body = json.loads(response["body"].read())
                model_text = response_body["content"][0]["text"]
                logger.info(f"Claude raw output: {model_text}")
                
                # Parse JSON response
                parsed_data = json.loads(model_text)
                
                # Set defaults if not provided
                parsed_data.setdefault("mfa_required", True)
                parsed_data.setdefault("rotate_keys_days", 90)
                parsed_data.setdefault("reset_password", True)
                
                logger.info(f"Successfully parsed IAM user request: {parsed_data}")
                return parsed_data
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response on attempt {attempt}: {e}")
                if attempt == max_retries:
                    logger.error("All attempts failed, falling back to regex extraction")
                    return self._fallback_regex_extraction(ticket_body)
            except Exception as e:
                logger.error(f"Error invoking Claude on attempt {attempt}: {e}")
                if attempt == max_retries:
                    logger.error("All attempts failed, falling back to regex extraction")
                    return self._fallback_regex_extraction(ticket_body)
        
        return self._fallback_regex_extraction(ticket_body)
    
    def _fallback_regex_extraction(self, ticket_body: str) -> Dict:
        """Fallback regex-based extraction if Claude fails"""
        logger.info("Using fallback regex extraction for IAM user details")
        
        result = {
            "iam_username": "",
            "permissions": [],
            "policies": [],
            "mfa_required": True,
            "reset_password": True,
            "rotate_keys_days": 90,
            "additional_requirements": ""
        }
        
        # Extract username patterns
        username_patterns = [
            r"username[:\s]+([a-zA-Z0-9_-]+)",
            r"user[:\s]+([a-zA-Z0-9_-]+)",
            r"create user[:\s]+([a-zA-Z0-9_-]+)",
            r"IAM user[:\s]+([a-zA-Z0-9_-]+)"
        ]
        
        for pattern in username_patterns:
            match = re.search(pattern, ticket_body, re.IGNORECASE)
            if match:
                result["iam_username"] = match.group(1)
                break
        
        # Extract MFA requirements
        if re.search(r"no mfa|disable mfa|without mfa", ticket_body, re.IGNORECASE):
            result["mfa_required"] = False
        
        # Extract policies
        policy_patterns = [
            r"ReadOnlyAccess",
            r"PowerUserAccess", 
            r"AdministratorAccess",
            r"S3FullAccess",
            r"EC2FullAccess"
        ]
        
        for policy in policy_patterns:
            if re.search(policy, ticket_body, re.IGNORECASE):
                result["policies"].append(f"arn:aws:iam::aws:policy/{policy}")
        
        return result
    
    def create_iam_user(self, user_details: Dict) -> Dict:
        """Create IAM user with specified configuration"""
        try:
            username = user_details.get("iam_username")
            if not username:
                raise ValueError("Username is required")
            
            logger.info(f"Creating IAM user: {username} in account: {self.account_id}")
            
            # Create the user
            try:
                create_response = self.iam.create_user(
                    UserName=username,
                    Path='/',
                    Tags=[
                        {
                            'Key': 'CreatedBy',
                            'Value': 'AutomationBot'
                        },
                        {
                            'Key': 'CreatedDate',
                            'Value': datetime.now().strftime('%Y-%m-%d')
                        },
                        {
                            'Key': 'RotateKeysAfter',
                            'Value': str(user_details.get("rotate_keys_days", 90))
                        }
                    ]
                )
                logger.info(f"Successfully created user: {username}")
            except self.iam.exceptions.EntityAlreadyExistsException:
                logger.warning(f"User {username} already exists")
                create_response = {"User": {"UserName": username}}
            
            # Attach policies
            policies = user_details.get("policies", [])
            for policy_arn in policies:
                try:
                    self.iam.attach_user_policy(
                        UserName=username,
                        PolicyArn=policy_arn
                    )
                    logger.info(f"Attached policy {policy_arn} to user {username}")
                except Exception as e:
                    logger.error(f"Failed to attach policy {policy_arn}: {e}")
            
            # Create access keys if needed
            access_key_response = None
            try:
                access_key_response = self.iam.create_access_key(UserName=username)
                logger.info(f"Created access keys for user: {username}")
            except Exception as e:
                logger.error(f"Failed to create access keys: {e}")
            
            # Set up login profile if reset_password is requested
            login_profile_response = None
            if user_details.get("reset_password", True):
                try:
                    # Generate temporary password
                    temp_password = self._generate_temp_password()
                    login_profile_response = self.iam.create_login_profile(
                        UserName=username,
                        Password=temp_password,
                        PasswordResetRequired=True
                    )
                    logger.info(f"Created login profile for user: {username}")
                except Exception as e:
                    logger.error(f"Failed to create login profile: {e}")
            
            # Set up MFA requirement if needed
            if user_details.get("mfa_required", True):
                try:
                    # Create policy requiring MFA
                    mfa_policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Sid": "AllowViewAccountInfo",
                                "Effect": "Allow",
                                "Action": [
                                    "iam:GetAccountPasswordPolicy",
                                    "iam:ListVirtualMFADevices"
                                ],
                                "Resource": "*"
                            },
                            {
                                "Sid": "AllowManageOwnPasswords",
                                "Effect": "Allow",
                                "Action": [
                                    "iam:ChangePassword",
                                    "iam:GetUser"
                                ],
                                "Resource": f"arn:aws:iam::*:user/${{aws:username}}"
                            },
                            {
                                "Sid": "AllowManageOwnMFA",
                                "Effect": "Allow",
                                "Action": [
                                    "iam:CreateVirtualMFADevice",
                                    "iam:DeleteVirtualMFADevice",
                                    "iam:EnableMFADevice",
                                    "iam:ListMFADevices",
                                    "iam:ResyncMFADevice"
                                ],
                                "Resource": [
                                    f"arn:aws:iam::*:mfa/${{aws:username}}",
                                    f"arn:aws:iam::*:user/${{aws:username}}"
                                ]
                            },
                            {
                                "Sid": "DenyAllExceptUnlessSignedInWithMFA",
                                "Effect": "Deny",
                                "NotAction": [
                                    "iam:CreateVirtualMFADevice",
                                    "iam:EnableMFADevice",
                                    "iam:GetUser",
                                    "iam:ListMFADevices",
                                    "iam:ListVirtualMFADevices",
                                    "iam:ResyncMFADevice",
                                    "sts:GetSessionToken"
                                ],
                                "Resource": "*",
                                "Condition": {
                                    "BoolIfExists": {
                                        "aws:MultiFactorAuthPresent": "false"
                                    }
                                }
                            }
                        ]
                    }
                    
                    policy_name = f"{username}-MFA-Policy"
                    self.iam.put_user_policy(
                        UserName=username,
                        PolicyName=policy_name,
                        PolicyDocument=json.dumps(mfa_policy)
                    )
                    logger.info(f"Applied MFA policy to user: {username}")
                except Exception as e:
                    logger.error(f"Failed to apply MFA policy: {e}")
            
            # Prepare response
            result = {
                "status": "success",
                "username": username,
                "user_arn": create_response.get("User", {}).get("Arn"),
                "policies_attached": policies,
                "mfa_required": user_details.get("mfa_required", True),
                "access_key_created": bool(access_key_response),
                "login_profile_created": bool(login_profile_response),
                "rotate_keys_after_days": user_details.get("rotate_keys_days", 90)
            }
            
            # Include sensitive data only in logs, not in response
            if access_key_response:
                access_key_id = access_key_response["AccessKey"]["AccessKeyId"]
                secret_key = access_key_response["AccessKey"]["SecretAccessKey"]
                logger.info(f"Access Key ID: {access_key_id}")
                logger.info("Secret Access Key created (check secure logs)")
                result["access_key_id"] = access_key_id
                # Don't include secret key in response for security
            
            if login_profile_response and user_details.get("reset_password", True):
                logger.info(f"Temporary password created for {username} (check secure logs)")
                result["temporary_password_set"] = True
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to create IAM user: {e}")
            return {
                "status": "error",
                "error": str(e),
                "username": user_details.get("iam_username")
            }
    
    def _generate_temp_password(self) -> str:
        """Generate a temporary password"""
        import secrets
        import string
        
        # Generate a strong temporary password
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(12))
        return password
    
    def get_user_info(self, username: str) -> Dict:
        """Get information about an existing IAM user"""
        try:
            user_response = self.iam.get_user(UserName=username)
            
            # Get attached policies
            attached_policies = self.iam.list_attached_user_policies(UserName=username)
            
            # Get inline policies
            inline_policies = self.iam.list_user_policies(UserName=username)
            
            # Get access keys
            access_keys = self.iam.list_access_keys(UserName=username)
            
            # Get MFA devices
            mfa_devices = self.iam.list_mfa_devices(UserName=username)
            
            return {
                "status": "success",
                "user": user_response["User"],
                "attached_policies": attached_policies["AttachedPolicies"],
                "inline_policies": inline_policies["PolicyNames"],
                "access_keys": [key["AccessKeyId"] for key in access_keys["AccessKeyMetadata"]],
                "mfa_devices": mfa_devices["MFADevices"]
            }
            
        except Exception as e:
            logger.error(f"Failed to get user info for {username}: {e}")
            return {"status": "error", "error": str(e)}

def handle_iam_user_creation(ticket_body: str, from_email: str = None) -> Dict:
    """
    Main function to handle IAM user creation requests
    """
    try:
        logger.info("Starting IAM user creation process")
        
        if not ticket_body:
            raise ValueError("Ticket body is required")
        
        # Get account information from email if provided
        account_id = None
        aws_region = REGION
        
        if from_email:
            actual_email = extract_email_address(from_email)
            logger.info(f"Original email: {from_email}, Extracted: {actual_email}")
            
            if not actual_email:
                raise ValueError(f"Could not extract valid email from: {from_email}")
            
            account_info = get_account_details_from_email(actual_email)
            if not account_info:
                raise ValueError(f"No account found for email: {actual_email}")
            
            account_id = account_info["AccountId"]
            aws_region = account_info["Regions"][0] if account_info["Regions"] else REGION
            logger.info(f"Found account info: AccountId={account_id}, Region={aws_region}")
        
        if not account_id:
            raise ValueError("Account ID is required for IAM user creation")
        
        # Assume role for cross-account access
        session = assume_role(account_id)
        
        # Initialize IAM User Manager
        iam_manager = IAMUserManager(account_id=account_id, cross_account_session=session)
        
        # Parse ticket for IAM user details
        user_details = iam_manager.parse_ticket_for_iam_user(ticket_body)
        logger.info(f"Parsed user details: {user_details}")
        
        if not user_details.get("iam_username"):
            raise ValueError("Could not extract username from ticket body")
        
        # Create the IAM user
        creation_result = iam_manager.create_iam_user(user_details)
        
        logger.info(f"IAM user creation result: {creation_result}")
        return creation_result
        
    except Exception as e:
        logger.error(f"Error in IAM user creation process: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to create IAM user"
        }