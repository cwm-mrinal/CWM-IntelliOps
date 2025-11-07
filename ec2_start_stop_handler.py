import json
import re
import boto3
from datetime import datetime, timedelta
import uuid
import time
import logging
from cross_account_role import assume_role
from constants import ACCOUNT_TABLE_NAME
from constants import REGION, MODEL_ID

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region_map = {
    "Mumbai": "ap-south-1", "Hyderabad": "ap-south-2", "Osaka": "ap-northeast-3", "Seoul": "ap-northeast-2",
    "N. Virginia": "us-east-1", "Ohio": "us-east-2", "N. California": "us-west-1", "Oregon": "us-west-2",
    "Singapore": "ap-southeast-1", "Sydney": "ap-southeast-2", "Tokyo": "ap-northeast-1", "Canada": "ca-central-1",
    "Frankfurt": "eu-central-1", "Ireland": "eu-west-1", "London": "eu-west-2", "Paris": "eu-west-3",
    "Stockholm": "eu-north-1", "São Paulo": "sa-east-1"
}

session = boto3.Session(region_name=REGION)
bedrock_runtime = session.client("bedrock-runtime") 

SYSTEM_PROMPT = (
    "You are an expert IT assistant that extracts exactly three pieces of information from a user request:\n\n"
    
    "1) **Action**: Either 'start' or 'stop' indicating the requested action on an instance.\n"
    "2) **InstanceName**: The name of the target instance (typically a hyphenated word near the action).\n"
    "3) **ScheduleTime**: The time at which the action should occur, extracted in 12H or 24H formats (return as ISO 8601 if possible).\n\n"
    
    "## OUTPUT FORMAT:\n"
    "Respond with ONLY valid JSON in this exact structure:\n\n"
    "{\n"
    '  "Action": "start",\n'
    '  "InstanceName": "example-instance",\n'
    '  "ScheduleTime": "2025-07-04T14:00:00"\n'
    "}\n\n"
    
    "## RULES:\n"
    "- If action or instance name cannot be determined, leave the corresponding field as an empty string.\n"
    "- If time is not found, set ScheduleTime as an empty string.\n"
    "- Return ONLY the JSON response with these three fields.\n\n"
    
    "## MISSING INFORMATION HANDLING:\n"
    "If you cannot determine any of the required fields (Action, InstanceName, or ScheduleTime), respond with ONLY this question (no JSON):\n\n"
    "\"Can you please provide the missing information? Specifically, I need the action (start/stop), instance name, or schedule time.\"\n\n"
    
    "## VALIDATION CHECKLIST:\n"
    "Before responding, verify:\n"
    "✓ JSON syntax is valid\n"
    "✓ All three fields (Action, InstanceName, ScheduleTime) are included\n"
    "✓ No extra text outside the JSON block or question prompt"
)

def parse_time_string(time_str):
    time_str = time_str.strip().lower().replace('.', '')
    if time_str[-2:] in ('am', 'pm') and len(time_str) > 2 and time_str[-3] != ' ':
        time_str = time_str[:-2] + ' ' + time_str[-2:]

    formats = ['%I %p', '%I:%M %p', '%H:%M', '%H', '%H%M']
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None

