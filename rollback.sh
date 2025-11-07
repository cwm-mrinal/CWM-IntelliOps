#!/bin/bash

################################################################################
# Rollback Script
# Rollback Lambda function to a previous version
################################################################################

set -e

FUNCTION_NAME="Zoho-Automation-Lambda"
REGION="ap-south-1"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Lambda Rollback Script${NC}"
echo -e "${BLUE}================================${NC}"

# List recent versions
echo -e "\n${YELLOW}Recent Lambda versions:${NC}"
aws lambda list-versions-by-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --max-items 10 \
    --query 'Versions[*].[Version,LastModified,Description]' \
    --output table

# Get current version
CURRENT_VERSION=$(aws lambda get-alias \
    --function-name "$FUNCTION_NAME" \
    --name production \
    --region "$REGION" \
    --query 'FunctionVersion' \
    --output text 2>/dev/null || echo "No production alias")

echo -e "\n${GREEN}Current production version: ${CURRENT_VERSION}${NC}"

# Prompt for version to rollback to
read -p "Enter version number to rollback to (or 'cancel' to abort): " VERSION

if [ "$VERSION" = "cancel" ]; then
    echo -e "${YELLOW}Rollback cancelled${NC}"
    exit 0
fi

# Confirm rollback
read -p "Are you sure you want to rollback to version $VERSION? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${YELLOW}Rollback cancelled${NC}"
    exit 0
fi

# Update production alias
echo -e "\n${BLUE}Rolling back to version $VERSION...${NC}"
aws lambda update-alias \
    --function-name "$FUNCTION_NAME" \
    --name production \
    --function-version "$VERSION" \
    --region "$REGION" \
    --no-cli-pager

echo -e "${GREEN}✓ Rollback completed successfully!${NC}"
echo -e "${YELLOW}⚠ Please monitor CloudWatch Logs to ensure the rollback was successful${NC}"
