import boto3
import logging
import json
import asyncio
from botocore.exceptions import ClientError
from cross_account_role import assume_role
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler()]
)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

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
    "You are an expert EC2 automation assistant. Your role is to assist with automating Amazon EC2 tasks such as launching instances, "
    "terminating instances, and optimizing instance configurations. Provide secure, cost-effective, and optimized configurations "
    "for EC2 operations, ensuring compliance with AWS best practices and the specified region and account."
)

async def validate_region(region):
    """Validate if the provided region is supported."""
    if region not in region_map.values():
        raise ValueError(f"Unsupported region: {region}. Supported regions: {list(region_map.values())}")

async def get_ec2_client(account_id, role_name, region=REGION):
    """Assume role and return EC2 client for the specified account and region."""
    try:
        await validate_region(region)
        credentials = assume_role(account_id, role_name)
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        logger.info({"event": "ec2_client_created", "account_id": account_id, "region": region})
        return ec2_client
    except Exception as e:
        logger.error({"event": "ec2_client_creation_failed", "error": str(e), "account_id": account_id, "region": region})
        raise

async def validate_instance_config(account_id, instance_type, ami_id, subnet_id, security_group_ids, resource_config=None):
    """Validate EC2 instance configuration using Bedrock."""
    try:
        prompt = (
            f"{SYSTEM_PROMPT}\nValidate the following EC2 configuration for security and optimization in account {account_id}:\n"
            f"Instance Type: {instance_type}, AMI ID: {ami_id}, Subnet ID: {subnet_id}, "
            f"Security Group IDs: {security_group_ids}"
        )
        if resource_config:
            prompt += f"\nIncorporate the following resource configuration: {json.dumps(resource_config)}"
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "prompt": prompt,
                    "max_tokens": 500,
                    "temperature": 0.7
                })
            )
        )
        config_validation = json.loads(response['body'].read().decode('utf-8'))
        
        # Apply default configuration and merge with resource_config if provided
        default_config = {
            "instance_type": instance_type,
            "ami_id": ami_id,
            "subnet_id": subnet_id,
            "security_group_ids": security_group_ids,
            "tags": [{"Key": "Environment", "Value": "Production"}]
        }
        if resource_config and "tags" in resource_config:
            default_config["tags"] = resource_config["tags"]
        
        config_validation = {**default_config, **(config_validation or {})}
        logger.info({"event": "instance_config_validated", "account_id": account_id, "config": config_validation})
        return config_validation
    except Exception as e:
        logger.error({"event": "instance_config_validation_failed", "account_id": account_id, "error": str(e)})
        raise

async def launch_ec2_instance(account_id, role_name, instance_type, ami_id, subnet_id, security_group_ids, region=REGION, resource_config=None):
    """Launch an EC2 instance with Bedrock-validated parameters."""
    try:
        # Validate instance configuration using Bedrock
        instance_config = await validate_instance_config(account_id, instance_type, ami_id, subnet_id, security_group_ids, resource_config)
        ec2_client = await get_ec2_client(account_id, role_name, region)
        response = ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SubnetId=subnet_id,
            SecurityGroupIds=security_group_ids,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': instance_config.get("tags", [])
            }]
        )
        instance_id = response['Instances'][0]['InstanceId']
        logger.info({
            "event": "ec2_instance_launched",
            "instance_id": instance_id,
            "account_id": account_id,
            "config": instance_config
        })
        return {"InstanceId": instance_id, "config": instance_config}
    except Exception as e:
        logger.error({"event": "ec2_instance_launch_failed", "account_id": account_id, "error": str(e)})
        raise

async def terminate_ec2_instance(account_id, role_name, instance_id, region=REGION):
    """Terminate a specified EC2 instance."""
    try:
        ec2_client = await get_ec2_client(account_id, role_name, region)
        response = ec2_client.terminate_instances(InstanceIds=[instance_id])
        logger.info({"event": "ec2_instance_terminated", "instance_id": instance_id, "account_id": account_id})
        return response
    except ClientError as e:
        logger.error({"event": "ec2_instance_termination_failed", "instance_id": instance_id, "account_id": account_id, "error": str(e)})
        raise

