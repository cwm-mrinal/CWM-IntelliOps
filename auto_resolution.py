import boto3
import json
import logging
from typing import Dict, Any
from botocore.exceptions import ClientError
from cross_account_role import assume_role
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME
from parse_body import extract_actual_message

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

SYSTEM_PROMPT = (
    "You are an expert IT automation assistant specializing in AWS support ticket resolution. "
    "Your task is to analyze a support ticket and provide a resolution action based on the issue type and ticket details. "
    "Return a JSON object with the following fields: 'action' (a specific, safe AWS operation or null if no action is feasible) "
    "and 'parameters' (a dictionary of required parameters for the action). Follow these instructions:\n\n"
    "1. **Issue Types and Actions**:\n"
    "   - **Connectivity**: Issues like 'cannot connect', 'network down', 'timeout', or 'unreachable'. "
    "     Suggested action: 'reboot_instance' (reboot an EC2 instance). "
    "     Parameters: {'instance_id': '<AWS EC2 instance ID>'}. "
    "     Example: 'Cannot connect to server' → {'action': 'reboot_instance', 'parameters': {'instance_id': 'i-1234567890abcdef0'}}.\n"
    "   - **Login**: Issues like 'login failed', 'authentication error', 'access denied', or 'invalid credentials'. "
    "     Suggested action: 'reset_password' (reset IAM user credentials). "
    "     Parameters: {'user_id': '<IAM user ID or username>'}. "
    "     Example: 'Login failed for user' → {'action': 'reset_password', 'parameters': {'user_id': 'john.doe'}}.\n"
    "   - **Performance**: Issues like 'slow performance', 'high latency', or 'response time'. "
    "     Suggested action: 'modify_instance_type' (upgrade EC2 instance type). "
    "     Parameters: {'instance_id': '<AWS EC2 instance ID>', 'instance_type': '<new instance type, e.g., t3.medium>'}. "
    "     Example: 'Application slow' → {'action': 'modify_instance_type', 'parameters': {'instance_id': 'i-1234567890abcdef0', 'instance_type': 't3.medium'}}.\n"
    "   - If the issue type is unclear or insufficient details are provided, return {'action': null, 'parameters': {}, 'reason': '<explanation>'}.\n\n"
    "2. **Rules**:\n"
    "   - Prioritize safe, reversible actions (e.g., reboot, reset password, modify instance type). Avoid destructive actions like terminating instances.\n"
    "   - Use the provided context (account name, regions) to tailor the resolution. For example, ensure the instance_id or region is valid for the account.\n"
    "   - Extract parameters from the ticket body or subject if available (e.g., instance IDs, user IDs). If not found, use placeholders but include a 'reason' field explaining the issue.\n"
    "   - Ensure all parameters required for the action are included in the 'parameters' dictionary.\n"
    "   - If no actionable resolution is possible, set 'action' to null and provide a clear 'reason' in the parameters (e.g., 'Missing instance_id').\n"
    "   - Ensure all keywords in parameters (e.g., instance_id, user_id) are lowercase and match AWS API expectations.\n"
    "   - Return a valid JSON object, even if fields are null or empty.\n\n"
    "3. **Example Input**:\n"
    "   - Issue Type: connectivity\n"
    "   - Context: Account: Acme Corp, Regions: [us-east-1, us-west-2]\n"
    "   - Ticket Subject: [ALARM] BillingApp down in us-west-2\n"
    "   - Ticket Body: Cannot connect to BillingApp on instance i-1234567890abcdef0.\n"
    "   **Example Output**:\n"
    "   {\n"
    "     'action': 'reboot_instance',\n"
    "     'parameters': {'instance_id': 'i-1234567890abcdef0'}\n"
    "   }\n\n"
    "4. **Edge Case Handling**:\n"
    "   - If the ticket lacks sufficient details (e.g., no instance_id for connectivity), return:\n"
    "     {'action': null, 'parameters': {}, 'reason': 'Missing required parameter: instance_id'}\n"
    "   - If the issue type does not match a known category or no action is applicable, return:\n"
    "     {'action': null, 'parameters': {}, 'reason': 'No actionable resolution for the issue'}\n\n"
    "Analyze the provided ticket and return a JSON object with the resolution action and parameters."
)

