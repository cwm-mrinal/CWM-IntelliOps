import logging
from zoho_private_comment import lambda_handler as zoho_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handle_zoho(ticket_id, reply_text):
    try:
        payload = {"ticketId": ticket_id, "reply": reply_text}
        response = zoho_handler(payload)
        logger.info("Zoho handler response: %s", response)
        return {
            "status": "zoho_success",
            "ticketId": ticket_id,
            "zoho_response": response
        }
    except Exception as e:
        logger.error("Zoho integration error: %s", str(e))
        return {
            "status": "zoho_failed",
            "ticketId": ticket_id,
            "error": str(e)
        }
