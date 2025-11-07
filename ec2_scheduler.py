import boto3
import json
import logging
import re
import time
import requests
import urllib.parse
from typing import Optional
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError
from messager import SYSTEM_PROMPT
from mail_formatter import convert_to_email_template
from constants import REGION, MODEL_ID

# Logger Configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handle_message(
    prompt: str,
    inference_profile_arn: str = MODEL_ID,
    max_retries: int = 7,
    retry_delay_seconds: int = 3,
    max_tokens: int = 25000,
    allow_html: bool = True
) -> str:
    session = boto3.Session(region_name=REGION)
    bedrock_runtime = session.client("bedrock-runtime")

    
    combined_prompt = f"{SYSTEM_PROMPT}\n\nUser Request:\n{prompt}"

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": combined_prompt}]
    }

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(json.dumps({"event": "invoke_model_attempt", "attempt": attempt}))
            response = bedrock_runtime.invoke_model(
                modelId=inference_profile_arn,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )
            model_reply = json.loads(response["body"].read().decode("utf-8")).get("content", [])[0].get("text", "").strip()
            
            if allow_html:
                model_reply = convert_to_email_template(model_reply) 

            feedback_link = (
                "<br><br>-------------------------------------------------------<br>"
                "We'd love your feedback to improve our support experience.<br>"
                "Please take a moment to fill out this quick feedback form:<br>"
                '🗒<a href="http://zoho-uptime-automation-assets-bucket.s3-website.ap-south-1.amazonaws.com" '
                'target="_blank" rel="noopener noreferrer">Click Here</a>'
            )

            return model_reply + feedback_link

        except (ClientError, EndpointConnectionError, ConnectionClosedError) as e:
            logger.error(json.dumps({"event": "invoke_model_error", "attempt": attempt, "error": str(e)}))
            if attempt == max_retries:
                break
            time.sleep(retry_delay_seconds * attempt)

        except Exception as e:
            logger.error(json.dumps({"event": "unexpected_error", "error": str(e)}))
            break

    return (
        "Dear Sir/Ma'am,\n\n"
        "Greetings from Workmates Support! We encountered an unexpected issue while generating a response. "
        "Please be assured that our Workmates L2 engineer is reviewing the matter and will respond shortly.\n\n"
        "Best regards,\nWorkmates Support"
    )