# Zoho Automation Lambda Function - Technical Documentation

## 📋 Overview

**Function Name:** Zoho-Automation-Lambda  
**ARN:** `arn:aws:lambda:ap-south-1:036160411876:function:Zoho-Automation-Lambda`  
**Region:** ap-south-1 (Mumbai)  
**Runtime:** Python 3.11  
**Purpose:** Automated IT support ticket processing and AWS resource management

---

## 🎯 What This Lambda Function Does

This Lambda function is an intelligent automation system that processes IT support tickets from Zoho Desk and performs automated actions based on ticket content. It combines AI/ML capabilities with AWS service integrations to provide automated support responses and infrastructure management.

### Core Capabilities

1. **Intelligent Ticket Classification**
   - Uses AWS Bedrock (Claude AI) to classify tickets into categories
   - Categories: alarm, security, cost_optimization, custom, os
   - Confidence scoring and fallback logic

2. **Multi-Language Support**
   - Detects ticket language using AWS Comprehend
   - Translates non-English tickets to English using AWS Translate
   - Processes tickets in any language

3. **Automated AWS Resource Management**
   - EC2 instance start/stop operations
   - Security group rule modifications
   - IAM user creation and management
   - CloudWatch alarm processing

4. **AI-Powered Response Generation**
   - Generates professional email responses using AWS Bedrock
   - Context-aware responses based on ticket content
   - Includes troubleshooting steps and solutions

5. **Team Routing and Notifications**
   - Routes tickets to appropriate teams
   - Sends notifications via Microsoft Teams
   - Updates Zoho Desk ticket status and assignments

---

## 🏗️ Architecture

### Input
- **Trigger:** API Gateway webhook from Zoho Desk
- **Payload:** JSON containing ticket details (ID, subject, body, emails)

### Processing Flow
```
1. Receive ticket from Zoho Desk
2. Parse and validate ticket data
3. Extract AWS account ID from ticket
4. Validate account against whitelist (DynamoDB)
5. Classify ticket using AI (Bedrock)
6. Route based on classification:
   ├─ alarm → Process CloudWatch alarms
   ├─ security → Security analysis
   ├─ cost_optimization → Cost analysis
   ├─ custom → EC2/SG automation
   └─ os → OS-specific handling
7. Generate AI response
8. Send email reply to customer
9. Update ticket status in Zoho
10. Notify team via Microsoft Teams
```

### Output
- Email response to customer
- Updated Zoho Desk ticket
- Microsoft Teams notification
- CloudWatch logs

---

## 🔧 Key Components

### 1. Ticket Classification (`classifier.py`)
- **Purpose:** Categorize incoming tickets
- **Technology:** AWS Bedrock (Claude Sonnet)
- **Output:** Category + confidence score
- **Fallback:** Keyword-based classification

### 2. AWS Resource Automation

#### EC2 Management (`ec2_start_stop_handler.py`)
- Start/stop EC2 instances by name
- Schedule operations for future execution
- Cross-account support via STS role assumption
- AI-powered parameter extraction

#### Security Group Management (`security_group_handler.py`)
- Add/remove inbound/outbound rules
- Support for multiple ports and protocols
- Automatic validation and conflict detection
- AI-powered rule extraction

#### IAM User Management (`iam_users.py`)
- Create IAM users with policies
- Set up MFA requirements
- Generate temporary passwords
- Create access keys with rotation policies

### 3. CloudWatch Alarm Processing (`monitor_alerts.py`)
- Generates visual metric dashboards
- Attaches graphs to Zoho tickets
- Supports multiple AWS services (EC2, RDS, ALB, Lambda, S3)
- Shows alarm thresholds and annotations

### 4. AI Response Generation (`mail_handler.py`)
- Uses AWS Bedrock for response generation
- Professional, context-aware emails
- Includes troubleshooting steps
- Retry logic with exponential backoff

### 5. Team Routing (`teams_integration.py`)
- Matches customer email to team
- Fuzzy matching for email validation
- Sends adaptive cards to Microsoft Teams
- Fallback to Uptime Team

### 6. Account Validation (`account_restriction.py`)
- Validates AWS account IDs against whitelist
- Routes unsupported accounts to Uptime Team
- DynamoDB-based validation

---

## 🗄️ AWS Resources Used

### DynamoDB Tables

#### CWM-Account-Details-Table
```json
{
  "AccountId": "123456789012",
  "AccountName": "Customer Corp",
  "CustomerEmailIds": "admin@customer.com",
  "Regions": "Mumbai,N. Virginia",
  "TeamName": "Enterprise Linux Team",
  "Zoho_Account_Id": "zoho-123456"
}
```

#### CWM-Account-Restriction-Table
```json
{
  "AccountId": "123456789012"
}
```

#### CWM-Ticket-Embeddings-Table
```json
{
  "ticketId": "12345",
  "ticketSubject": "Server down",
  "ticketBody": "Cannot connect...",
  "response": "AI-generated response",
  "embedding": [0.123, 0.456, ...],
  "timestamp": "2025-01-07T10:00:00Z"
}
```

### Secrets Manager
**Secret:** `zoho-automation-secrets-sMdisV`

Contains:
- Zoho OAuth tokens
- AWS Bedrock agent ARNs
- Team IDs
- API credentials

