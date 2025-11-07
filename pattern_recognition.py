import boto3
import json
import re
import logging
from typing import Dict, Optional
from cross_account_role import assume_role
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME
from parse_body import extract_actual_message

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

SYSTEM_PROMPT = (
    "You are an expert IT automation assistant specializing in AWS support ticket analysis. "
    "Your task is to analyze a support ticket and extract the following fields into a JSON object: "
    "`account_id` (12-digit AWS account ID), `account_name` (organization or customer name), "
    "`project_name` (specific project or application), `region` (AWS region, e.g., us-east-1), "
    "`issue_type` (one of: connectivity, login, performance, or null if undetermined), "
    "`query` (the main question or request), and `keywords` (list of relevant terms or phrases). "
    "Follow these instructions:\n\n"
    "1. **account_id**: Extract a 12-digit AWS account ID from the ticket subject or body. "
    "Validate that it is exactly 12 digits. If not found, use the provided account_id or set to null.\n"
    "   - Example: 'Account 123456789012 is down' → '\"account_id\": \"123456789012\"'\n"
    "2. **account_name**: Identify the organization or customer name from the ticket or context. "
    "Use 'Unknown' if not specified.\n"
    "   - Example: 'Acme Corp server issue' → '\"account_name\": \"Acme Corp\"'\n"
    "3. **project_name**: Extract the project or application name (e.g., 'BillingApp', 'WebPortal'). "
    "Use 'Unknown' if not specified.\n"
    "   - Example: 'BillingApp is slow' → '\"project_name\": \"BillingApp\"'\n"
    "4. **region**: Identify the AWS region (e.g., us-east-1, eu-west-2). If not specified, "
    "use the default region from context or set to null.\n"
    "   - Example: 'Server in us-west-2 is down' → '\"region\": \"us-west-2\"'\n"
    "5. **issue_type**: Classify the issue as 'connectivity', 'login', 'performance', or null. "
    "Base this on keywords or context:\n"
    "   - Connectivity: Terms like 'cannot connect', 'network down', 'timeout', 'unreachable'.\n"
    "   - Login: Terms like 'login failed', 'authentication error', 'access denied'.\n"
    "   - Performance: Terms like 'slow performance', 'high latency', 'response time'.\n"
    "   - Set to null if no clear issue type is identified.\n"
    "   - Example: 'Cannot connect to server' → '\"issue_type\": \"connectivity\"'\n"
    "6. **query**: Extract the main question or request, summarizing the ticket’s intent in a concise sentence. "
    "If unclear, use the ticket body.\n"
    "   - Example: 'Server is down, please help' → '\"query\": \"Assist with server downtime\"'\n"
    "7. **keywords**: Extract a list of relevant terms or phrases (e.g., 'server down', 'timeout'). "
    "Include matched patterns and other significant terms, in lowercase.\n"
    "   - Example: 'Cannot connect due to timeout' → '\"keywords\": [\"cannot connect\", \"timeout\"]'\n\n"
    "**Rules**:\n"
    "- Return a JSON object with all fields, even if null or 'Unknown'.\n"
    "- Prioritize explicit information in the ticket body over the subject.\n"
    "- If ambiguous, use context (e.g., account details, regions, team) to inform decisions.\n"
    "- Avoid guessing; set fields to null or 'Unknown' if evidence is insufficient.\n"
    "- Ensure keywords are lowercase and relevant to the issue.\n\n"
    "**Example Input**:\n"
    "- Context: Account: Acme Corp, Regions: [us-east-1, us-west-2], Team: DevOps\n"
    "- Ticket Subject: [ALARM] BillingApp down in us-west-2 for 123456789012\n"
    "- Ticket Body: Cannot connect to BillingApp. Server timeout in us-west-2.\n\n"
    "**Example Output**:\n"
    "{\n"
    "  \"account_id\": \"123456789012\",\n"
    "  \"account_name\": \"Acme Corp\",\n"
    "  \"project_name\": \"BillingApp\",\n"
    "  \"region\": \"us-west-2\",\n"
    "  \"issue_type\": \"connectivity\",\n"
    "  \"query\": \"Resolve BillingApp server timeout\",\n"
    "  \"keywords\": [\"cannot connect\", \"server timeout\", \"billingapp\", \"us-west-2\"],\n"
    "  \"ai_detected\": true\n"
    "}\n\n"
    "Analyze the provided ticket and return a JSON object with the extracted fields."
)

