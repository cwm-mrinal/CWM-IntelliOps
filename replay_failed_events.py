import boto3
import json
import logging
import time
from constants import DLQ_URL, LAMBDA_HANDLER_ARN

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client("sqs")
lambda_client = boto3.client("lambda")

def replay_failed_events(max_messages=10):
    """
    Reads failed messages from the DLQ, invokes the main Lambda with the original event,
    and deletes message if processed successfully.
    """
    logger.info(f"Checking DLQ for messages: {DLQ_URL}")

    while True:
        response = sqs.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=1,
            VisibilityTimeout=30,
        )

        messages = response.get("Messages", [])
        if not messages:
            logger.info("No messages found in DLQ.")
            break

        for msg in messages:
            receipt_handle = msg["ReceiptHandle"]
            body = msg.get("Body", "{}")
            try:
                payload = json.loads(body)
            except Exception as e:
                logger.error(f"Failed to parse DLQ message body: {e}, body: {body}")
                # Delete malformed message to avoid retry loops
                sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=receipt_handle)
                continue

            # Extract originalEvent from DLQ message, or use full payload if missing
            original_event = payload.get("originalEvent") or payload

            try:
                logger.info(f"Replaying event to Lambda: {original_event}")
                invoke_response = lambda_client.invoke(
                    FunctionName=LAMBDA_HANDLER_ARN,
                    InvocationType='Event',
                    Payload=json.dumps(original_event).encode()
                )
                status_code = invoke_response.get("StatusCode")
                if status_code == 202:
                    logger.info(f"Successfully invoked Lambda for DLQ message, deleting from DLQ")
                    sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=receipt_handle)
                else:
                    logger.warning(f"Lambda invoke returned status code {status_code}, not deleting message.")
            except Exception as e:
                logger.error(f"Failed to invoke Lambda with DLQ message: {e}", exc_info=True)

        # Optional: small delay to avoid throttling
        time.sleep(5)