async def extract_parameters_with_llm(ticket_body):
    """Extract parameters from ticket_body using Bedrock LLM."""
    try:
        # Prepare prompt for LLM to extract parameters
        extraction_prompt = (
            f"{SYSTEM_PROMPT}\nYou are provided with a ticket_body that contains parameters for an EC2 automation task. "
            "Your task is to extract the following parameters and return them in a JSON object: "
            "operation (string, required), role_name (string, required), instance_type (string, optional), "
            "ami_id (string, optional), subnet_id (string, optional), security_group_ids (list of strings, optional), "
            "instance_id (string, optional), region (string, optional), and resource_config (object, optional). "
            "If a parameter is missing, do not include it in the output unless specified otherwise. "
            "If the input is a JSON string, parse it. If it's unstructured text, interpret it logically. "
            f"Input ticket_body: {ticket_body}\n"
            "Return the extracted parameters in JSON format."
        )

        # Call Bedrock model
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "prompt": extraction_prompt,
                    "max_tokens": 500,
                    "temperature": 0.3  # Lower temperature for precise extraction
                })
            )
        )

        # Parse LLM response
        extracted_data = json.loads(response['body'].read().decode('utf-8'))

        # Validate required parameters
        required_params = ['operation', 'role_name']
        missing_params = [param for param in required_params if param not in extracted_data]
        if missing_params:
            raise ValueError(f"LLM failed to extract required parameters: {', '.join(missing_params)}")

        # Additional validation for launch_instance operation
        if extracted_data['operation'] == "launch_instance":
            launch_required = ['instance_type', 'ami_id', 'subnet_id', 'security_group_ids']
            missing_launch_params = [param for param in launch_required if param not in extracted_data]
            if missing_launch_params:
                raise ValueError(f"Missing required parameters for launch_instance: {', '.join(missing_launch_params)}")
        
        # Additional validation for terminate_instance operation
        if extracted_data['operation'] == "terminate_instance":
            if 'instance_id' not in extracted_data:
                raise ValueError("Missing required parameter for terminate_instance: instance_id")

        # Set default value for region if not provided
        extracted_data.setdefault('region', REGION)

        logger.info({"event": "parameters_extracted", "extracted_data": extracted_data})
        return extracted_data

    except Exception as e:
        logger.error({"event": "parameter_extraction_failed", "error": str(e), "ticket_body": ticket_body})
        raise

async def lambda_handler(event, context):
    """AWS Lambda handler for EC2 automation tasks with ticket_body and account_id."""
    try:
        logger.info({"event": "lambda_invoked", "request_id": context.aws_request_id, "event_data": event})
        
        # Extract ticket_body and account_id
        ticket_body = event.get('ticket_body')
        account_id = event.get('account_id')
        
        if not ticket_body or not account_id:
            raise ValueError("Missing required parameters: ticket_body, account_id")
        
        # Extract parameters using LLM
        params = await extract_parameters_with_llm(ticket_body)
        
        # Assign extracted parameters
        operation = params['operation']
        role_name = params['role_name']
        region = params['region']
        instance_type = params.get('instance_type')
        ami_id = params.get('ami_id')
        subnet_id = params.get('subnet_id')
        security_group_ids = params.get('security_group_ids')
        instance_id = params.get('instance_id')
        resource_config = params.get('resource_config')
        
        # Validate operation
        valid_operations = ["launch_instance", "terminate_instance"]
        if operation not in valid_operations:
            raise ValueError(f"Unsupported operation: {operation}. Supported operations: {valid_operations}")
        
        # Dispatch based on operation
        if operation == "launch_instance":
            result = await launch_ec2_instance(
                account_id, role_name, instance_type, ami_id, subnet_id, security_group_ids, region, resource_config
            )
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'EC2 instance launch initiated',
                    'instance_id': result['InstanceId'],
                    'config': result['config']
                })
            }
        elif operation == "terminate_instance":
            result = await terminate_ec2_instance(account_id, role_name, instance_id, region)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'EC2 instance termination initiated',
                    'instance_id': instance_id,
                    'details': result
                })
            }
    except Exception as e:
        logger.error({
            "event": "lambda_execution_failed",
            "request_id": context.aws_request_id,
            "error": str(e)
        })
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'Error',
                'error': str(e)
            })
        }