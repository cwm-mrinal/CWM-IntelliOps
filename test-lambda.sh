#!/bin/bash

################################################################################
# Lambda Testing Script
# Test Lambda function with various scenarios
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

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

test_alarm_ticket() {
    print_header "Test 1: CloudWatch Alarm Ticket"
    
    cat > /tmp/test-alarm.json <<'EOF'
{
  "body": "{\"ticketId\":\"TEST-ALARM-001\",\"ticketSubject\":\"ALARM: High CPU on i-1234567890abcdef0 in Mumbai\",\"ticketBody\":\"You are receiving this email because your Amazon CloudWatch Alarm \\\"High-CPU-Alert\\\" in the Asia Pacific (Mumbai) region has entered the ALARM state.\\n\\nAWS Account: 123456789012\\n\\nAlarm Details:\\n- Name: High-CPU-Alert\\n- Description: Alert when CPU exceeds 85%\\n- State Change: OK -> ALARM\\n- Reason: Threshold Crossed: 1 datapoint [92.5 (07/01/25 10:00:00)] was greater than or equal to the threshold (85.0).\\n\\nMetricNamespace: AWS/EC2\\nMetricName: CPUUtilization\\nDimensions: [{'name': 'InstanceId', 'value': 'i-1234567890abcdef0'}]\\nPeriod: 300 seconds\\nStatistic: Average\\nUnit: Percent\\nThreshold: GreaterThanOrEqualToThreshold 85.0\",\"fromEmail\":[\"customer@example.com\"],\"toEmail\":[\"support@cloudworkmates.com\"],\"ccEmail\":[]}"
}
EOF
    
    echo -e "${YELLOW}Invoking Lambda with alarm ticket...${NC}"
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload file:///tmp/test-alarm.json \
        --region "$REGION" \
        /tmp/response-alarm.json \
        --no-cli-pager
    
    echo -e "${GREEN}Response:${NC}"
    cat /tmp/response-alarm.json | python3 -m json.tool
    echo ""
}

test_ec2_start_ticket() {
    print_header "Test 2: EC2 Start Request"
    
    cat > /tmp/test-ec2.json <<'EOF'
{
  "body": "{\"ticketId\":\"TEST-EC2-001\",\"ticketSubject\":\"Start prod-web-server\",\"ticketBody\":\"Hi Team,\\n\\nPlease start the prod-web-server instance at 6 PM today.\\n\\nThanks,\\nJohn Doe\",\"fromEmail\":[\"john.doe@example.com\"],\"toEmail\":[\"support@cloudworkmates.com\"],\"ccEmail\":[]}"
}
EOF
    
    echo -e "${YELLOW}Invoking Lambda with EC2 start request...${NC}"
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload file:///tmp/test-ec2.json \
        --region "$REGION" \
        /tmp/response-ec2.json \
        --no-cli-pager
    
    echo -e "${GREEN}Response:${NC}"
    cat /tmp/response-ec2.json | python3 -m json.tool
    echo ""
}

test_security_group_ticket() {
    print_header "Test 3: Security Group Modification"
    
    cat > /tmp/test-sg.json <<'EOF'
{
  "body": "{\"ticketId\":\"TEST-SG-001\",\"ticketSubject\":\"Add port 443 to security group\",\"ticketBody\":\"Hi Support,\\n\\nPlease add inbound rule for port 443 (HTTPS) to security group sg-0123456789abcdef0 from 0.0.0.0/0.\\n\\nRegards,\\nJane Smith\",\"fromEmail\":[\"jane.smith@example.com\"],\"toEmail\":[\"support@cloudworkmates.com\"],\"ccEmail\":[]}"
}
EOF
    
    echo -e "${YELLOW}Invoking Lambda with security group request...${NC}"
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload file:///tmp/test-sg.json \
        --region "$REGION" \
        /tmp/response-sg.json \
        --no-cli-pager
    
    echo -e "${GREEN}Response:${NC}"
    cat /tmp/response-sg.json | python3 -m json.tool
    echo ""
}

test_invalid_ticket() {
    print_header "Test 4: Invalid Ticket (Error Handling)"
    
    cat > /tmp/test-invalid.json <<'EOF'
{
  "body": "{\"ticketId\":\"TEST-INVALID-001\"}"
}
EOF
    
    echo -e "${YELLOW}Invoking Lambda with invalid ticket...${NC}"
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload file:///tmp/test-invalid.json \
        --region "$REGION" \
        /tmp/response-invalid.json \
        --no-cli-pager
    
    echo -e "${GREEN}Response:${NC}"
    cat /tmp/response-invalid.json | python3 -m json.tool
    echo ""
}

test_performance() {
    print_header "Test 5: Performance Test"
    
    echo -e "${YELLOW}Running 10 concurrent invocations...${NC}"
    
    for i in {1..10}; do
        aws lambda invoke \
            --function-name "$FUNCTION_NAME" \
            --payload file:///tmp/test-alarm.json \
            --region "$REGION" \
            /tmp/response-perf-$i.json \
            --no-cli-pager &
    done
    
    wait
    
    echo -e "${GREEN}All invocations completed${NC}"
    echo -e "${YELLOW}Check CloudWatch Metrics for duration and concurrency${NC}"
    echo ""
}

view_logs() {
    print_header "Recent Lambda Logs"
    
    echo -e "${YELLOW}Fetching last 50 log entries...${NC}"
    aws logs tail "/aws/lambda/$FUNCTION_NAME" \
        --region "$REGION" \
        --since 10m \
        --format short
}

cleanup() {
    echo -e "${YELLOW}Cleaning up test files...${NC}"
    rm -f /tmp/test-*.json /tmp/response-*.json
    echo -e "${GREEN}Cleanup complete${NC}"
}

# Main menu
main() {
    print_header "Lambda Function Testing"
    
    echo "Select test to run:"
    echo "1) CloudWatch Alarm Ticket"
    echo "2) EC2 Start Request"
    echo "3) Security Group Modification"
    echo "4) Invalid Ticket (Error Handling)"
    echo "5) Performance Test (10 concurrent)"
    echo "6) View Recent Logs"
    echo "7) Run All Tests"
    echo "8) Exit"
    echo ""
    
    read -p "Enter choice [1-8]: " choice
    
    case $choice in
        1) test_alarm_ticket ;;
        2) test_ec2_start_ticket ;;
        3) test_security_group_ticket ;;
        4) test_invalid_ticket ;;
        5) test_performance ;;
        6) view_logs ;;
        7)
            test_alarm_ticket
            test_ec2_start_ticket
            test_security_group_ticket
            test_invalid_ticket
            test_performance
            ;;
        8)
            cleanup
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}"
            exit 1
            ;;
    esac
    
    cleanup
    
    echo -e "\n${GREEN}Testing completed!${NC}"
    echo -e "${BLUE}View detailed logs in CloudWatch: https://console.aws.amazon.com/cloudwatch/home?region=${REGION}#logsV2:log-groups/log-group/\$252Faws\$252Flambda\$252F${FUNCTION_NAME}${NC}"
}

main
