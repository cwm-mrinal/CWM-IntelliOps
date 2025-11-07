from agent_invoker import invoke_bedrock_agent
from constants import AGENT_ARNS, AGENT_ALIASES
import logging
import json
import re

logger = logging.getLogger()

def extract_json_from_text(text):
    """Extract JSON from various text formats"""
    try:
        # Pattern 1: Extract JSON between ```json and ```
        json_block = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_block:
            return json.loads(json_block.group(1))
        
        # Pattern 2: Extract JSON between ``` and ``` (without json keyword)
        code_block = re.search(r"```\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            return json.loads(code_block.group(1))
        
        # Pattern 3: Extract the first complete JSON object
        json_pattern = r'\{(?:[^{}]|{(?:[^{}]|{[^{}]*})*})*\}'
        json_match = re.search(json_pattern, text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
            
    except json.JSONDecodeError as e:
        logger.warning("JSON decode error: %s", str(e))
    except Exception as e:
        logger.warning("Failed to extract JSON from text: %s", str(e))
    return None

def is_cloudwatch_alarm_ticket(ticket_description):
    """Detect if this is a CloudWatch alarm ticket based on specific patterns"""
    # Check for CloudWatch alarm indicators
    alarm_indicators = [
        "Subject: ALARM:",
        "MetricNamespace:",
        "MetricName:",
        "Dimensions:",
        "Threshold:",
        "ALARM state",
        "GreaterThanOrEqualToThreshold",
        "Feedback-ID: ::1.ap-south-1",
        "support@cloudworkmates.com"
    ]
    
    # Count how many indicators are present
    matches = sum(1 for indicator in alarm_indicators if indicator in ticket_description)
    
    # If we have 4 or more indicators, it's definitely a CloudWatch alarm
    return matches >= 4

def classify_ticket(ticket_id, translated_description):
    """Classify support ticket and return category with confidence score"""
    
    # Check if this is a CloudWatch alarm ticket first
    if is_cloudwatch_alarm_ticket(translated_description):
        logger.info("Detected CloudWatch alarm ticket format, defaulting to alarm category")
        return "alarm", 0.95
    
    # More explicit classification prompt
    classification_prompt = f"""
You are a support ticket classifier. Analyze the following customer issue and respond ONLY with a JSON object containing exactly two fields:

Required JSON format:
{{"category": "alarm", "confidence": 0.95}}

Categories:
- "cost_optimization": Issues related to AWS costs, billing, or resource optimization
- "security": Security concerns, access issues, or compliance matters  
- "alarm": CloudWatch alarms, monitoring alerts, system alerts
- "custom": Custom application issues or specific business logic problems
- "os": Operating system related issues, server configuration problems

Customer Ticket:
\"{translated_description}\"

Respond with ONLY the JSON object, no additional text or explanation."""

    try:
        main_response = invoke_bedrock_agent(
            AGENT_ARNS["main"],
            ticket_id,
            classification_prompt,
            alias_id=AGENT_ALIASES["main"]
        )
        
        logger.info("Raw response from main agent: %s", main_response)
        
        if not main_response:
            logger.error("Empty or None response from Bedrock agent")
            return "custom", 0.0  # Default fallback
        
        # Handle different response formats
        raw_text = None
        if isinstance(main_response, dict):
            if 'raw_response' in main_response:
                raw_text = main_response['raw_response']
            elif 'category' in main_response and 'confidence' in main_response:
                # Direct JSON response
                return validate_classification(main_response)
            else:
                # Try to extract from the dict itself
                raw_text = str(main_response)
        elif isinstance(main_response, str):
            raw_text = main_response
        else:
            logger.error("Unexpected response type: %s", type(main_response))
            return "custom", 0.0
        
        # Check if response contains conversational text (like your example)
        if raw_text and any(phrase in raw_text.lower() for phrase in [
            "i need to clarify", "should i:", "which format", "want to confirm"
        ]):
            logger.warning("Agent returned conversational response instead of classification")
            # Try to infer from the ticket content directly
            return fallback_classification(translated_description)
        
        # Try to extract JSON from the text
        parsed_json = extract_json_from_text(raw_text)
        
        if parsed_json:
            return validate_classification(parsed_json)
        else:
            logger.warning("Could not extract valid JSON from response")
            return fallback_classification(translated_description)
            
    except Exception as e:
        logger.error("Error in classify_ticket: %s", str(e))
        return fallback_classification(translated_description)

def validate_classification(parsed_json):
    """Validate and return classification results"""
    try:
        category = parsed_json.get("category", "").lower().strip()
        confidence = float(parsed_json.get("confidence", 0.0))
        
        # Validate category
        valid_categories = ['cost_optimization', 'security', 'alarm', 'custom', 'os']
        if category not in valid_categories:
            logger.warning("Invalid category '%s', defaulting to 'custom'", category)
            category = "custom"
            confidence = 0.5
        
        # Validate confidence
        if not (0.0 <= confidence <= 1.0):
            logger.warning("Invalid confidence %s, clamping to valid range", confidence)
            confidence = max(0.0, min(1.0, confidence))
        
        return category, confidence
        
    except (ValueError, TypeError) as e:
        logger.error("Error validating classification: %s", str(e))
        return "custom", 0.0

def fallback_classification(ticket_description):
    """Fallback classification based on keywords when agent fails"""
    
    # First check if it's a CloudWatch alarm ticket
    if is_cloudwatch_alarm_ticket(ticket_description):
        return "alarm", 0.95
    
    description_lower = ticket_description.lower()
    
    # Alarm keywords (expanded for better detection)
    alarm_keywords = ['alarm', 'alert', 'cloudwatch', 'metric', 'threshold', 'monitoring', 
                     'cpu', 'memory', 'disk', 'warning', 'critical', 'metricnamespace',
                     'metricname', 'dimensions', 'statistic', 'period', 'greaterthanorequaltothreshold']
    
    # Cost optimization keywords  
    cost_keywords = ['cost', 'billing', 'expensive', 'optimize', 'budget', 'spend', 'charge']
    
    # Security keywords
    security_keywords = ['security', 'access', 'permission', 'unauthorized', 'breach', 
                        'credential', 'authentication', 'iam', 'policy']
    
    # OS keywords
    os_keywords = ['operating system', 'windows', 'linux', 'server', 'boot', 'registry',
                  'service', 'process', 'configuration']
    
    # Check for alarm (highest priority for your case)
    if any(keyword in description_lower for keyword in alarm_keywords):
        return "alarm", 0.8
    
    # Check other categories
    if any(keyword in description_lower for keyword in cost_keywords):
        return "cost_optimization", 0.7
    
    if any(keyword in description_lower for keyword in security_keywords):
        return "security", 0.7
        
    if any(keyword in description_lower for keyword in os_keywords):
        return "os", 0.7
    
    # Default to custom
    return "custom", 0.5