def extract_details(message):
    """
    Extracts action, instance name, and schedule time from a free-form message using Claude first,
    then falls back to regex-based parsing.
    Returns dict with keys: InstanceName, Action, ScheduleTime.
    """

    inference_profile_arn = MODEL_ID
    max_retries = 3
    retry_delay_seconds = 2
    max_tokens = 3000

    logger.info("Starting extraction with Claude Sonnet via Bedrock for message: %s", message)

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": f"{SYSTEM_PROMPT}\n\nUser Request:\n{message}"
            }
        ]
    }

    # Try Claude first
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(json.dumps({"event": "invoke_model_attempt", "attempt": attempt}))

            response = bedrock_runtime.invoke_model(
                modelId=inference_profile_arn,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )

            response_body = json.loads(response["body"].read())
            model_text = response_body["content"][0]["text"]
            logger.info(json.dumps({"event": "model_raw_output", "text": model_text}))

            parsed = json.loads(model_text)

            action = parsed.get("Action", "").strip().lower()
            instance_name = parsed.get("InstanceName", "").strip()
            schedule_time = parsed.get("ScheduleTime", "").strip()

            # Ensure at least Action and InstanceName are non-empty or fallback
            if action or instance_name:
                logger.info("Successfully parsed via Claude: %s", json.dumps(parsed, indent=2))
                return {
                    "Action": action,
                    "InstanceName": instance_name,
                    "ScheduleTime": schedule_time
                }
            else:
                raise ValueError("Claude returned incomplete information")

        except Exception as e:
            logger.warning(json.dumps({
                "event": "invoke_model_error",
                "attempt": attempt,
                "error": str(e)
            }))
            if attempt == max_retries:
                logger.info("Claude failed after retries; falling back to regex parsing.")
            else:
                time.sleep(retry_delay_seconds)

    # Fallback: regex-based extraction
    logger.info("Fallback: parsing with regex.")

    # Action
    action_match = re.search(r'\b(start|stop)\b', message, re.IGNORECASE)
    action = action_match.group(1).lower() if action_match else ""

    # Instance name
    instance_name = ""
    if action:
        name_match = re.search(
            rf'{action}\s+(?:the\s+)?([\w\-]+)', message, re.IGNORECASE
        )
        if name_match:
            instance_name = name_match.group(1)

    # Schedule time
    schedule_time = ""
    time_match = re.search(
        r'\b(?:at|time\s*[:\-]?)\s*(\d{1,2}(:\d{2})?\s*(am|pm)?|\d{4})\b',
        message, re.IGNORECASE
    )
    if time_match:
        time_str = time_match.group(1)
        parsed_time = parse_time_string(time_str)
        if parsed_time:
            now = datetime.now()
            scheduled_datetime = now.replace(
                hour=parsed_time.hour, minute=parsed_time.minute,
                second=0, microsecond=0
            )
            if scheduled_datetime <= now:
                scheduled_datetime += timedelta(days=1)
            schedule_time = scheduled_datetime.isoformat()

    result = {
        "Action": action,
        "InstanceName": instance_name,
        "ScheduleTime": schedule_time
    }

    logger.info("Fallback extraction completed with result: %s", json.dumps(result, indent=2))
    return result


def find_instance_id_by_name(ec2_client, instance_name):
    filters = [{'Name': 'tag:Name', 'Values': [instance_name]}]
    try:
        response = ec2_client.describe_instances(Filters=filters)
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                return instance['InstanceId']
    except Exception as e:
        print(f"Error finding instance by name: {e}")
    return None


