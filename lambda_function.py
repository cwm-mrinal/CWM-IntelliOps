import json
import logging
import re
import base64
from bs4 import BeautifulSoup
import boto3
from language_utils import detect_and_translate
from classifier import classify_ticket
from agent_invoker import invoke_bedrock_agent
from zoho_integration import handle_zoho
from teams_integration import handle_custom, send_alarm_to_uptime_team
from constants import AGENT_ARNS, AGENT_ALIASES, DLQ_URL, REGION
from mail_handler import handle_mail
from first_response import send_email_reply
from ticket_assign import assign_ticket_to_team
from ticket_status import update_ticket_status
from replay_failed_events import replay_failed_events
from monitor_alerts import lambda_handler as alarm_handler 
from parse_body import extract_actual_message 
from ec2_start_stop_handler import lambda_handler as ec2_lambda_handler 
from ec2_scheduler import handle_message
from security_group_handler import lambda_handler as sg_lambda_handler 
from alarm_formatter import handle_alarm
from check_site import check_site_status
from ticket_site_status import close_ticket_status
from ticket_embeddings import save_bedrock_response
from search_similar_embeddings import search_similar_ticket_response 
from account_restriction import handle_account_restriction_from_body
#from first_response_template import FIRST_RESPONSE_TEMPLATE
from pattern_recognition import identify_issue_pattern
#from auto_resolution import AutoResolutionEngine
#from service_health import ServiceHealthMonitor
from escalation_framework import EscalationFramework
from iam_users import handle_iam_user_creation

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sqs = boto3.client("sqs")

def infer_ticket_type_from_subject(subject: str) -> str:
    subject = subject.strip().lower()

    # Prefix patterns indicating alarm-type tickets
    alarm_prefixes = [
        r"^\[?alarm[:\]]",
        r"^alarm[:\s]",
        r"^health event[:\s\]]?",
        r"^incident[:\s\]]?",
        r"^\[?alert[:\s\]]?",
        r"^\[alert\]",
        r"^\[alert\]\s*\[firing\]",
        r"^\[action required\]",
        r"^\[firing[:\s\]]?",
        r"^\[resolved[:\s\]]?",                      
    ]

    # Alarm indicators anywhere in the subject text
    alarm_indicators = [
        r"\bdown\b",
        r"\bup\b.*\b200\s*-\s*ok\b",
        r"status code\s*5\d\d",
        r"\b(request|connection)\s*failed\b",
        r"\bserver error\b",
        r"request failed with status code\s*5\d\d",
        r"\bpodrestart\b",
        r"cost anomaly detected",
        r"aws cost management",
        r"aws budgets?.*exceed(ed|ing)?",
        r"\bmonthly[_\s-]?budget\b",
        r"exceeded.*alert threshold",
        r"\baction may be required\b",
        r"docker v\d+\.\d+\.\d+",                
    ]

    # First check for prefixes
    for pattern in alarm_prefixes:
        if re.match(pattern, subject):
            return "alarm"

    # Then check for indicators
    for pattern in alarm_indicators:
        if re.search(pattern, subject):
            return "alarm"

    return "client"

def sanitize_json_string(json_str):
    """Remove or escape invalid control characters from JSON string"""
    if not json_str:
        return json_str
    
    # Replace common problematic characters with escaped versions
    json_str = json_str.replace('\n', '\\n')
    json_str = json_str.replace('\r', '\\r') 
    json_str = json_str.replace('\t', '\\t')
    json_str = json_str.replace('\b', '\\b')
    json_str = json_str.replace('\f', '\\f')
    
    json_str = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_str)
    
    return json_str

