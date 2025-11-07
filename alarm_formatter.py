import boto3
import json
import logging
import time
import re
from html import unescape
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError
from config_parser import SYSTEM_PROMPT
from mail_beautifier import convert_to_email_template
from serverhandler import lambda_handler as server_handler 
from constants import REGION, MODEL_ID

# Logger Configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------- Core Function ----------
def handle_alarm(
    prompt: str,
    ticket_subject: str,
    ticket_body: str,
    ticket_id: str,
    inference_profile_arn: str = MODEL_ID,
    max_retries: int = 7,
    retry_delay_seconds: int = 3,
    max_tokens: int = 25000,
    allow_html: bool = True
) -> str:
    session = boto3.Session(region_name=REGION)
    bedrock_runtime = session.client("bedrock-runtime")

    # Step 1: Fetch command output (Universal - detects OS and runs appropriate commands)
    try:
        logger.info("🔍 Extracting system analysis from ticket content")
        event = {
            "ticket_subject": ticket_subject,
            "ticket_body": ticket_body,
            "ticket_id": ticket_id
        }
        server_response = server_handler(event, context={})

        if server_response.get("status") == "success":
            tree_output = server_response.get("stdout", "")
            error_output = server_response.get("stderr", "")
        else:
            tree_output = f"[ERROR] {server_response.get('message', '')}"
            error_output = ""

        # Optional: Truncate output for logging
        log_tree_output = tree_output[:3000]
        log_error_output = error_output[:3000]

        logger.info("🖥️ UNIVERSAL SYSTEM ANALYSIS OUTPUT:\n" + log_tree_output)
        if error_output:
            logger.warning("⚠️ COMMAND EXECUTION ERRORS:\n" + log_error_output)

    except Exception as e:
        logger.error(f"Universal handler failed: {e}", exc_info=True)
        tree_output = "[ERROR] Failed to retrieve system analysis output"
        error_output = str(e)

    # Step 2: Inject command output into prompt with appropriate formatting
    prompt += (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🖥️ UNIVERSAL SYSTEM ANALYSIS OUTPUT\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{tree_output}"
    )
    if error_output:
        prompt += (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ COMMAND EXECUTION ERRORS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{error_output}"
        )

    # Step 3: Construct Bedrock request payload
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": f"{SYSTEM_PROMPT}\n\nUser Request:\n{prompt}"
        }]
    }

    # Step 4: Retry inference if needed
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(json.dumps({"event": "invoke_model_attempt", "attempt": attempt}))
            response = bedrock_runtime.invoke_model(
                modelId=inference_profile_arn,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )
            body_bytes = response["body"].read()
            body_str = body_bytes.decode("utf-8")
            body_json = json.loads(body_str)

            model_reply = ""
            content = body_json.get("content", [])
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    model_reply = first.get("text", "").strip()

            if allow_html:
                model_reply = convert_to_email_template(model_reply)

            return model_reply

        except (ClientError, EndpointConnectionError, ConnectionClosedError) as e:
            logger.error(json.dumps({"event": "invoke_model_error", "attempt": attempt, "error": str(e)}))
            if attempt == max_retries:
                break
            time.sleep(retry_delay_seconds * attempt)

        except Exception as e:
            logger.error(json.dumps({"event": "unexpected_error", "error": str(e)}))
            break

    # Step 5: Fallback response
    return (
        "Dear Sir/Ma'am,\n\n"
        "Greetings from Workmates Support! We encountered an unexpected issue while generating a response. "
        "Please be assured that our Workmates L2 engineer is reviewing the matter and will respond shortly.\n\n"
        "Best regards,\nWorkmates Support"
    )