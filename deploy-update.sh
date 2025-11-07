#!/bin/bash

################################################################################
# Lambda Function UPDATE Script
# Updates EXISTING Lambda function - NO infrastructure creation
################################################################################

set -e

# Configuration - YOUR EXISTING RESOURCES
FUNCTION_NAME="Zoho-Automation-Lambda"
FUNCTION_ARN="arn:aws:lambda:ap-south-1:036160411876:function:Zoho-Automation-Lambda"
REGION="ap-south-1"
ACCOUNT_ID="036160411876"
DEPLOYMENT_PACKAGE="lambda-update.zip"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_info() { echo -e "${BLUE}ℹ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Lambda Function Update Deployment    ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo ""

# Verify AWS credentials
print_info "Verifying AWS credentials..."
if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials not configured"
    exit 1
fi
print_success "AWS credentials verified"

# Verify function exists
print_info "Verifying Lambda function exists..."
if ! aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &> /dev/null; then
    print_error "Lambda function $FUNCTION_NAME not found"
    exit 1
fi
print_success "Lambda function found"

# Get current function info
print_info "Current function configuration:"
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query '{Runtime:Runtime,Memory:MemorySize,Timeout:Timeout,LastModified:LastModified}' \
    --output table

# Clean old package
rm -f "$DEPLOYMENT_PACKAGE"

# Package Lambda function
print_info "Packaging Lambda function code..."
zip -r "$DEPLOYMENT_PACKAGE" \
    lambda_function.py \
    config.py \
    config_parser.py \
    config_manager.py \
    constants.py \
    shared_utils.py \
    security_utils.py \
    error_handler.py \
    prompt_library.py \
    aws_accounts.py \
    classifier.py \
    agent_invoker.py \
    language_utils.py \
    mail_handler.py \
    mail_formatter.py \
    mail_beautifier.py \
    zoho_integration.py \
    zoho_private_comment.py \
    zoho_alarm_pvt_comment.py \
    teams_integration.py \
    send_teams_webhook.py \
    first_response.py \
    ticket_assign.py \
    ticket_status.py \
    ticket_site_status.py \
    ticket_embeddings.py \
    account_restriction.py \
    alarm_formatter.py \
    monitor_alerts.py \
    parse_body.py \
    pattern_recognition.py \
    escalation_framework.py \
    escalation_mail.py \
    ec2_automation.py \
    ec2_start_stop_handler.py \
    ec2_scheduler.py \
    security_group_handler.py \
    iam_users.py \
    cross_account_role.py \
    serverhandler.py \
    check_site.py \
    close_ticket_status.py \
    search_similar_embeddings.py \
    replay_failed_events.py \
    -q 2>/dev/null || true

PACKAGE_SIZE=$(du -h "$DEPLOYMENT_PACKAGE" | cut -f1)
print_success "Package created: $DEPLOYMENT_PACKAGE ($PACKAGE_SIZE)"

# Update Lambda function code
print_info "Updating Lambda function code..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://"$DEPLOYMENT_PACKAGE" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

print_success "Code uploaded"

# Wait for update to complete
print_info "Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

print_success "Update completed"

# Publish new version
print_info "Publishing new version..."
NEW_VERSION=$(aws lambda publish-version \
    --function-name "$FUNCTION_NAME" \
    --description "Deployed on $(date '+%Y-%m-%d %H:%M:%S')" \
    --region "$REGION" \
    --query 'Version' \
    --output text)

print_success "Published version: $NEW_VERSION"

# Update production alias (if exists)
if aws lambda get-alias --function-name "$FUNCTION_NAME" --name production --region "$REGION" &> /dev/null; then
    print_info "Updating production alias..."
    aws lambda update-alias \
        --function-name "$FUNCTION_NAME" \
        --name production \
        --function-version "$NEW_VERSION" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    print_success "Production alias updated to version $NEW_VERSION"
fi

# Clean up
rm -f "$DEPLOYMENT_PACKAGE"

# Summary
echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Deployment Successful! ✓           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Function:${NC} $FUNCTION_NAME"
echo -e "${BLUE}Version:${NC}  $NEW_VERSION"
echo -e "${BLUE}Region:${NC}   $REGION"
echo -e "${BLUE}Time:${NC}     $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Test: aws lambda invoke --function-name $FUNCTION_NAME --region $REGION response.json"
echo "  2. Logs: aws logs tail /aws/lambda/$FUNCTION_NAME --follow --region $REGION"
echo "  3. Rollback: aws lambda update-alias --function-name $FUNCTION_NAME --name production --function-version <previous-version> --region $REGION"
echo ""

print_success "Deployment completed in $(date '+%H:%M:%S')"
