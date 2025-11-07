import boto3
import json
import base64
import logging

logger = logging.getLogger()
bedrock = boto3.client("bedrock-agent-runtime")

def encode_session_id(session_id):
    return base64.urlsafe_b64encode(session_id.encode()).decode().rstrip("=")

def invoke_bedrock_agent(agent_arn, session_id, input_text, alias_id=None):
    agent_id = agent_arn.split("/")[-1]
    session_id = encode_session_id(session_id)

    response_stream = bedrock.invoke_agent(
        agentId=agent_id,
        agentAliasId=alias_id,
        sessionId=session_id,
        inputText=input_text
    )

    final_output = ""
    for event in response_stream["completion"]:
        chunk = event.get("chunk")
        if chunk and "bytes" in chunk:
            final_output += chunk["bytes"].decode("utf-8")

    try:
        return json.loads(final_output)
    except json.JSONDecodeError:
        logger.warning("Agent output not JSON.")
        return {"raw_response": final_output}
