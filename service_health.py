import boto3
import json
import logging
from typing import Dict, Any
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
from cross_account_role import assume_role
from constants import REGION, MODEL_ID, ACCOUNT_TABLE_NAME

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
bedrock_runtime = boto3.client('bedrock-runtime', region_name=REGION)
account_table = dynamodb.Table(ACCOUNT_TABLE_NAME)

SYSTEM_PROMPT = (
    "You are an IT automation assistant specializing in AWS infrastructure. Analyze the provided diagnostic data, ticket details, and AWS Health Dashboard status for multiple AWS services (EC2, CloudWatch, DynamoDB, RDS, S3, Lambda). "
    "Provide a comprehensive health summary with the following: "
    "- A 'summary' field with a concise description of the overall health status, integrating resource-specific diagnostics and AWS service health. "
    "- An 'issues' field listing identified problems, including resource-specific issues and any relevant AWS service disruptions from the Health Dashboard. "
    "- Correlate AWS Health Dashboard disruptions with resource diagnostics and ticket details to identify potential impacts. "
    "Return the response as a JSON object."
)

class ServiceHealthMonitor:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.session = assume_role(account_id)
        self.cloudwatch_client = self.session.client('cloudwatch')
        self.ec2_client = self.session.client('ec2')
        self.rds_client = self.session.client('rds')
        self.s3_client = self.session.client('s3')
        self.lambda_client = self.session.client('lambda')
        self.health_client = self.session.client('health', region_name='us-east-1')
    
    def get_aws_service_health(self) -> Dict:
        """Fetch AWS Health Dashboard status for relevant services."""
        try:
            response = self.health_client.describe_events(
                filter={
                    'services': ['EC2', 'CLOUDWATCH', 'DYNAMODB', 'RDS', 'S3', 'LAMBDA'],
                    'eventStatusCodes': ['open', 'upcoming'],
                    'regions': [REGION]
                }
            )
            health_issues = []
            for event in response.get('events', []):
                health_issues.append({
                    'service': event.get('service'),
                    'status': event.get('eventStatusCode'),
                    'description': event.get('eventDescription', {}).get('latestDescription'),
                    'start_time': event.get('startTime', '').strftime('%Y-%m-%d %H:%M:%S') if event.get('startTime') else None
                })
            return {"service_health": health_issues}
        except ClientError as e:
            logger.error(f"Failed to fetch AWS Health Dashboard data: {str(e)}")
            return {"service_health": []}
    
    def analyze_diagnostics(self, diagnostics: Dict, ticket_body: str, ticket_subject: str) -> Dict:
        """Analyze diagnostics and AWS service health using Bedrock AI."""
        try:
            account_details = account_table.get_item(Key={'AccountId': self.account_id}).get('Item', {})
            context = f"Account: {account_details.get('AccountName', 'Unknown')}, Regions: {account_details.get('Regions', [])}"
            
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 12000,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{SYSTEM_PROMPT}\n\nContext: {context}\nDiagnostics: {json.dumps(diagnostics)}\nTicket Subject: {ticket_subject}\nTicket Body: {ticket_body}"
                    }
                ]
            }
            
            response = self.bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(payload).encode("utf-8")
            )
            response_body = json.loads(response["body"].read())
            return json.loads(response_body["content"][0]["text"])
        except Exception as e:
            logger.error(f"Failed to analyze diagnostics: {str(e)}")
            return {"summary": "Analysis failed", "issues": []}
    
    def check_service_health(self, resource_id: str, ticket_body: str, ticket_subject: str, resource_type: str = "instance") -> Dict[str, Any]:
        """Performs diagnostic checks on specified resources and AWS services."""
        try:
            diagnostics = {}
            
            # Fetch AWS Health Dashboard data
            diagnostics.update(self.get_aws_service_health())
            
            # Resource-specific diagnostics
            if resource_type == "instance":
                response = self.ec2_client.describe_instance_status(InstanceIds=[resource_id])
                diagnostics["instance_status"] = response.get('InstanceStatuses', [{}])[0].get('InstanceStatus', {}).get('Status', 'unknown')
                
                metrics = self.cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/EC2',
                    MetricName='CPUUtilization',
                    Dimensions=[{'Name': 'InstanceId', 'Value': resource_id}],
                    StartTime=datetime.utcnow() - timedelta(minutes=30),
                    EndTime=datetime.utcnow(),
                    Period=300,
                    Statistics=['Average']
                )
                diagnostics["cpu_utilization"] = metrics['Datapoints'][-1]['Average'] if metrics['Datapoints'] else None
            
            elif resource_type == "rds":
                response = self.rds_client.describe_db_instances(DBInstanceIdentifier=resource_id)
                diagnostics["rds_status"] = response.get('DBInstances', [{}])[0].get('DBInstanceStatus', 'unknown')
                
                metrics = self.cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/RDS',
                    MetricName='CPUUtilization',
                    Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': resource_id}],
                    StartTime=datetime.utcnow() - timedelta(minutes=30),
                    EndTime=datetime.utcnow(),
                    Period=300,
                    Statistics=['Average']
                )
                diagnostics["rds_cpu_utilization"] = metrics['Datapoints'][-1]['Average'] if metrics['Datapoints'] else None
            
            elif resource_type == "s3":
                response = self.s3_client.list_buckets()
                bucket_exists = any(bucket['Name'] == resource_id for bucket in response.get('Buckets', []))
                diagnostics["s3_status"] = "available" if bucket_exists else "not_found"
            
            elif resource_type == "lambda":
                response = self.lambda_client.get_function(FunctionName=resource_id)
                diagnostics["lambda_status"] = response.get('Configuration', {}).get('State', 'unknown')
                
                metrics = self.cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/Lambda',
                    MetricName='Invocations',
                    Dimensions=[{'Name': 'FunctionName', 'Value': resource_id}],
                    StartTime=datetime.utcnow() - timedelta(minutes=30),
                    EndTime=datetime.utcnow(),
                    Period=300,
                    Statistics=['Sum']
                )
                diagnostics["lambda_invocations"] = metrics['Datapoints'][-1]['Sum'] if metrics['Datapoints'] else None
            
            analysis = self.analyze_diagnostics(diagnostics, ticket_body, ticket_subject)
            logger.info(f"Service health check completed for {resource_id}: {diagnostics}, Analysis: {analysis}")
            return {"status": "success", "diagnostics": diagnostics, "analysis": analysis}
        
        except ClientError as e:
            logger.error(f"Service health check failed: {str(e)}")
            return {"status": "error", "message": str(e)}