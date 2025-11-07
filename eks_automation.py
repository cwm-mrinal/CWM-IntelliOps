import boto3
import logging
import json
import subprocess
import yaml
import asyncio
import uuid
from botocore.exceptions import ClientError
from cross_account_role import assume_role
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME
from datetime import datetime

# Configure structured logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler()]
)

dynamodb = boto3.resource('dynamodb')
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)
config_table = dynamodb.Table('EKSConfigTable')

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
    "You are an expert EKS automation assistant. Your role is to assist with automating Amazon EKS tasks such as cluster upgrades, "
    "autoscaler setup, and deploying monitoring tools like Loki and Grafana. Provide precise, secure, and optimized configurations "
    "for EKS operations, ensuring compatibility with AWS best practices, secure IAM policies, and the specified region and account."
)

def validate_region(region):
    """Validate if the provided region is supported."""
    if region not in region_map.values():
        raise ValueError(f"Unsupported region: {region}. Supported regions: {list(region_map.values())}")

async def get_eks_client(account_id, role_name, region=REGION):
    """Assume role and return EKS client for the specified account and region."""
    try:
        validate_region(region)
        credentials = assume_role(account_id, role_name)
        eks_client = boto3.client(
            'eks',
            region_name=region,
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        logger.info({"event": "eks_client_created", "account_id": account_id, "region": region})
        return eks_client
    except Exception as e:
        logger.error({"event": "eks_client_creation_failed", "error": str(e), "account_id": account_id, "region": region})
        raise

async def validate_cluster_state(account_id, role_name, cluster_name, region=REGION):
    """Validate EKS cluster state before performing operations."""
    try:
        eks_client = await get_eks_client(account_id, role_name, region)
        response = eks_client.describe_cluster(name=cluster_name)
        cluster_status = response['cluster']['status']
        if cluster_status != 'ACTIVE':
            raise ValueError(f"Cluster {cluster_name} is not in ACTIVE state. Current state: {cluster_status}")
        logger.info({"event": "cluster_state_validated", "cluster_name": cluster_name, "status": cluster_status})
        return True
    except ClientError as e:
        logger.error({"event": "cluster_state_validation_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def store_config(account_id, cluster_name, config_type, config_data):
    """Store configuration in DynamoDB for auditing and rollback."""
    try:
        config_id = str(uuid.uuid4())
        config_table.put_item(
            Item={
                'ConfigId': config_id,
                'AccountId': account_id,
                'ClusterName': cluster_name,
                'ConfigType': config_type,
                'ConfigData': json.dumps(config_data),
                'Timestamp': datetime.utcnow().isoformat()
            }
        )
        logger.info({"event": "config_stored", "config_id": config_id, "cluster_name": cluster_name, "config_type": config_type})
        return config_id
    except Exception as e:
        logger.error({"event": "config_storage_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def upgrade_eks_cluster(account_id, role_name, cluster_name, version, region=REGION):
    """Upgrade an EKS cluster to a specified version with rollback support."""
    try:
        await validate_cluster_state(account_id, role_name, cluster_name, region)
        eks_client = await get_eks_client(account_id, role_name, region)
        
        current_config = eks_client.describe_cluster(name=cluster_name)
        config_id = await store_config(account_id, cluster_name, "cluster_version", {
            "version": current_config['cluster']['version']
        })
        
        response = eks_client.update_cluster_version(
            name=cluster_name,
            version=version
        )
        logger.info({
            "event": "cluster_upgrade_initiated",
            "cluster_name": cluster_name,
            "account_id": account_id,
            "target_version": version,
            "config_id": config_id
        })
        return response
    except ClientError as e:
        logger.error({"event": "cluster_upgrade_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def validate_autoscaler_config(config):
    """Validate cluster autoscaler configuration."""
    required_keys = ["minNodes", "maxNodes", "scaleDown"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required key in autoscaler config: {key}")
    if config["minNodes"] > config["maxNodes"]:
        raise ValueError("minNodes cannot be greater than maxNodes")
    return True

async def setup_eks_autoscaler(account_id, role_name, cluster_name, region=REGION, resource_config=None):
    """Set up cluster autoscaler for an EKS cluster with Bedrock validation."""
    try:
        await validate_cluster_state(account_id, role_name, cluster_name, region)
        autoscaler_config = await generate_autoscaler_config(cluster_name, resource_config)
        await validate_autoscaler_config(autoscaler_config)
        
        config_id = await store_config(account_id, cluster_name, "autoscaler", autoscaler_config)
        eks_client = await get_eks_client(account_id, role_name, region)
        
        logger.info({
            "event": "autoscaler_setup_initiated",
            "cluster_name": cluster_name,
            "account_id": account_id,
            "config_id": config_id,
            "config": autoscaler_config
        })
        return {"status": "Autoscaler setup initiated", "config_id": config_id, "config": autoscaler_config}
    except Exception as e:
        logger.error({"event": "autoscaler_setup_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def rollback_deployment(cluster_name, namespace, release_name):
    """Rollback a failed Helm deployment."""
    try:
        helm_command = ["helm", "rollback", release_name, "0", "--namespace", namespace]
        process = subprocess.run(helm_command, capture_output=True, text=True)
        if process.returncode != 0:
            raise RuntimeError(f"Rollback failed: {process.stderr}")
        logger.info({"event": "helm_rollback_success", "cluster_name": cluster_name, "release_name": release_name})
        return True
    except Exception as e:
        logger.error({"event": "helm_rollback_failed", "cluster_name": cluster_name, "release_name": release_name, "error": str(e)})
        raise

async def deploy_loki_grafana(account_id, role_name, cluster_name, namespace="monitoring", region=REGION, resource_config=None):
    """Deploy Loki and Grafana to an EKS cluster for logging and monitoring using Helm."""
    try:
        await validate_cluster_state(account_id, role_name, cluster_name, region)
        eks_client = await get_eks_client(account_id, role_name, region)
        
        helm_values = await generate_helm_values(account_id, cluster_name, namespace, resource_config)
        config_id = await store_config(account_id, cluster_name, "loki_grafana", helm_values)
        
        helm_command = [
            "helm", "upgrade", "--install", "loki-grafana", "grafana/loki-stack",
            "--namespace", namespace, "--create-namespace",
            "-f", "-"
        ]
        
        try:
            process = subprocess.run(
                helm_command,
                input=yaml.dump(helm_values),
                text=True,
                capture_output=True
            )
            if process.returncode != 0:
                await rollback_deployment(cluster_name, namespace, "loki-grafana")
                raise RuntimeError(f"Helm deployment failed: {process.stderr}")
            
            logger.info({
                "event": "loki_grafana_deployment_success",
                "cluster_name": cluster_name,
                "account_id": account_id,
                "namespace": namespace,
                "config_id": config_id
            })
            return {
                "status": f"Loki and Grafana deployment successful in {namespace}",
                "config_id": config_id,
                "helm_values": helm_values
            }
        except Exception as e:
            await rollback_deployment(cluster_name, namespace, "loki-grafana")
            raise
    except Exception as e:
        logger.error({"event": "loki_grafana_deployment_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def generate_autoscaler_config(cluster_name, resource_config=None):
    """Generate cluster autoscaler configuration using Bedrock, incorporating custom resource limits."""
    try:
        prompt = (
            f"{SYSTEM_PROMPT}\nGenerate a secure and optimized cluster autoscaler configuration for an EKS cluster named {cluster_name}. "
            f"Include settings for minNodes, maxNodes, scaleDown delay, and resource limits in JSON format."
        )
        if resource_config:
            prompt += f"\nIncorporate the following resource limits: {json.dumps(resource_config)}"
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "prompt": prompt,
                    "max_tokens": 500,
                    "temperature": 0.6
                })
            )
        )
        config = json.loads(response['body'].read().decode('utf-8'))
        
        # Apply default values and override with resource_config if provided
        default_config = {
            "minNodes": 1,
            "maxNodes": 10,
            "scaleDown": {"delay": "10m"},
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"}
            }
        }
        if resource_config:
            if "resources" in resource_config:
                default_config["resources"] = {**default_config["resources"], **resource_config["resources"]}
            for key in ["minNodes", "maxNodes", "scaleDown"]:
                if key in resource_config:
                    default_config[key] = resource_config[key]
        
        config = {**default_config, **(config or {})}
        logger.info({"event": "autoscaler_config_generated", "cluster_name": cluster_name, "config": config})
        return config
    except Exception as e:
        logger.error({"event": "autoscaler_config_generation_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def generate_helm_values(account_id, cluster_name, namespace, resource_config=None):
    """Generate Helm chart values for Loki and Grafana deployment, incorporating custom resource limits."""
    try:
        prompt = (
            f"{SYSTEM_PROMPT}\nGenerate a Helm values.yaml configuration for deploying Loki and Grafana to an EKS cluster named {cluster_name} "
            f"in namespace {namespace}. Include secure settings, persistence, resource limits, and IAM roles for AWS integration in YAML format."
        )
        if resource_config:
            prompt += f"\nIncorporate the following resource limits: {json.dumps(resource_config)}"
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "prompt": prompt,
                    "max_tokens": 1000,
                    "temperature": 0.6
                })
            )
        )
        values = yaml.safe_load(response['body'].read().decode('utf-8'))
        
        default_values = {
            "loki": {
                "persistence": {
                    "enabled": True,
                    "size": "10Gi",
                    "storageClass": "gp3"
                },
                "resources": {
                    "requests": {"cpu": "200m", "memory": "256Mi"},
                    "limits": {"cpu": "500m", "memory": "512Mi"}
                },
                "serviceAccount": {
                    "create": True,
                    "annotations": {
                        "eks.amazonaws.com/role-arn": f"arn:aws:iam::{account_id}:role/LokiServiceAccount"
                    }
                }
            },
            "grafana": {
                "persistence": {
                    "enabled": True,
                    "size": "5Gi",
                    "storageClass": "gp3"
                },
                "resources": {
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"cpu": "300m", "memory": "256Mi"}
                },
                "adminUser": "admin",
                "adminPassword": "securepassword",
                "serviceAccount": {
                    "create": True,
                    "annotations": {
                        "eks.amazonaws.com/role-arn": f"arn:aws:iam::{account_id}:role/GrafanaServiceAccount"
                    }
                }
            }
        }
        
        # Merge resource_config with default values if provided
        if resource_config:
            for component in ["loki", "grafana"]:
                if component in resource_config and "resources" in resource_config[component]:
                    default_values[component]["resources"] = {
                        **default_values[component]["resources"],
                        **resource_config[component]["resources"]
                    }
        
        values = {**default_values, **(values or {})}
        logger.info({"event": "helm_values_generated", "cluster_name": cluster_name, "namespace": namespace})
        return values
    except Exception as e:
        logger.error({"event": "helm_values_generation_failed", "cluster_name": cluster_name, "error": str(e)})
        raise

async def extract_parameters_with_llm(ticket_body):
    """Extract parameters from ticket_body using Bedrock LLM."""
    try:
        # Prepare prompt for LLM to extract parameters
        extraction_prompt = (
            f"{SYSTEM_PROMPT}\nYou are provided with a ticket_body that contains parameters for an EKS automation task. "
            "Your task is to extract the following parameters and return them in a JSON object: "
            "operation (string, required), role_name (string, required), cluster_name (string, required), "
            "region (string, optional), version (string, optional), namespace (string, optional), "
            "and resource_config (object, optional). "
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
                    "temperature": 0.3
                })
            )
        )

        # Parse LLM response
        extracted_data = json.loads(response['body'].read().decode('utf-8'))

        # Validate required parameters
        required_params = ['operation', 'role_name', 'cluster_name']
        missing_params = [param for param in required_params if param not in extracted_data]
        if missing_params:
            raise ValueError(f"LLM failed to extract required parameters: {', '.join(missing_params)}")

        # Set default values for optional parameters if not provided
        extracted_data.setdefault('region', REGION)
        extracted_data.setdefault('namespace', 'monitoring')

        logger.info({
            "event": "parameters_extracted",
            "extracted_data": extracted_data
        })
        return extracted_data

    except Exception as e:
        logger.error({
            "event": "parameter_extraction_failed",
            "error": str(e),
            "ticket_body": ticket_body
        })
        raise

async def lambda_handler(event, context):
    """AWS Lambda handler for EKS automation tasks with ticket_body and account_id."""
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
        cluster_name = params['cluster_name']
        region = params['region']
        version = params.get('version')
        namespace = params['namespace']
        resource_config = params.get('resource_config')
        
        # Validate operation
        valid_operations = ["upgrade_cluster", "setup_autoscaler", "deploy_loki_grafana"]
        if operation not in valid_operations:
            raise ValueError(f"Unsupported operation: {operation}. Supported operations: {valid_operations}")
        
        # Dispatch based on operation
        if operation == "upgrade_cluster":
            if not version:
                raise ValueError("Version is required for cluster upgrade")
            result = await upgrade_eks_cluster(account_id, role_name, cluster_name, version, region)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'Cluster upgrade initiated',
                    'cluster_name': cluster_name,
                    'version': version,
                    'details': result
                })
            }
        elif operation == "setup_autoscaler":
            result = await setup_eks_autoscaler(account_id, role_name, cluster_name, region, resource_config)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'Autoscaler setup initiated',
                    'cluster_name': cluster_name,
                    'config_id': result['config_id'],
                    'config': result['config']
                })
            }
        elif operation == "deploy_loki_grafana":
            result = await deploy_loki_grafana(account_id, role_name, cluster_name, namespace, region, resource_config)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'status': 'Loki and Grafana deployment initiated',
                    'cluster_name': cluster_name,
                    'namespace': namespace,
                    'config_id': result['config_id'],
                    'helm_values': result['helm_values']
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