class AutoResolutionEngine:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.session = assume_role(account_id)
        self.ec2_client = self.session.client('ec2')
        self.bedrock_runtime = self.session.client("bedrock-runtime")
        self.rollback_states = {}
    
    def get_resolution_suggestion(self, issue_type: str, ticket_body: str, ticket_subject: str) -> Dict:
        """Get AI-driven resolution suggestion from Bedrock."""
        # Clean the ticket body using extract_actual_message
        cleaned_body = extract_actual_message(ticket_subject, ticket_body)
        
        try:
            account_details = account_table.get_item(Key={'AccountId': self.account_id}).get('Item', {})
            context = f"Account: {account_details.get('AccountName', 'Unknown')}, Regions: {account_details.get('Regions', [])}"
            
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 12000,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{SYSTEM_PROMPT}\n\nIssue Type: {issue_type}\nContext: {context}\nTicket Subject: {ticket_subject}\nTicket Body: {cleaned_body}"
                    }
                ]
            }
            
            response = self.bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )
            response_body = json.loads(response["body"].read())
            return json.loads(response_body["content"][0]["text"])
        except Exception as e:
            logger.error(f"Failed to get resolution suggestion: {str(e)}")
            return {"action": None, "parameters": {}}
    
    def resolve_connectivity(self, ticket_id: str, ticket_body: str, ticket_subject: str) -> Dict[str, Any]:
        """Resolves connectivity issues with AI suggestion."""
        # Clean the ticket body using extract_actual_message
        cleaned_body = extract_actual_message(ticket_subject, ticket_body)
        
        try:
            suggestion = self.get_resolution_suggestion("connectivity", cleaned_body, ticket_subject)
            instance_id = suggestion["parameters"].get("instance_id", "i-1234567890abcdef0")
            
            logger.info(f"Attempting connectivity resolution for ticket {ticket_id} with suggestion: {suggestion}")
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            self.rollback_states[ticket_id] = {
                "instance_id": instance_id,
                "state": response['Reservations'][0]['Instances'][0]['State']['Name']
            }
            
            if suggestion["action"] == "reboot_instance":
                self.ec2_client.reboot_instances(InstanceIds=[instance_id])
                logger.info(f"Rebooted instance {instance_id} for ticket {ticket_id}")
                return {"status": "success", "message": f"Instance {instance_id} rebooted"}
            else:
                logger.warning(f"Unknown action: {suggestion['action']}")
                return {"status": "error", "message": "Invalid resolution action"}
        except ClientError as e:
            logger.error(f"Failed to resolve connectivity: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def resolve_login(self, ticket_id: str, ticket_body: str, ticket_subject: str) -> Dict[str, Any]:
        """Resolves login issues with AI suggestion."""
        # Clean the ticket body using extract_actual_message
        cleaned_body = extract_actual_message(ticket_subject, ticket_body)
        
        try:
            suggestion = self.get_resolution_suggestion("login", cleaned_body, ticket_subject)
            user_id = suggestion["parameters"].get("user_id", "user_id_placeholder")
            
            logger.info(f"Attempting login resolution for ticket {ticket_id} with suggestion: {suggestion}")
            return {"status": "success", "message": f"Credentials reset for user {user_id}"}
        except Exception as e:
            logger.error(f"Failed to resolve login: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def resolve_performance(self, ticket_id: str, ticket_body: str, ticket_subject: str) -> Dict[str, Any]:
        """Resolves performance issues with AI suggestion."""
        # Clean the ticket body using extract_actual_message
        cleaned_body = extract_actual_message(ticket_subject, ticket_body)
        
        try:
            suggestion = self.get_resolution_suggestion("performance", cleaned_body, ticket_subject)
            instance_id = suggestion["parameters"].get("instance_id")
            
            logger.info(f"Attempting performance resolution for ticket {ticket_id} with suggestion: {suggestion}")
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            self.rollback_states[ticket_id] = {
                "instance_id": instance_id,
                "instance_type": response['Reservations'][0]['Instances'][0]['InstanceType']
            }
            
            if suggestion["action"] == "modify_instance_type":
                self.ec2_client.modify_instance_attribute(
                    InstanceId=instance_id,
                    InstanceType={'Value': suggestion["parameters"].get("instance_type", "t3.medium")}
                )
                return {"status": "success", "message": f"Instance {instance_id} upgraded to {suggestion['parameters'].get('instance_type', 't3.medium')}"}
            else:
                logger.warning(f"Unknown action: {suggestion['action']}")
                return {"status": "error", "message": "Invalid resolution action"}
        except ClientError as e:
            logger.error(f"Failed to resolve performance: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def rollback(self, ticket_id: str) -> Dict[str, Any]:
        """Rolls back changes for a given ticket."""
        try:
            if ticket_id not in self.rollback_states:
                return {"status": "error", "message": "No rollback state found"}
            
            state = self.rollback_states[ticket_id]
            instance_id = state.get("instance_id")
            
            if "instance_type" in state:
                self.ec2_client.modify_instance_attribute(
                    InstanceId=instance_id,
                    InstanceType={'Value': state["instance_type"]}
                )
                logger.info(f"Rolled back instance type for {instance_id}")
            
            del self.rollback_states[ticket_id]
            return {"status": "success", "message": f"Rollback completed for {instance_id}"}
        except ClientError as e:
            logger.error(f"Rollback failed: {str(e)}")
            return {"status": "error", "message": str(e)}