def get_account_details(account_id: str) -> Dict:
    """Retrieve account details from DynamoDB."""
    try:
        response = account_table.get_item(Key={'AccountId': account_id})
        return response.get('Item', {})
    except Exception as e:
        logger.error(f"Failed to get account details for {account_id}: {str(e)}")
        return {}

def identify_issue_pattern(ticket_subject: str, ticket_body: str, account_id: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Identifies recurring issue patterns and extracts AccountId, AccountName, ProjectName, Region, Issue, and Query using Bedrock AI, with regex fallback for AccountId.
    Retrieves account details for context-aware analysis. Uses extract_actual_message to clean the ticket body.
    """
    # Clean the ticket body using extract_actual_message
    cleaned_body = extract_actual_message(ticket_subject, ticket_body)
    
    patterns = {
        "connectivity": [
            r"connectivity\s+issue",
            r"cannot\s+connect",
            r"network\s+down",
            r"timeout",
            r"unreachable"
        ],
        "login": [
            r"login\s+failed",
            r"authentication\s+error",
            r"access\s+denied",
            r"invalid\s+credentials"
        ],
        "performance": [
            r"slow\s+performance",
            r"high\s+latency",
            r"application\s+slow",
            r"response\s+time"
        ]
    }
    
    result = {
        "account_id": account_id,
        "account_name": "Unknown",
        "project_name": "Unknown",
        "region": REGION,
        "issue_type": None,
        "query": cleaned_body,
        "keywords": [],
        "ai_detected": False
    }
    
    try:
        # Get account details if account_id is provided
        account_details = get_account_details(account_id) if account_id else {}
        regions = account_details.get('Regions', [])
        team_name = account_details.get('TeamName', 'Unknown')
        context = f"Account: {account_details.get('AccountName', 'Unknown')}, Regions: {regions}, Team: {team_name}"
        
        # Initialize Bedrock client with cross-account session
        session = assume_role(account_id)
        bedrock_runtime = session.client("bedrock-runtime")
        
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 12000,
            "messages": [
                {
                    "role": "user",
                    "content": f"{SYSTEM_PROMPT}\n\nContext: {context}\n\nTicket Subject: {ticket_subject}\nTicket Body: {cleaned_body}"
                }
            ]
        }
        
        # Try Bedrock AI first
        for attempt in range(1, 4):
            try:
                response = bedrock_runtime.invoke_model(
                    modelId=MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(payload).encode("utf-8")
                )
                response_body = json.loads(response["body"].read())
                model_text = response_body["content"][0]["text"]
                parsed = json.loads(model_text)
                
                result["account_id"] = parsed.get("account_id", account_id)
                result["account_name"] = parsed.get("account_name", "Unknown")
                result["project_name"] = parsed.get("project_name", "Unknown")
                result["region"] = parsed.get("region", REGION)
                result["issue_type"] = parsed.get("issue_type")
                result["query"] = parsed.get("query", cleaned_body)
                result["keywords"] = parsed.get("keywords", [])
                result["ai_detected"] = True
                logger.info(f"AI-detected fields: account_id={result['account_id']}, account_name={result['account_name']}, "
                            f"project_name={result['project_name']}, region={result['region']}, issue_type={result['issue_type']}, "
                            f"query={result['query']}, keywords={result['keywords']}")
                return result
            except Exception as e:
                logger.warning(f"Bedrock attempt {attempt} failed: {str(e)}")
                if attempt == 3:
                    logger.error("Bedrock failed after max retries, falling back to regex for AccountId")
        
        # Fallback to regex for AccountId
        content = f"{ticket_subject.lower()} {cleaned_body.lower()}"
        account_id_match = re.search(r'\d{12}', content)
        if account_id_match:
            result["account_id"] = account_id_match.group(0)
            logger.info(f"Regex-detected AccountId: {result['account_id']}")
        
        # Fallback to regex for issue_type
        for issue_type, regex_list in patterns.items():
            for pattern in regex_list:
                if re.search(pattern, content, re.IGNORECASE):
                    result["issue_type"] = issue_type
                    result["keywords"].append(pattern)
                    logger.info(f"Matched {issue_type} pattern: {pattern}")
        
        if not result["issue_type"]:
            logger.info("No known issue pattern matched")
        
        return result
    
    except Exception as e:
        logger.error(f"Error in pattern recognition: {str(e)}")
        return result