def safe_json_parse(json_str):
    """Safely parse JSON with multiple fallback methods"""
    if not isinstance(json_str, str):
        return json_str
    
    try:
        # First attempt: standard JSON parsing
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("Initial JSON parse failed: %s", str(e))
        
        try:
            # Second attempt: sanitize and try again
            sanitized = sanitize_json_string(json_str)
            return json.loads(sanitized)
        except json.JSONDecodeError as e2:
            logger.error("JSON parse failed after sanitization: %s", str(e2))
            
            # Log problematic area for debugging
            if hasattr(e2, 'pos') and e2.pos < len(json_str):
                start = max(0, e2.pos - 50)
                end = min(len(json_str), e2.pos + 50)
                context = json_str[start:end]
                char_at_pos = json_str[e2.pos] if e2.pos < len(json_str) else 'EOF'
                logger.error("Error context: %r", context)
                logger.error("Character at error position: %r (ord: %d)", char_at_pos, ord(char_at_pos) if char_at_pos != 'EOF' else -1)
            
            raise e2

def lambda_handler(event, context):
    try:
        # Enhanced JSON parsing with error handling
        raw_body = event.get("body")
        logger.info("Raw body content: %s", raw_body)
        logger.info("Raw body type: %s, length: %s", type(raw_body), len(raw_body) if raw_body else 0)
        
        # Parse the request body safely
        body = safe_json_parse(raw_body) if isinstance(raw_body, str) else event
        
        logger.info("Successfully parsed request body")
        
        # Continue with your existing logic
        path = event.get("path")
        method = event.get("httpMethod")
        resource = event.get("resource")

        ticket_id = body.get("ticketId")
        ticket_subject = body.get("ticketSubject")
        ticket_body = body.get("ticketBody")
        zoho_account_id = body.get("zohoAccountId")

        ticket_type = infer_ticket_type_from_subject(ticket_subject or "")
        logger.info("Inferred ticket_type from subject: %s", ticket_type)
       
        cc_emails = body.get("ccEmail", [])
        to_emails = body.get("toEmail", [])
        from_emails = body.get("fromEmail", [])

        if not isinstance(cc_emails, list): cc_emails = [cc_emails]
        if not isinstance(to_emails, list): to_emails = [to_emails]
        if not isinstance(from_emails, list): from_emails = [from_emails]

        logger.info("Parsed email fields - CC: %s, TO: %s, FROM: %s", cc_emails, to_emails, from_emails)

        all_emails = cc_emails + to_emails + from_emails
        email_matches = [email for email in all_emails if re.match(r"[\w\.-]+@[\w\.-]+", str(email))]
        customer_email = email_matches[-1] if email_matches else None

        logger.info("Extracted fields - ticketId: %s, subject: %s, ticket_type: %s, customerEmail: %s",
                    ticket_id, ticket_subject, ticket_type, customer_email)

        if not ticket_subject or not ticket_body:
            logger.warning("Missing ticket subject or body")
            return {
                "statusCode": 400, 
                "body": json.dumps({"error": "Missing 'ticketSubject' or 'ticketBody' in input"})
            } 

        ticket_body = extract_actual_message(body.get("ticketSubject"), body.get("ticketBody"))
        logger.info("Extracted actual message from ticket body")
        logger.info("Ticket body: %s", ticket_body)

        ticket_id = str(body.get("ticketId"))
        logger.info("Assigning ticket %s to Uptime Team", ticket_id)
        assign_ticket_to_team(str(ticket_id), "Uptime Team")
        logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
        status_response = update_ticket_status(str(ticket_id))
        
        """
        # Initialize EscalationFramework
        escalator = EscalationFramework(zoho_account_id)
        
        # Parse diagnostics
        diagnostics = escalator.parse_diagnostics(ticket_body, ticket_subject)
        logger.info(f"Parsed diagnostics: {diagnostics}")
        
        # Get team information
        team_info = escalator.get_team_name_and_email(ticket_id)
        logger.info(f"Team info: {team_info}") 
        
        """

        # AI-driven detection for AccountId, AccountName, ProjectName, Region, Issue, and Query
        pattern_recognizer = identify_issue_pattern(ticket_body, ticket_subject)
        account_id = pattern_recognizer.get("account_id")
        account_name = pattern_recognizer.get("account_name", "Unknown")
        project_name = pattern_recognizer.get("project_name", "Unknown")
        region = pattern_recognizer.get("region", REGION)
        issue_type = pattern_recognizer.get("issue_type", "Unknown")
        query = pattern_recognizer.get("query", ticket_body)
        logger.info("Extracted AccountId: %s, AccountName: %s, ProjectName: %s, Region: %s, Issue: %s, Query: %s",
                    account_id, account_name, project_name, region, issue_type, query)
        
        # AI Detection and Escalation Management
        # Extract AccountId from ticket_subject or ticket_body
        account_id = None
        # Check if ticket_subject exists and search for a 12-digit account ID using regex
        if ticket_subject:
            account_id_match = re.search(r'\d{12}', ticket_subject)
            if account_id_match:
                account_id = account_id_match.group(0)
        if not account_id and ticket_body:
            account_id_match = re.search(r'\d{12}', ticket_body)
            # If a match is found, assign the matched account ID
            if account_id_match:
                account_id = account_id_match.group(0)

        account_id = account_id
        
        logger.info("Extracted AccountId: %s", account_id)
        
        """
        # Initialize new components with cross-account session
        pattern_recognizer = identify_issue_pattern(ticket_body, ticket_subject, account_id)
        auto_resolver = AutoResolutionEngine(account_id)
        health_monitor = ServiceHealthMonitor(account_id)
        escalator = EscalationFramework(account_id) 
        
        # Pattern recognition and auto-resolution
        issue_type = pattern_recognizer.get("issue_type")
        # If an issue type is identified, proceed with further processing
        if issue_type:
            logger.info(f"Identified issue: {issue_type}, AI-detected: {pattern_recognizer['ai_detected']}")
            
            # Pass instance_id, ticket_body, and ticket_subject to check service health
            health_status = health_monitor.check_service_health(instance_id, ticket_body, ticket_subject)
            # Log the result of the service health check
            logger.info(f"Health check result: {health_status}")
            
            # Attempt auto-resolution based on the identified issue type
            resolution_result = None
            # If the issue is connectivity-related, attempt to resolve it
            if issue_type == "connectivity":
                resolution_result = auto_resolver.resolve_connectivity(ticket_id, ticket_body, ticket_subject)
            # If the issue is login-related, attempt to resolve it
            elif issue_type == "login":
                resolution_result = auto_resolver.resolve_login(ticket_id, ticket_body, ticket_subject)
            # If the issue is performance-related, attempt to resolve it
            elif issue_type == "performance":
                resolution_result = auto_resolver.resolve_performance(ticket_id, ticket_body, ticket_subject)
            
            # Check if auto-resolution was successful
            if resolution_result and resolution_result.get("status") == "success":
                # Log the successful auto-resolution message
                logger.info(f"Auto-resolution successful: {resolution_result['message']}")
                # Close the ticket since it was successfully resolved
                close_ticket_status(str(ticket_id))
                # Return a success response with details about the resolution
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "status": "auto-resolved",
                        "ticketId": ticket_id,
                        "issue_type": issue_type,
                        "resolution": resolution_result["message"]
                    })
                }
            else:
                # Log a warning if auto-resolution failed, including the failure message
                logger.warning(f"Auto-resolution failed: {resolution_result.get('message')}")
                # Attempt to rollback any changes made during the failed resolution
                rollback_result = auto_resolver.rollback(ticket_id)
                # Log the result of the rollback
                logger.info(f"Rollback result: {rollback_result}")
                
                # Escalate with AI recommendation
                escalation_result = escalator.escalate_ticket(ticket_id, "Bot", ticket_body, ticket_subject, health_status.get("diagnostics", {}))
                # Check if escalation was successful and assign an engineer
                if escalation_result["status"] == "success":
                    assign_result = escalator.assign_engineer(ticket_id, issue_type)
                    # Log the engineer assignment result
                    logger.info(f"Engineer assignment: {assign_result}")
                
                # Check SLA compliance for the ticket
                sla_result = escalator.monitor_sla(ticket_id)
                # Log the SLA status
                logger.info(f"SLA status: {sla_result}")
        """

        # ------------------------ Adding Restriction Account Check -------------------------------
        # Restriction check
        restriction_result = handle_account_restriction_from_body(
            ticket_id=ticket_id,
            ticket_subject=ticket_subject,
            ticket_body_message=ticket_body,
            from_emails=from_emails,
            to_emails=to_emails,
            cc_emails=cc_emails,
        )

        if restriction_result.get("response"):
            return restriction_result["response"]

        # Check for specific restriction messages and exit early
        if not restriction_result.get("account_found", True):
            logger.warning("AccountId not found — setting ticket_type to 'Client'")
            ticket_type = "client"
            #reply_text = FIRST_RESPONSE_TEMPLATE
            #l1_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
            #logger.info("First response sent: %s", l1_response)
            # Exit immediately for no valid AWS AccountId - matches your log pattern
            logger.warning("Exiting function early: No valid AWS AccountId found in ticket body. Will treat as client.")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Function terminated early: No valid AWS AccountId found",
                    "ticket_id": ticket_id
                })
            }
        
        # Check if the restriction_result contains a response (meaning account was found but not supported)
        # This corresponds to the 403 response in your account_restriction.py
        if restriction_result.get("response") and restriction_result["response"].get("statusCode") == 403:
            logger.info("Exiting function early: AccountId is not supported - ticket routed to Uptime Team")
            return restriction_result["response"]
        
        top_similar = search_similar_ticket_response(ticket_body)
        
        # Fix: Check the status and access the results properly
        if top_similar and top_similar.get("status") == "success":
            results = top_similar.get("results", [])
            if results:
                logger.info("Top similar past responses:")
                logger.info(f"Found {top_similar['total_found']} similar tickets in {top_similar['processing_time_seconds']} seconds")
                for result in results:
                    logger.info("Match: %.2f | Ticket ID: %s", result["similarity"], result["ticketId"])
            else:
                logger.info("No similar tickets found above threshold.")
        elif top_similar and top_similar.get("status") == "error":
            logger.error("Error searching for similar tickets: %s", top_similar.get("message"))
        else:
            logger.info("No similar tickets found.")

        # Step 1: Check the site status
        site_status_message = check_site_status(ticket_body)
        logger.info("Site status message: %s", site_status_message)

        if re.search(r"📶 Status:\s+HTTP 2\d{2}", site_status_message):
            logger.info("Posting private comment to Zoho for ticket %s", ticket_id)
            handle_zoho(str(ticket_id), site_status_message)

            logger.info("Closing ticket %s", ticket_id)
            close_ticket_status(str(ticket_id))
        
        ticket_description = f"{ticket_subject}\n\n{ticket_body}"
        logger.info("Combined ticket description for processing.")

        language_code, translated_description = detect_and_translate(ticket_description)
        logger.info("Detected language: %s", language_code) 

        classification, confidence = classify_ticket(str(ticket_id), translated_description)
        logger.info("Initial classification result - category: %s, confidence: %.2f", classification, confidence)

        if ticket_type and ticket_type.lower() == "client":
            logger.info("Overriding classification to 'custom' due to ticket_type 'Client'")
            classification = "custom"
            confidence = 1.0
           
        elif not classification or confidence < 0.7:
            logger.warning("Low confidence or missing classification. Routing to manual review.")

            try:
                logger.info("Sending Teams notification to Uptime Team due to low confidence classification.")
                uptime_resp = send_alarm_to_uptime_team(
                    team_name="Uptime Team",
                    subject=ticket_subject,
                    ticket_id=str(ticket_id),
                    reply_text="Low confidence classification. Manual review required.",
                    from_email=from_emails,
                    to_emails=to_emails,
                    cc_emails=cc_emails,
                )
                logger.info("Uptime Team notification response: %s", uptime_resp)
            except Exception as te:
                logger.error("Failed to notify Uptime Team: %s", str(te))
           
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "fallback",
                    "message": "Low confidence score. Manual review needed.",
                    "classification": classification,
                    "confidence": confidence,
                    "ticket_type": ticket_type
                })
            }

        agent_key = classification
        agent_arn = AGENT_ARNS.get(agent_key)
        alias_id = AGENT_ALIASES.get(agent_key)

        logger.info("Invoking Bedrock Agent with ARN: %s and alias ID: %s", agent_arn, alias_id)
        prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}\n\n"
      
        response_data = handle_mail(prompt=prompt)
        save_bedrock_response(str(ticket_id), ticket_subject, ticket_body, response_data, source="bedrock_handle_mail")
        logger.info("Received response from Bedrock Agent: %s", response_data)

        reply_text = ""
        if isinstance(response_data, dict):
            reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
        elif isinstance(response_data, str):
            reply_text = response_data

        if not reply_text:
            reply_text = "Thank you for reaching out."
        logger.info("Reply text to be sent: %s", reply_text)
        
        zoho_resp = None
        if classification in ["alarm", "security", "cost_optimization"]:
            #logger.info("Triggering Zoho integration for classification: %s", classification)
            #zoho_resp = handle_zoho(str(ticket_id), reply_text)
            #logger.info("Zoho integration response: %s", zoho_resp)
           
            if classification == "alarm":
                try:
                    logger.info("Assigning ticket %s to team: %s", ticket_id, "Uptime Team")
                    assign_ticket_to_team(str(ticket_id), "Uptime Team")
                    logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
                    status_response = update_ticket_status(str(ticket_id))
                    logger.info("Initiating CloudWatch alarm image generation and ticket update process.")
                    alarm_resp = alarm_handler(event, context)
                    if alarm_resp.get("statusCode") == 200:
                        logger.info("Successfully attached CloudWatch alarm image to ticket. Response: %s", alarm_resp)
                    else:
                        logger.warning("Failed to attach CloudWatch alarm image to ticket. Response: %s", alarm_resp)
                    logger.info("Ticket status update response: %s", status_response)
                    logger.info("Sending Teams notification to Uptime Team for 'alarm' ticket.")
                    uptime_resp = send_alarm_to_uptime_team(
                        team_name="Uptime Team",
                        subject=ticket_subject,
                        ticket_id=str(ticket_id),
                        reply_text=reply_text,
                        from_email=from_emails,
                        to_emails=to_emails,
                        cc_emails=cc_emails,
                    )
                    logger.info("Uptime Team notification response: %s", uptime_resp)
                    logger.info("Sending email reply to customer.")
                    prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}"
                    response_data = handle_alarm(prompt=prompt,ticket_subject=ticket_subject,ticket_body=ticket_body,ticket_id=ticket_id)
                    save_bedrock_response(ticket_id, ticket_subject, ticket_body, response_data, source="bedrock_handle_alarm")
                    logger.info("Received response from Bedrock Agent for Alarm Data: %s", response_data)

                    if isinstance(response_data, dict):
                        reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
                    elif isinstance(response_data, str):
                        reply_text = response_data

                    first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
                    logger.info("First response sent: %s", first_response)
                except Exception as te:
                    logger.error("Failed to notify Uptime Team: %s", str(te)) 

        elif classification == "security":
                try:
                    logger.info("Assigning ticket %s to team: %s", ticket_id, "Uptime Team")
                    assign_ticket_to_team(str(ticket_id), "Uptime Team")
                    logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
                    status_response = update_ticket_status(str(ticket_id))
                    uptime_resp = send_alarm_to_uptime_team(
                        team_name="Uptime Team",
                        subject=ticket_subject,
                        ticket_id=str(ticket_id),
                        reply_text=reply_text,
                        from_email=from_emails,
                        to_emails=to_emails,
                        cc_emails=cc_emails,
                    )
                    logger.info("Uptime Team notification response: %s", uptime_resp)
                    logger.info("Sending email reply to customer.")
                    prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}"
                    response_data = handle_alarm(prompt=prompt,ticket_subject=ticket_subject,ticket_body=ticket_body,ticket_id=ticket_id)
                    logger.info("Received response from Bedrock Agent for Alarm Data: %s", response_data)

                    if isinstance(response_data, dict):
                        reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
                    elif isinstance(response_data, str):
                        reply_text = response_data

                    first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
                    logger.info("First response sent: %s", first_response)
                
                except Exception as te:
                    logger.error("Failed to notify Security Team: %s", str(te)) 
        elif classification == "cost_optimization":
            try:
                logger.info("Assigning ticket %s to team: %s", ticket_id, "Uptime Team")
                assign_ticket_to_team(str(ticket_id), "Uptime Team")
                logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
                status_response = update_ticket_status(str(ticket_id))
                logger.info("Sending Teams notification to Uptime Team for 'cost_optimization' ticket.")
                uptime_resp = send_alarm_to_uptime_team(
                    team_name="Uptime Team",
                    subject=ticket_subject,
                    ticket_id=str(ticket_id),
                    reply_text=reply_text,
                    from_email=from_emails,
                    to_emails=to_emails,
                    cc_emails=cc_emails,
                )
                logger.info("Cost Optimization Team notification response: %s", uptime_resp)
                logger.info("Sending email reply to customer.")
                prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}"
                response_data = handle_alarm(prompt=prompt, ticket_subject=ticket_subject, ticket_body=ticket_body,ticket_id=ticket_id)
                logger.info("Received response from Bedrock Agent for Alarm Data: %s", response_data)

                if isinstance(response_data, dict):
                    reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
                elif isinstance(response_data, str):
                    reply_text = response_data

                first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
                logger.info("First response sent: %s", first_response)
            except Exception as te:
                logger.error("Failed to notify Cost Optimization Team: %s", str(te))
        elif classification == "custom":
            ec2_event = {
                "message": ticket_body,
                "body": {
                    "fromEmail": from_emails
                }
            }
            ec2_response = ec2_lambda_handler(ec2_event, context)

            logger.info("EC2 Lambda response: %s", ec2_response)

            sg_event = {
                "message": ticket_body,
                "body": {
                    "fromEmail": from_emails
                }
            }
            sg_response = sg_lambda_handler(sg_event, context)
            logger.info("SG Lambda response: %s", sg_response)

            ec2_message = None
            if isinstance(ec2_response, dict) and ec2_response.get("statusCode") in [200, 202]:
                ec2_message = ec2_response.get("detailedMessage") or ec2_response.get("message")

            sg_message = None
            if isinstance(sg_response, dict) and sg_response.get("statusCode") in [200, 202]:
                sg_message = sg_response.get("detailedMessage") or sg_response.get("message")

            if ec2_message or sg_message:
                prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}"
                if ec2_message:
                    prompt += f"\n\nEC2 Response:\n{ec2_message}"
                if sg_message:
                    prompt += f"\n\nSecurity Group Response:\n{sg_message}"

                response_data = handle_message(prompt=prompt)
                save_bedrock_response(ticket_id, ticket_subject, ticket_body, response_data, source="bedrock_ec2_sg_lambda_handler")
                logger.info("Received response from Bedrock Agent (after EC2/SG update): %s", response_data)

                if isinstance(response_data, dict):
                    reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
                elif isinstance(response_data, str):
                    reply_text = response_data

                logger.info("Sending first response to customer based on EC2/SG + Bedrock response.")
                first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
                logger.info("First response sent: %s", first_response)

            else:
                logger.info("EC2/SG response missing or null, sending fallback response using original reply_text.")
                prompt = f"Ticket ID: {ticket_id}\n\n{translated_description}"
                response_data = handle_mail(prompt=prompt)
                save_bedrock_response(ticket_id, ticket_subject, ticket_body, response_data, source="bedrock_general_support")
                logger.info("Received response from Bedrock Agent (fallback): %s", response_data)

                if isinstance(response_data, dict):
                    reply_text = response_data.get("reply") or response_data.get("message") or response_data.get("raw_response", "")
                elif isinstance(response_data, str):
                    reply_text = response_data

                first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
                logger.info("First response sent: %s", first_response)

            logger.info("Handling custom classification with Teams integration.")
            custom_resp = handle_custom(
                customer_email,
                ticket_subject,
                ticket_body,
                reply_text,
                str(ticket_id),
                from_email=from_emails,
                to_emails=to_emails,
                cc_emails=cc_emails,
                zoho_account_id=zoho_account_id
            )

            logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
            status_response = update_ticket_status(str(ticket_id))
            logger.info("Teams integration response: %s", custom_resp)

            if isinstance(custom_resp, dict):
                try:
                    body_raw = custom_resp.get("body", "{}")
                    body_data = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
                    team_name = body_data.get("teamName")

                    if team_name:
                        logger.info("Assigning ticket %s to team: %s", ticket_id, team_name)
                        assign_ticket_to_team(str(ticket_id), team_name)
                except Exception as e:
                    logger.error("Failed to parse custom response: %s", e, exc_info=True)

            return custom_resp

           
        if re.search(r"(create|add|new)\s+(IAM\s+user|user)", ticket_body, re.IGNORECASE):
            logger.info("Detected IAM user creation request in custom ticket")
            iam_response = handle_iam_user_creation(ticket_body, from_emails[0] if from_emails else None)
            logger.info("IAM user creation response: %s", iam_response)

            if iam_response.get("status") == "success":
                reply_text = f"IAM user {iam_response.get('username')} created successfully. "
                if iam_response.get("temporary_password_set"):
                    reply_text += "A temporary password has been set, and the user must reset it upon first login. "
                if iam_response.get("mfa_required"):
                    reply_text += "MFA is required for this user. "
                if iam_response.get("access_key_created"):
                    reply_text += f"Access Key ID: {iam_response.get('access_key_id')}. "
                reply_text += "Please check secure logs for sensitive information."
            else:
                reply_text = f"Failed to create IAM user: {iam_response.get('error')}"
            
            logger.info("Sending IAM response to customer")
            first_response = send_email_reply(str(ticket_id), from_emails, to_emails, cc_emails, reply_text)
            logger.info("IAM response sent: %s", first_response)

            logger.info("Assigning ticket %s to team: %s", ticket_id, "Uptime Team")
            assign_ticket_to_team(str(ticket_id), "Uptime Team")
            logger.info("Updating ticket status from 'Open' to 'Assigned' for ticket %s", ticket_id)
            status_response = update_ticket_status(str(ticket_id))

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "success",
                    "ticketId": str(ticket_id),
                    "customerEmail": customer_email,
                    "ticket_type": ticket_type,
                    "category": classification,
                    "confidence": confidence,
                    "language": language_code,
                    "agent_used": agent_key,
                    "reply": reply_text,
                    "iam_response": iam_response,
                    "fromEmail": from_emails,
                    "toEmail": to_emails,
                    "ccEmail": cc_emails,
                })
            }

    except Exception as e:
        logger.error("Unhandled Exception: %s", str(e), exc_info=True)
        if DLQ_URL:
            try:
                logger.warning("Sending failed event to DLQ: %s", DLQ_URL)
                sqs.send_message(
                    QueueUrl=DLQ_URL,
                    MessageBody=json.dumps({
                        "error": str(e),
                        "originalEvent": event
                    })
                )
            except Exception as dlq_error:
                logger.error("Failed to send message to DLQ: %s", str(dlq_error))

        return {"statusCode": 500, "body": json.dumps({"error": str(e)})} 
    try:
        logger.info("Starting to replay failed events from DLQ...")
        replay_failed_events()
        logger.info("Finished replaying failed events.")
    except Exception as e:
        logger.error(f"Error while replaying failed events: {e}", exc_info=True)