def schedule_self_invocation(event_details, schedule_time, region, context, session=None):
    session = session or boto3
    iam_client = session.client("iam")
    events_client = session.client("events", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)

    rule_name = f"ec2-schedule-{uuid.uuid4().hex[:8]}"
    dt = datetime.fromisoformat(schedule_time)
    cron_expr = f"cron({dt.minute} {dt.hour} {dt.day} {dt.month} ? {dt.year})"

    response = events_client.put_rule(Name=rule_name, ScheduleExpression=cron_expr, State='ENABLED')

    lambda_arn = context.invoked_function_arn
    role_name = f"{rule_name}-role"

    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }

    try:
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy_document),
            Description="Role to allow EventBridge to invoke Lambda"
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        pass

    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="InvokeLambdaPolicy",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": lambda_arn}]
        })
    )

    role_arn = iam_client.get_role(RoleName=role_name)['Role']['Arn']

    try:
        lambda_client.add_permission(
            FunctionName=lambda_arn,
            StatementId=f"{rule_name}-stmt",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=response["RuleArn"]
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass

    events_client.put_targets(
        Rule=rule_name,
        Targets=[{
            "Id": "1",
            "Arn": lambda_arn,
            "RoleArn": role_arn,
            "Input": json.dumps(event_details)
        }]
    )

    return rule_name


def extract_email(raw_email):
    match = re.search(r'[\w\.-]+@[\w\.-]+', raw_email)
    return match.group(0) if match else raw_email

def get_account_details_from_email(email):
    response = account_table.scan(
        FilterExpression="contains(CustomerEmailIds, :email)",
        ExpressionAttributeValues={":email": email}
    )
    for item in response.get("Items", []):
        return {
            "AccountId": item["AccountId"],
            "Regions": [r.strip() for r in item["Regions"].split(",") if r.strip()]
        }
    return None


def lambda_handler(event, context):
    message = event.get("message", "")
    body = event.get("body", {})
    from_emails = body.get("fromEmail", [])

    if not from_emails:
        return {
            "statusCode": 400,
            "status": "error",
            "message": "Hi! We couldn't process your request because 'fromEmail' is missing. Please include a sender email.",
            "error": "MissingFromEmail"
        }

    cleaned_emails = [extract_email(email) for email in from_emails]

    for clean_email in cleaned_emails:
        account_data = get_account_details_from_email(clean_email)
        if not account_data:
            continue

        account_id = account_data["AccountId"]
        regions = account_data["Regions"]

        extracted = extract_details(message)
        instance_name = extracted["InstanceName"]
        action = extracted["Action"]
        schedule_time = extracted["ScheduleTime"]

        if not instance_name or not action:
            return {
                "statusCode": 400,
                "status": "error",
                "message": f"Hello! Please include both instance name and the desired action (start/stop) in your message for email '{clean_email}'.",
                "error": "MissingDetails"
            }

        for region in regions:
            try:
                aws_region = region_map.get(region)
                if not aws_region:
                    continue

                session = assume_role(account_id)
                ec2 = session.client("ec2", region_name=aws_region)
                instance_id = find_instance_id_by_name(ec2, instance_name)

                if not instance_id:
                    continue

                extracted.update({
                    "AWSRegion": aws_region,
                    "AccountId": account_id
                })

                if schedule_time:
                    rule = schedule_self_invocation(extracted, schedule_time, aws_region, context, session)
                    return {
                        "statusCode": 202,
                        "status": "success",
                        "message": f"Hi there! Your request to **{action}** instance **{instance_name}** at **{schedule_time}** in **{region}** is scheduled successfully.",
                        "rule": rule,
                        "details": extracted
                    }

                # Get current instance state
                state_response = ec2.describe_instances(InstanceIds=[instance_id])
                current_state = state_response["Reservations"][0]["Instances"][0]["State"]["Name"]

                if action == "start":
                    if current_state == "running":
                        return {
                            "statusCode": 200,
                            "status": "info",
                            "message": f"Hi! The instance **{instance_name}** is already **running** in region **{region}**.",
                            "details": extracted
                        }
                    ec2.start_instances(InstanceIds=[instance_id])
                    return {
                        "statusCode": 200,
                        "status": "success",
                        "message": f"Hi! Your instance **{instance_name}** has been successfully **started** in region **{region}**.",
                        "details": extracted
                    }

                elif action == "stop":
                    if current_state == "stopped":
                        return {
                            "statusCode": 200,
                            "status": "info",
                            "message": f"Hi! The instance **{instance_name}** is already **stopped** in region **{region}**.",
                            "details": extracted
                        }
                    ec2.stop_instances(InstanceIds=[instance_id])
                    return {
                        "statusCode": 200,
                        "status": "success",
                        "message": f"Hi! Your instance **{instance_name}** has been successfully **stopped** in region **{region}**.",
                        "details": extracted
                    }

                else:
                    return {
                        "statusCode": 400,
                        "status": "error",
                        "message": f"Unsupported action: {action}",
                        "details": extracted
                    }


            except Exception as e:
                return {
                    "statusCode": 500,
                    "status": "error",
                    "message": f"Oops! Something went wrong while performing action in **{region}**. Please try again.",
                    "error": str(e),
                    "region": region,
                    "account_id": account_id
                }

    return {
        "statusCode": 404,
        "status": "error",
        "message": "Hi! We couldn't find any account linked to the provided 'fromEmail' values. Please ensure you're using a registered email address.",
        "emails": cleaned_emails
    }