### AWS Services Integration
- **Bedrock:** AI/ML for classification and response generation
- **Comprehend:** Language detection
- **Translate:** Multi-language support
- **STS:** Cross-account access
- **CloudWatch:** Alarm processing and metrics
- **EventBridge:** Scheduled operations
- **SQS:** Dead letter queue for failed events
- **IAM:** User management

---

## 🔄 Workflow Examples

### Example 1: CloudWatch Alarm Ticket
```
1. Alarm triggers → SNS → Zoho Desk → Webhook → Lambda
2. Extract: AccountId, Region, InstanceId, Metric, Threshold
3. Classification: "alarm" (confidence: 0.95)
4. Generate CloudWatch dashboard image
5. Attach image to Zoho ticket
6. AI analyzes alarm and generates response
7. Send email to customer
8. Notify Uptime Team via Microsoft Teams
9. Update ticket status to "Assigned"
```

### Example 2: EC2 Start Request
```
1. Customer emails: "Please start prod-web-server at 6 PM"
2. Classification: "custom" (confidence: 0.85)
3. AI extracts: Action=start, InstanceName=prod-web-server, Time=18:00
4. Validate customer email → Lookup AccountId
5. Assume role in customer account
6. Find instance by name tag
7. Schedule EventBridge rule for 6 PM
8. Send confirmation email
9. At 6 PM: EventBridge triggers Lambda → Starts instance
10. Send completion email
```

### Example 3: Security Group Modification
```
1. Customer: "Add port 443 inbound to sg-abc123 from 0.0.0.0/0"
2. Classification: "custom" (confidence: 0.80)
3. AI extracts: Ports=[443], Direction=inbound, SG=sg-abc123, CIDR=0.0.0.0/0
4. Validate account and assume role
5. Check if rule already exists
6. Add security group rule
7. Generate confirmation response
8. Send email reply
9. Notify team via Microsoft Teams
```

---

## 🔐 Security Features

### Authentication & Authorization
- OAuth 2.0 for Zoho Desk API
- STS role assumption for cross-account access
- IAM roles with least privilege
- Secrets stored in AWS Secrets Manager

### Data Protection
- Automatic masking of sensitive data in logs
- No passwords logged in plaintext
- Encrypted secrets at rest
- Secure password generation

### Access Control
- Account whitelist validation
- Email-based customer verification
- Team-based access control
- Cross-account role with external ID

---

## 📊 Monitoring & Logging

### CloudWatch Logs
- Structured JSON logging
- Request ID correlation
- Sensitive data masking
- Error tracking with stack traces

### CloudWatch Metrics
- Invocations
- Duration
- Errors
- Throttles
- Concurrent executions

### CloudWatch Alarms
- Error rate > 5%
- Duration > 50 seconds
- Throttles > 0

---

## 🎯 Performance Characteristics

- **Memory:** 2048 MB (recommended)
- **Timeout:** 60 seconds
- **Cold Start:** 3-5 seconds
- **Warm Execution:** 5-10 seconds
- **Concurrent Executions:** Unlimited (account limit)

---

## 🔄 Error Handling

### Retry Logic
- Exponential backoff for AWS API calls
- Maximum 3 retries for Bedrock calls
- Automatic token refresh for Zoho API

### Dead Letter Queue
- Failed events sent to SQS DLQ
- Replay mechanism for failed events
- Error context preserved

### Rollback Manager
- Transaction-like operations
- LIFO rollback execution
- Context storage for state management

---

## 📝 Configuration

### Environment Variables
- `AWS_REGION`: ap-south-1

### Constants (from Secrets Manager)
- Agent ARNs and aliases
- Team IDs
- DynamoDB table names
- Model IDs
- Organization ID

---

## 🚀 Scalability

### Current Capacity
- Handles 100+ tickets per day
- Supports multiple AWS accounts
- Processes tickets in any language
- Concurrent execution support

### Scaling Considerations
- Add provisioned concurrency for consistent traffic
- Implement caching for DynamoDB lookups
- Use Lambda layers for dependencies
- Consider Step Functions for complex workflows

---

## 📞 Integration Points

### Zoho Desk
- Webhook trigger
- Email reply API
- Private comment API
- Ticket status update API
- Team assignment API

### Microsoft Teams
- Webhook notifications
- Adaptive cards
- Team-specific channels

### AWS Services
- Bedrock (AI/ML)
- EC2 (instance management)
- CloudWatch (monitoring)
- IAM (user management)
- DynamoDB (data storage)
- Secrets Manager (credentials)

---

## 🎓 Key Technologies

- **Python 3.11:** Core runtime
- **AWS Bedrock:** AI/ML capabilities
- **AWS Lambda:** Serverless compute
- **DynamoDB:** NoSQL database
- **API Gateway:** HTTP endpoint
- **EventBridge:** Scheduled operations

---

## 📈 Future Enhancements

- Machine learning model training for better classification
- GraphQL API for flexible queries
- Admin dashboard for monitoring
- Custom metrics for business KPIs
- Multi-region deployment
- Enhanced caching layer

---

**Last Updated:** January 7, 2025  
**Version:** 1.0  
**Maintained By:** CloudWorkMates DevOps Team (CWM x Mrinal)
