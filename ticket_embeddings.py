import boto3
import uuid
import datetime
from constants import EMBED_TABLE_NAME
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(EMBED_TABLE_NAME)

# Configuration
days_threshold = 365

def delete_old_items():
    """
    Delete items older than the configured days_threshold (365 days).

    Returns:
        dict: Status and count of deleted items
    """
    try:
        # Calculate cutoff date
        cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days_threshold)
        cutoff_timestamp = cutoff_date.isoformat()
        
        deleted_count = 0
        
        # Scan the table for old items
        scan_kwargs = {
            'FilterExpression': Attr('timestamp').lt(cutoff_timestamp)
        }
        
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            # Delete items in batch
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'id': item['id']})
                    deleted_count += 1
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        return {
            "status": "success", 
            "deletedCount": deleted_count,
            "cutoffDate": cutoff_timestamp
        }
        
    except Exception as e:
        return {"status": "error", "errorMessage": str(e)}

def save_bedrock_response(ticket_id, ticket_subject, ticket_body, response_data, source="bedrock", auto_cleanup=True):
    """
    Save ticket data and Bedrock response to DynamoDB.
    Optionally performs cleanup of items older than 14 days.
    
    Args:
        ticket_id: ID of the ticket
        ticket_subject: Subject of the ticket
        ticket_body: Body content of the ticket
        response_data: Response data from Bedrock
        source: Source identifier (default: "bedrock")
        auto_cleanup: Whether to automatically clean up old items (default: True)
    
    Returns:
        dict: Combined result of save and cleanup operations
    """
    try:
        item = {
            "id": str(uuid.uuid4()),
            "ticketId": ticket_id,
            "ticketSubject": ticket_subject,
            "ticketBody": ticket_body,
            "response": response_data,
            "source": source,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        table.put_item(Item=item)
        
        save_result = {"status": "success", "savedItem": item}
        
        # Perform cleanup if enabled
        if auto_cleanup:
            cleanup_result = delete_old_items()
            return {
                "save": save_result,
                "cleanup": cleanup_result
            }
        
        return save_result
        
    except Exception as e:
        return {"status": "error", "errorMessage": str(e)}