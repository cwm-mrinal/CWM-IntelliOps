import json
import requests
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def send_to_teams_webhook(
    teams_url,
    subject,
    original_body,
    reply_text,
    account_id,
    account_name,
    team_name,
    ticket_id,
    team_id,
    image_analysis=None
):
    try:
        ticket_url = f"https://support.cloudworkmates.com/agent/workmates/managed-service/tickets/details/{ticket_id}"
        ticket_link = f"[🔗 View Ticket #{ticket_id}]({ticket_url})"

        message_card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": subject,
            "themeColor": "0076D7",
            "title": f"🛠️ Support Ticket: {subject}",
            "sections": [
                {
                    "activityTitle": f"👀 Attention {team_name}",
                    "text": f"A new ticket has been created for **{team_name}**.\n\n{ticket_link}\n\n🆔 **Team ID:** `{team_id}`"
                },
                {
                    "activityTitle": "📩 Customer Ticket",
                    "text": original_body
                },
                {
                    "activityTitle": "💬 Agent Reply",
                    "text": reply_text
                },
                {
                    "activityTitle": "📊 Account Details",
                    "facts": [
                        {"name": "🔐 Account ID", "value": account_id},
                        {"name": "🏷️ Account Name", "value": account_name},
                        {"name": "👥 Team Name", "value": team_name},
                        {"name": "🆔 Team ID", "value": team_id}
                    ]
                }
            ]
        }

        # ✅ Append Image Analysis section if available
        if image_analysis:
            message_card["sections"].append({
                "activityTitle": "🖼️ Image Analysis",
                "text": image_analysis
            })

        response = requests.post(
            teams_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(message_card)
        )

        response.raise_for_status()
        logger.info("Successfully sent message to Teams webhook.")

    except requests.exceptions.RequestException as e:
        logger.error("Failed to send to Teams webhook: %s", str(e), exc_info=True)
        raise 

def send_basic_teams_webhook(teams_url, subject, reply_text, team_name, ticket_id):
    try:
        ticket_url = f"https://support.cloudworkmates.com/agent/workmates/managed-service/tickets/details/{ticket_id}"
        ticket_link = f"[🔗 View Ticket #{ticket_id}]({ticket_url})"

        message_card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": subject,
            "themeColor": "0076D7",
            "title": f"🛠️ Support Ticket: {subject}",
            "sections": [
                {
                    "activityTitle": f"👀 Attention {team_name}",
                    "text": f"A new ticket has been created for **{team_name}**.\n\n{ticket_link}"
                },
                {
                    "activityTitle": "💬 Agent Reply",
                    "text": reply_text
                }
            ]
        }

        response = requests.post(
            teams_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(message_card)
        )

        response.raise_for_status()
        logger.info("Successfully sent basic message to Teams webhook.")

    except requests.exceptions.RequestException as e:
        logger.error("Failed to send basic Teams webhook: %s", str(e), exc_info=True)
        raise
