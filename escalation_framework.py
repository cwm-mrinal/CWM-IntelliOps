import boto3
import json
import logging
import requests
import re
from typing import Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN_TEAM, ORG_ID
from ticket_assign import assign_ticket_to_team
from escalation_mail import send_email_reply

logger = logging.getLogger()
logger.setLevel(logging.INFO)

logger.info(f"Using DynamoDB table: {ACCOUNT_TABLE_NAME} in region: {REGION}")

# Enhanced HTML email template with escaped curly braces in CSS
HTML_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{ 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: #ffffff;
            min-height: 100vh;
            line-height: 1.6;
        }}
        
        .email-wrapper {{
            background: transparent;
            border-radius: 20px;
            padding: 20px;
            max-width: 650px;
            margin: 0 auto;
        }}
        
        .container {{ 
            max-width: 100%;
            margin: 0 auto; 
            background: #ffffff;
            border-radius: 16px; 
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
            position: relative;
        }}
        
        .container::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, #007bff, #28a745, #ffc107, #dc3545);
        }}
        
        .header {{ 
            background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
            color: #ffffff; 
            padding: 40px 30px; 
            text-align: center; 
            position: relative;
            overflow: hidden;
        }}
        
        .header::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><pattern id="grain" width="100" height="100" patternUnits="userSpaceOnUse"><circle cx="25" cy="25" r="1" fill="rgba(255,255,255,0.1)"/><circle cx="75" cy="75" r="1" fill="rgba(255,255,255,0.1)"/><circle cx="50" cy="10" r="0.5" fill="rgba(255,255,255,0.05)"/><circle cx="20" cy="80" r="0.5" fill="rgba(255,255,255,0.05)"/></pattern></defs><rect width="100" height="100" fill="url(%23grain)"/></svg>');
            opacity: 0.3;
        }}
        
        .header img {{ 
            max-width: 180px; 
            height: auto; 
            filter: brightness(1.1) drop-shadow(0 2px 4px rgba(0,0,0,0.2));
            margin-bottom: 15px;
            position: relative;
            z-index: 1;
        }}
        
        .header h1 {{ 
            margin: 15px 0 0 0; 
            font-size: 28px; 
            font-weight: 700; 
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
            position: relative;
            z-index: 1;
        }}
        
        .status-badge {{
            display: inline-block;
            background: rgba(255,255,255,0.2);
            backdrop-filter: blur(10px);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            margin-top: 10px;
            border: 1px solid rgba(255,255,255,0.3);
        }}
        
        .content {{ 
            padding: 40px 30px; 
            background: #ffffff;
        }}
        
        .content p {{ 
            margin: 15px 0; 
            font-size: 16px; 
            color: #2c3e50;
            font-weight: 400;
        }}
        
        .greeting {{
            font-size: 18px;
            font-weight: 600;
            color: #1a202c;
            margin-bottom: 20px;
        }}
        
        .message-content {{
            background: linear-gradient(135deg, #f8f9ff 0%, #e3f2fd 100%);
            padding: 25px;
            border-radius: 12px;
            border-left: 4px solid #007bff;
            margin: 25px 0;
            position: relative;
            overflow: hidden;
        }}
        
        .message-content::before {{
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 60px;
            height: 60px;
            background: rgba(0,123,255,0.1);
            border-radius: 50%;
            transform: translate(20px, -20px);
        }}
        
        .details-card {{
            background: #ffffff;
            border-radius: 12px;
            padding: 0;
            margin: 25px 0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            border: 1px solid #e2e8f0;
            overflow: hidden;
        }}
        
        .details-header {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            padding: 20px;
            border-bottom: 1px solid #dee2e6;
        }}
        
        .details-header h3 {{
            font-size: 18px;
            font-weight: 600;
            color: #2c3e50;
            margin: 0;
            display: flex;
            align-items: center;
        }}
        
        .details-header h3::before {{
            content: '📋';
            margin-right: 10px;
            font-size: 20px;
        }}
        
        .details {{ 
            width: 100%; 
            border-collapse: collapse; 
            margin: 0;
        }}
        
        .details tr:hover {{
            background: rgba(0,123,255,0.02);
        }}
        
        .details th, .details td {{ 
            padding: 18px 20px; 
            text-align: left; 
            font-size: 15px;
            border-bottom: 1px solid #f1f3f4;
        }}
        
        .details th {{ 
            background: transparent;
            color: #4a5568; 
            font-weight: 600;
            width: 30%;
            position: relative;
        }}
        
        .details td {{ 
            color: #2d3748;
            font-weight: 500;
        }}
        
        .details tr:last-child th,
        .details tr:last-child td {{
            border-bottom: none;
        }}
        
        .button-container {{
            text-align: center;
            margin: 30px 0;
        }}
        
        .button {{ 
            display: inline-block; 
            padding: 16px 32px; 
            background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
            color: #ffffff; 
            text-decoration: none; 
            border-radius: 10px; 
            font-size: 16px; 
            font-weight: 600; 
            margin: 10px 8px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(0,123,255,0.3);
            position: relative;
            overflow: hidden;
        }}
        
        .button::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s;
        }}
        
        .button:hover::before {{
            left: 100%;
        }}
        
        .button:hover {{ 
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0,123,255,0.4);
        }}
        
        .secondary-button {{ 
            display: inline-block; 
            padding: 14px 28px; 
            background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
            color: #ffffff; 
            text-decoration: none; 
            border-radius: 10px; 
            font-size: 14px; 
            font-weight: 500;
            margin: 10px 8px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(108,117,125,0.3);
        }}
        
        .secondary-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(108,117,125,0.4);
        }}
        
        .footer {{ 
            text-align: center; 
            padding: 30px 20px; 
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            font-size: 13px; 
            color: #6c757d;
            border-top: 1px solid #dee2e6;
        }}
        
        .footer p {{
            margin: 8px 0;
        }}
        
        .footer a {{ 
            color: #007bff; 
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s ease;
        }}
        
        .footer a:hover {{
            color: #0056b3;
            text-decoration: underline;
        }}
        
        .company-info {{
            background: rgba(0,123,255,0.05);
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
            border: 1px solid rgba(0,123,255,0.1);
        }}
        
        .priority-indicator {{
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #28a745;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0% {{ box-shadow: 0 0 0 0 rgba(40, 167, 69, 0.7); }}
            70% {{ box-shadow: 0 0 0 10px rgba(40, 167, 69, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(40, 167, 69, 0); }}
        }}
        
        @media only screen and (max-width: 600px) {{
            body {{ padding: 10px; }}
            .email-wrapper {{ padding: 10px; border-radius: 15px; }}
            .container {{ border-radius: 12px; }}
            .header {{ padding: 25px 20px; }}
            .header h1 {{ font-size: 22px; }}
            .header img {{ max-width: 140px; }}
            .content {{ padding: 25px 20px; }}
            .content p {{ font-size: 15px; }}
            .details th, .details td {{ padding: 12px 15px; font-size: 14px; }}
            .button {{ padding: 14px 24px; font-size: 15px; margin: 8px 4px; }}
            .secondary-button {{ padding: 12px 20px; font-size: 13px; }}
            .message-content {{ padding: 20px; }}
            .details-header {{ padding: 15px; }}
            .details-header h3 {{ font-size: 16px; }}
        }}
        
        @media (prefers-color-scheme: dark) {{
            /* Dark mode support can be added here if needed */
        }}
    </style>
</head>
<body>
    <div class="email-wrapper">
        <div class="container">
            <div class="header">
                <img src="https://zoho-uptime-automation-assets-bucket.s3.ap-south-1.amazonaws.com/Workmates-Logo.png" alt="CloudWorkMates Logo">
                <h1>{subject}</h1>
                <div class="status-badge">
                    <span class="priority-indicator"></span>
                    Automated Notification
                </div>
            </div>
            <div class="content">
                <p class="greeting">Dear {recipient_name},</p>
                
                <div class="message-content">
                    <p>{message}</p>
                </div>
                
                <div class="details-card">
                    <div class="details-header">
                        <h3>Ticket Details</h3>
                    </div>
                    <table class="details">
                        <tr><th>Ticket ID</th><td><strong>{ticket_id}</strong></td></tr>
                        <tr><th>Subject</th><td>{ticket_subject}</td></tr>
                        <tr><th>Reason</th><td>{reason}</td></tr>
                        <tr><th>Contact Person</th><td>{contact_name}</td></tr>
                        <tr><th>Phone</th><td>{contact_phone}</td></tr>
                        <tr><th>Email</th><td>{contact_email}</td></tr>
                    </table>
                </div>
                
                <div class="button-container">
                    <a href="https://desk.zoho.com/portal/ticket/{ticket_id}" class="button">🎫 View Ticket in Zoho Desk</a>
                    <br>
                    <a href="mailto:support@cloudworkmates.com" class="secondary-button">📧 Contact Support</a>
                </div>
            </div>
            <div class="footer">
                <p><strong>Workmates Support Team</strong></p>
                <p>
                    <a href="https://sns.ap-south-1.amazonaws.com/unsubscribe">Unsubscribe</a> | 
                    <a href="tel:+918249711902">📞 082497 11902</a>
                </p>
                <div class="company-info">
                    <p>3rd 4th & 6th floor, RAIKVA Building, 3A, Ram Mohan Mullick Garden Ln<br>
                    Subhas Sarobar Park, Phool Bagan, Beleghata, Kolkata, West Bengal 700010</p>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

SYSTEM_PROMPT = (
    "You are an IT automation assistant specializing in ticket escalation for a cloud support system. Your task is to analyze the provided ticket details, diagnostics, and account context to recommend an escalation level (Bot, L1, L2, or L3) and provide a clear, concise reason for your recommendation. Follow these guidelines:\n"
    "- **Escalation Levels**:\n"
    "  - **Bot**: For automated resolution of simple, repetitive issues (e.g., password resets, basic configuration changes).\n"
    "  - **L1**: For issues requiring basic technical support, such as minor configuration errors or user guidance, resolvable by junior support staff.\n"
    "  - **L2**: For complex issues requiring advanced technical expertise, such as performance bottlenecks, infrastructure issues, or errors needing code-level debugging (e.g., 'WaiterError' issues).\n"
    "  - **L3**: For critical issues impacting production systems, requiring senior engineers or architects, such as system outages, security breaches, or complex integrations.\n"
    "- Consider the ticket's severity, urgency, impact (e.g., production vs. non-production), and diagnostics (e.g., CPU/memory utilization, error codes).\n"
    "- If diagnostics indicate critical thresholds (e.g., CPU > 95%), prioritize higher escalation (L2 or L3).\n"
    "- If information is insufficient, recommend L2 with a reason explaining the need for further investigation.\n"
    "- Provide a concise reason (50-100 words) explaining the escalation choice, referencing specific diagnostics or ticket details.\n"
    "- Always return the response as a valid JSON object with 'recommended_level' and 'reason' keys, wrapped in a ```json``` Markdown code block.\n\n"
    "Example response:\n"
    "```json\n"
    "{\n"
    "  \"recommended_level\": \"L2\",\n"
    "  \"reason\": \"High CPU utilization (98%) indicates a performance issue requiring advanced troubleshooting by L2 engineers.\"\n"
    "}\n"
    "```"
)

TEAM_LEADS = {
    "SMB Windows Team": {
        "name": "Sudhir Kumar Mohapatra",
        "email": "sudhir.m@cloudworkmates.com",
        "phone": "+91-7008912605"
    },
    "Enterprise Linux Team": {
        "name": "Jahangeer Alam",
        "email": "jahangeer.a@cloudworkmates.com",
        "phone": "+91-8618199208"
    },
    "SMB Linux Team": {
        "name": "Arghya Sengupta",
        "email": "arghya.s@cloudworkmates.com",
        "phone": "+91-8777032280"
    },
    "Enterprise Windows Team": {
        "name": "Istiyak Ahmed",
        "email": "istiyak.ahmed@cloudworkmates.com",
        "phone": "+91-7044695313"
    },
    "DevOps Team": {
        "name": "Devendra Pratap Maurya",
        "email": "devendra.m@cloudworkmates.com",
        "phone": "+91-6386846488"
    }
}

ESCALATION_MATRIX = {
    "L1": {
        "name": "Angshuman Adhikary",
        "phone": "+91-9830782426",
        "email": "angshuman.a@cloudworkmates.com",
        "toll_free": "18008901233"
    },
    "L2": {
        "name": "Niraj Kumar",
        "phone": "+91-8544240519",
        "email": "niraj.k@cloudworkmates.com"
    },
    "L3": {
        "name": "Arunava Mukherjee",
        "phone": "+91-9681316717",
        "email": "arunava.m@cloudworkmates.com"
    }
}

class EscalationFramework:
    def __init__(self, account_id: str):
        if not account_id:
            raise ValueError("Account ID cannot be empty")
        self.account_id = account_id
        sts_client = boto3.client('sts')
        identity = sts_client.get_caller_identity()
        logger.info(f"Initialized boto3 session in account {identity['Account']} for region {REGION}")
        self.dynamodb = boto3.resource('dynamodb', region_name=REGION)
        self.bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
        self.account_table = self.dynamodb.Table(ACCOUNT_TABLE_NAME)
    
    def get_team_name_and_email(self, ticket_id: str) -> Dict[str, str]:
        """Fetch TeamName from DynamoDB and match with Team Lead email."""
        try:
            response = self.account_table.get_item(Key={'AccountId': self.account_id})
            logger.info(f"DynamoDB response for AccountId {self.account_id} for ticket {ticket_id}: {response}")
            item = response.get('Item', {})
            team_name = item.get('TeamName', '')
            if not team_name:
                logger.error(f"No TeamName found for AccountId {self.account_id} in table {ACCOUNT_TABLE_NAME} for ticket {ticket_id}")
                return {"team_name": "", "email": ""}
            
            team_lead = TEAM_LEADS.get(team_name, {})
            email = team_lead.get('email', '') if team_lead else ''
            if not email:
                logger.error(f"No Team Lead email found for team {team_name} for ticket {ticket_id}")
                return {"team_name": team_name, "email": ""}
            
            logger.info(f"Matched TeamName: {team_name} with email: {email} for ticket {ticket_id}")
            return {"team_name": team_name, "email": email}
        except self.dynamodb.meta.client.exceptions.ResourceNotFoundException as e:
            logger.error(f"DynamoDB table {ACCOUNT_TABLE_NAME} or item not found for AccountId {self.account_id} for ticket {ticket_id}: {str(e)}")
            return {"team_name": "", "email": ""}
        except Exception as e:
            logger.error(f"Failed to fetch TeamName for AccountId {self.account_id} for ticket {ticket_id}: {str(e)}")
            return {"team_name": "", "email": ""}
    
    def get_zoho_ticket_details(self, ticket_id: str) -> Dict:
        """Fetch ticket details from Zoho Desk for SLA monitoring."""
        try:
            access_token = get_access_token()
            url = f"https://desk.zoho.com/api/v1/tickets/{ticket_id}"
            headers = {
                "Authorization": f"Zoho-oauthtoken {access_token}",
                "orgId": ORG_ID
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch Zoho ticket details for ticket {ticket_id}: {str(e)}")
            return {}
    
    def parse_diagnostics(ticket_body: str, ticket_subject: str) -> dict:
        """
        Parse ticket_body to extract diagnostics information.
        """
        diagnostics = {}
        try:
            # Extract alarm_percentage
            alarm_match = re.search(r'\[([\d.]+)\s*\([^)]+\)\]', ticket_body)
            if alarm_match:
                diagnostics['alarm_percentage'] = float(alarm_match.group(1))

            # Extract created_at timestamp
            timestamp_match = re.search(r'(\w+ \d{2} \w+, \d{4} \d{2}:\d{2}:\d{2} UTC)', ticket_body)
            if timestamp_match:
                # Convert to ISO format (e.g., '2025-07-02T06:06:44Z')
                timestamp = datetime.strptime(timestamp_match.group(1), '%A %d %B, %Y %H:%M:%S UTC')
                diagnostics['created_at'] = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Extract additional alarm details
            namespace_match = re.search(r'MetricNamespace: (\S+)', ticket_body)
            if namespace_match:
                diagnostics['MetricNamespace'] = namespace_match.group(1)

            metric_match = re.search(r'MetricName: (\S+)', ticket_body)
            if metric_match:
                diagnostics['MetricName'] = metric_match.group(1)

            instance_match = re.search(r"Dimensions: \[\{'value': '([^']+)', 'name': 'InstanceId'\}\]", ticket_body)
            if instance_match:
                diagnostics['InstanceId'] = instance_match.group(1)

            period_match = re.search(r'Period: (\d+) seconds', ticket_body)
            if period_match:
                diagnostics['Period'] = int(period_match.group(1))

            statistic_match = re.search(r'Statistic: (\S+)', ticket_body)
            if statistic_match:
                diagnostics['Statistic'] = statistic_match.group(1)

            unit_match = re.search(r'Unit: (\S+)', ticket_body)
            if unit_match:
                diagnostics['Unit'] = unit_match.group(1)

            threshold_match = re.search(r'GreaterThanOrEqualToThreshold ([\d.]+)', ticket_body)
            if threshold_match:
                diagnostics['Threshold'] = float(threshold_match.group(1))

        except Exception as e:
            logger.error(f"Failed to parse diagnostics: {str(e)}")
            diagnostics = {'alarm_percentage': 0, 'created_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}

        return diagnostics

    def get_escalation_recommendation(self, ticket_id: str, ticket_body: str, ticket_subject: str, diagnostics: Dict) -> Dict:
        """Get AI-driven escalation recommendation from Bedrock."""
        try:
            response = self.account_table.get_item(Key={'AccountId': self.account_id})
            logger.info(f"DynamoDB response for AccountId {self.account_id} for ticket {ticket_id}: {response}")
            account_details = response.get('Item', {})
            if not account_details:
                logger.error(f"No account found for AccountId {self.account_id} in table {ACCOUNT_TABLE_NAME} for ticket {ticket_id}")
                return {"recommended_level": "L2", "reason": "Default escalation due to missing account details"}
            
            context = f"Account: {account_details.get('AccountName', 'Unknown')}, Regions: {account_details.get('Regions', [])}"
            
            # Check alarm threshold for Team Lead notification
            alarm_percentage = diagnostics.get('alarm_percentage', 0)
            if 95 < alarm_percentage < 100:
                team_info = self.get_team_name_and_email(ticket_id)
                team_name = team_info['team_name']
                if team_name:
                    self.notify_team_lead(ticket_id, team_name, ticket_subject)
            
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 12000,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{SYSTEM_PROMPT}\n\nContext: {context}\nTicket ID: {ticket_id}\nDiagnostics: {json.dumps(diagnostics)}\nTicket Subject: {ticket_subject}\nTicket Body: {ticket_body}"
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
            logger.info(f"Bedrock response for ticket {ticket_id}: {response_body}")
            content_text = response_body.get("content", [{}])[0].get("text", "")
            if not content_text:
                logger.error(f"Empty or invalid Bedrock response content for ticket {ticket_id}")
                return {"recommended_level": "L2", "reason": "Default escalation due to empty Bedrock response"}
            
            # Extract JSON from Markdown code block
            json_match = re.search(r'```json\n([\s\S]*?)\n```', content_text)
            if not json_match:
                logger.error(f"No JSON code block found in Bedrock response for ticket {ticket_id}: {content_text}")
                return {"recommended_level": "L2", "reason": "Default escalation due to invalid Bedrock response format"}
            
            json_str = json_match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from Bedrock response for ticket {ticket_id}: {json_str}, error: {str(e)}")
                return {"recommended_level": "L2", "reason": f"Default escalation due to invalid JSON: {str(e)}"}
                
        except self.dynamodb.meta.client.exceptions.ResourceNotFoundException as e:
            logger.error(f"DynamoDB table {ACCOUNT_TABLE_NAME} or item not found for AccountId {self.account_id} for ticket {ticket_id}: {str(e)}")
            return {"recommended_level": "L2", "reason": f"Default escalation due to missing account details: {str(e)}"}
        except Exception as e:
            logger.error(f"Failed to get escalation recommendation for ticket {ticket_id}: {str(e)}")
            return {"recommended_level": "L2", "reason": f"Default escalation due to failure: {str(e)}"}
    
    def notify_team_lead(self, ticket_id: str, team_name: str, ticket_subject: str) -> Dict[str, Any]:
        """Notify Team Lead via Zoho Desk email, escalate to L2 if email fails."""
        try:
            team_lead = TEAM_LEADS.get(team_name, {})
            if not team_lead:
                logger.error(f"No Team Lead defined for team {team_name} for ticket {ticket_id}")
                return {"status": "error", "message": f"No Team Lead defined for team {team_name}", "email": ""}
            
            subject = f"Urgent: Ticket {ticket_id} Requires Attention"
            message = (
                f"Ticket {ticket_id} requires your immediate attention. "
                f"Please review and take action."
            )
            template_vars = {
                "subject": subject,
                "recipient_name": team_lead['name'],
                "message": message,
                "ticket_id": ticket_id,
                "ticket_subject": ticket_subject,
                "reason": "High alarm threshold detected",
                "contact_name": team_lead['name'],
                "contact_phone": team_lead['phone'],
                "contact_email": team_lead['email']
            }
            try:
                html_content = HTML_EMAIL_TEMPLATE.format(**template_vars)
            except KeyError as e:
                logger.error(f"Failed to format HTML template for ticket {ticket_id}: Missing key {str(e)}")
                return {"status": "error", "message": f"Template formatting failed: {str(e)}", "email": team_lead['email']}
            
            try:
                response = send_email_reply(
                    ticket_id=ticket_id,
                    from_emails=["support@cloudworkmates.com"],
                    to_emails=[team_lead['email']],
                    cc_emails=["aman.s@cloudworkmates.com"],
                    reply_text=html_content
                )
                if response["statusCode"] != 200:
                    logger.error(f"Zoho email failed for ticket {ticket_id}: {response['body']}")
                    # Escalate to L2 (Niraj Kumar)
                    l2_manager = ESCALATION_MATRIX["L2"]
                    subject = f"Escalation: Ticket {ticket_id} Notification Failure"
                    message = (
                        f"Failed to notify {team_lead['name']} for ticket {ticket_id}. "
                        f"Please review and take action."
                    )
                    template_vars = {
                        "subject": subject,
                        "recipient_name": l2_manager['name'],
                        "message": message,
                        "ticket_id": ticket_id,
                        "ticket_subject": ticket_subject,
                        "reason": f"Failed to notify Team Lead {team_lead['name']}",
                        "contact_name": l2_manager['name'],
                        "contact_phone": l2_manager['phone'],
                        "contact_email": l2_manager['email']
                    }
                    try:
                        html_content = HTML_EMAIL_TEMPLATE.format(**template_vars)
                    except KeyError as e:
                        logger.error(f"Failed to format HTML template for L2 escalation for ticket {ticket_id}: Missing key {str(e)}")
                        return {"status": "error", "message": f"L2 template formatting failed: {str(e)}", "email": l2_manager['email']}
                    
                    response = send_email_reply(
                        ticket_id=ticket_id,
                        from_emails=["support@cloudworkmates.com"],
                        to_emails=[l2_manager['email']],
                        cc_emails=["aman.s@cloudworkmates.com"],
                        reply_text=html_content
                    )
                    if response["statusCode"] != 200:
                        logger.error(f"Zoho email failed for L2 escalation for ticket {ticket_id}: {response['body']}")
                        return {"status": "error", "message": f"Failed to notify L2: {response['body']}", "email": l2_manager['email']}
                    
                    logger.info(f"Escalated ticket {ticket_id} to L2 ({l2_manager['name']}, {l2_manager['email']})")
                    return {
                        "status": "escalated",
                        "team_lead_notified": team_lead['name'],
                        "l2_notified": l2_manager['name'],
                        "email": l2_manager['email']
                    }
                
                logger.info(f"Notified {team_lead['name']} ({team_lead['email']}) for ticket {ticket_id}")
                return {
                    "status": "success",
                    "team_lead_notified": team_lead['name'],
                    "email": team_lead['email']
                }
            except Exception as e:
                logger.error(f"Failed to email {team_lead['name']} ({team_lead['email']}) for ticket {ticket_id}: {str(e)}")
                # Escalate to L2 (Niraj Kumar)
                l2_manager = ESCALATION_MATRIX["L2"]
                subject = f"Escalation: Ticket {ticket_id} Notification Failure"
                message = (
                    f"Failed to notify {team_lead['name']} for ticket {ticket_id}. "
                    f"Please review and take action."
                )
                template_vars = {
                    "subject": subject,
                    "recipient_name": l2_manager['name'],
                    "message": message,
                    "ticket_id": ticket_id,
                    "ticket_subject": ticket_subject,
                    "reason": f"Failed to notify Team Lead {team_lead['name']}",
                    "contact_name": l2_manager['name'],
                    "contact_phone": l2_manager['phone'],
                    "contact_email": l2_manager['email']
                }
                try:
                    html_content = HTML_EMAIL_TEMPLATE.format(**template_vars)
                except KeyError as e:
                    logger.error(f"Failed to format HTML template for L2 escalation for ticket {ticket_id}: Missing key {str(e)}")
                    return {"status": "error", "message": f"L2 template formatting failed: {str(e)}", "email": l2_manager['email']}
                
                response = send_email_reply(
                    ticket_id=ticket_id,
                    from_emails=["support@cloudworkmates.com"],
                    to_emails=[l2_manager['email']],
                    cc_emails=["aman.s@cloudworkmates.com"],
                    reply_text=html_content
                )
                if response["statusCode"] != 200:
                    logger.error(f"Failed to email L2 ({l2_manager['name']}, {l2_manager['email']}) for ticket {ticket_id}: {response['body']}")
                    return {
                        "status": "error",
                        "message": f"Failed to notify L2: {response['body']}",
                        "email": l2_manager['email']
                    }
                
                logger.info(f"Escalated ticket {ticket_id} to L2 ({l2_manager['name']}, {l2_manager['email']})")
                return {
                    "status": "escalated",
                    "team_lead_notified": team_lead['name'],
                    "l2_notified": l2_manager['name'],
                    "email": l2_manager['email']
                }
        except Exception as e:
            logger.error(f"Team Lead notification failed for ticket {ticket_id}: {str(e)}")
            return {"status": "error", "message": f"Team Lead notification failed: {str(e)}", "email": ""}
    
    def assign_team_lead(self, ticket_id: str, ticket_subject: str, ticket_body: str, diagnostics: Dict) -> Dict[str, Any]:
        """Assign ticket to the Team Lead in Zoho Desk based on TeamName."""
        try:
            team_info = self.get_team_name_and_email(ticket_id)
            team_name = team_info['team_name']
            if not team_name:
                logger.error(f"No TeamName found for account {self.account_id} in table {ACCOUNT_TABLE_NAME} for ticket {ticket_id}")
                return {"status": "error", "message": "No TeamName found for account", "email": ""}
            
            team_lead = TEAM_LEADS.get(team_name, {})
            if not team_lead:
                logger.error(f"No Team Lead defined for team {team_name} for ticket {ticket_id}")
                return {"status": "error", "message": f"No Team Lead defined for team {team_name}", "email": ""}
            
            # Assign ticket to team in Zoho Desk
            logger.info(f"Assigning ticket {ticket_id} to {team_name} ({team_lead['email']})")
            zoho_response = assign_ticket_to_team(str(ticket_id), team_name)
            
            if zoho_response["statusCode"] != 200:
                logger.error(f"Zoho assignment failed for ticket {ticket_id}: {zoho_response['body']}")
                return {"status": "error", "message": zoho_response["body"], "email": team_lead['email']}
            
            logger.info(f"Assigned ticket {ticket_id} to Team Lead {team_lead['name']} ({team_lead['email']}) for team {team_name}")
            return {
                "status": "success",
                "team_lead": team_lead['name'],
                "team_name": team_name,
                "email": team_lead['email'],
                "zoho_response": zoho_response["body"]
            }
        except Exception as e:
            logger.error(f"Team Lead assignment failed for ticket {ticket_id}: {str(e)}")
            return {"status": "error", "message": f"Team Lead assignment failed: {str(e)}", "email": ""}
    
    def escalate_ticket(self, ticket_id: str, current_level: str, ticket_body: str, ticket_subject: str, diagnostics: Dict) -> Dict[str, Any]:
        """Escalates ticket to next level based on AI recommendation and notifies via Zoho Desk email."""
        try:
            recommendation = self.get_escalation_recommendation(ticket_id, ticket_body, ticket_subject, diagnostics)
            next_level = recommendation["recommended_level"]
            
            # Notify higher management via Zoho Desk email
            manager = ESCALATION_MATRIX.get(next_level, {})
            if not manager:
                logger.error(f"No manager defined for escalation level {next_level} for ticket {ticket_id}")
                return {"status": "error", "message": f"No manager defined for level {next_level}", "email": ""}
            
            subject = f"Ticket {ticket_id} Escalated to {next_level}"
            message = (
                f"Ticket {ticket_id} has been escalated to {next_level}: {recommendation['reason']}. "
                f"Please review and take action."
            )
            template_vars = {
                "subject": subject,
                "recipient_name": manager['name'],
                "message": message,
                "ticket_id": ticket_id,
                "ticket_subject": ticket_subject,
                "reason": recommendation['reason'],
                "contact_name": manager['name'],
                "contact_phone": manager['phone'],
                "contact_email": manager['email']
            }
            try:
                html_content = HTML_EMAIL_TEMPLATE.format(**template_vars)
            except KeyError as e:
                logger.error(f"Failed to format HTML template for ticket {ticket_id}: Missing key {str(e)}")
                return {"status": "error", "message": f"Template formatting failed: {str(e)}", "email": manager['email']}
            
            try:
                response = send_email_reply(
                    ticket_id=ticket_id,
                    from_emails=["support@cloudworkmates.com"],
                    to_emails=[manager['email']],
                    cc_emails=["aman.s@cloudworkmates.com"],
                    reply_text=html_content
                )
                if response["statusCode"] != 200:
                    logger.error(f"Zoho email failed for ticket {ticket_id}: {response['body']}")
                    return {"status": "error", "message": f"Failed to notify {manager['name']}: {response['body']}", "email": manager['email']}
                
                logger.info(f"Notified {manager['name']} ({manager['email']}) for ticket {ticket_id} escalation to {next_level}")
                return {
                    "status": "success",
                    "new_level": next_level,
                    "reason": recommendation["reason"],
                    "email": manager['email']
                }
            except Exception as e:
                logger.error(f"Failed to email {manager['name']} ({manager['email']}) for ticket {ticket_id}: {str(e)}")
                return {"status": "error", "message": f"Failed to notify {manager['name']}: {str(e)}", "email": manager['email']}
        except Exception as e:
            logger.error(f"Escalation failed for ticket {ticket_id}: {str(e)}")
            return {"status": "error", "message": f"Escalation failed: {str(e)}", "email": ""}
    
    def monitor_sla(self, ticket_id: str, diagnostics: Dict, sla_hours: int = 4) -> Dict[str, Any]:
        """Monitors SLA and sends email alerts for violations using Zoho Desk ticket data."""
        try:
            # Try to get created_at from diagnostics, else fetch from Zoho
            created_at_str = diagnostics.get('created_at')
            if not created_at_str:
                ticket_details = self.get_zoho_ticket_details(ticket_id)
                created_at_str = ticket_details.get('createdTime')
                if not created_at_str:
                    logger.error(f"No created_at provided or found in Zoho for ticket {ticket_id}")
                    return {"status": "error", "message": "No created_at provided or found in Zoho", "email": ""}
            
            try:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            except ValueError as e:
                logger.error(f"Invalid created_at format for ticket {ticket_id}: {created_at_str}, error: {str(e)}")
                return {"status": "error", "message": f"Invalid created_at format: {str(e)}", "email": ""}
            
            now = datetime.now(ZoneInfo('UTC'))  # Offset-aware UTC time
            if now - created_at > timedelta(hours=sla_hours):
                team_info = self.get_team_name_and_email(ticket_id)
                team_name = team_info['team_name']
                team_lead = TEAM_LEADS.get(team_name, {})
                recipient = team_lead if team_name and team_lead else ESCALATION_MATRIX["L2"]
                subject = f"SLA Violation: Ticket {ticket_id}"
                message = f"SLA violation for ticket {ticket_id}: Exceeded {sla_hours} hours. Please take action."
                template_vars = {
                    "subject": subject,
                    "recipient_name": recipient['name'],
                    "message": message,
                    "ticket_id": ticket_id,
                    "ticket_subject": "SLA Violation",
                    "reason": f"SLA exceeded {sla_hours} hours",
                    "contact_name": recipient['name'],
                    "contact_phone": recipient['phone'],
                    "contact_email": recipient['email']
                }
                try:
                    html_content = HTML_EMAIL_TEMPLATE.format(**template_vars)
                except KeyError as e:
                    logger.error(f"Failed to format HTML template for SLA violation for ticket {ticket_id}: Missing key {str(e)}")
                    return {"status": "error", "message": f"SLA template formatting failed: {str(e)}", "email": recipient['email']}
                
                try:
                    response = send_email_reply(
                        ticket_id=ticket_id,
                        from_emails=["support@cloudworkmates.com"],
                        to_emails=[recipient['email']],
                        cc_emails=["aman.s@cloudworkmates.com"],
                        reply_text=html_content
                    )
                    if response["statusCode"] != 200:
                        logger.error(f"Failed to send SLA violation email for ticket {ticket_id} to {recipient['name']} ({recipient['email']}): {response['body']}")
                        return {"status": "error", "message": f"SLA notification failed: {response['body']}", "email": recipient['email']}
                    
                    logger.info(f"SLA violation email sent for ticket {ticket_id} to {recipient['name']} ({recipient['email']})")
                    return {
                        "status": "violation",
                        "message": "SLA exceeded",
                        "email": recipient['email']
                    }
                except Exception as e:
                    logger.error(f"Failed to send SLA violation email for ticket {ticket_id} to {recipient['name']} ({recipient['email']}): {str(e)}")
                    return {"status": "error", "message": f"SLA notification failed: {str(e)}", "email": recipient['email']}
            
            return {"status": "within_sla", "message": "SLA compliant", "email": ""}
        except Exception as e:
            logger.error(f"SLA monitoring failed for ticket {ticket_id}: {str(e)}")
            return {"status": "error", "message": f"SLA monitoring failed: {str(e)}", "email": ""}