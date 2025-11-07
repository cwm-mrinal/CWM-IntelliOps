.PHONY: help install update deploy-quick test clean rollback logs

# Variables - YOUR EXISTING RESOURCES
FUNCTION_NAME := Zoho-Automation-Lambda
FUNCTION_ARN := arn:aws:lambda:ap-south-1:036160411876:function:Zoho-Automation-Lambda
REGION := ap-south-1
ACCOUNT_ID := 036160411876
PYTHON := python3
PIP := pip3

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Zoho Automation Lambda - Makefile Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

install: ## Install Python dependencies
	@echo "$(BLUE)Installing dependencies...$(NC)"
	$(PIP) install -r requirements.txt --upgrade
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

update: ## Update Lambda function code (RECOMMENDED)
	@echo "$(BLUE)Updating Lambda function...$(NC)"
	chmod +x deploy-update.sh
	./deploy-update.sh
	@echo "$(GREEN)✓ Update complete$(NC)"

quick: ## Quick update (alias for update)
	@$(MAKE) update

test: ## Run Lambda function tests
	@echo "$(BLUE)Running tests...$(NC)"
	chmod +x test-lambda.sh
	./test-lambda.sh
	@echo "$(GREEN)✓ Tests complete$(NC)"

test-unit: ## Run unit tests with pytest
	@echo "$(BLUE)Running unit tests...$(NC)"
	$(PYTHON) -m pytest tests/ -v --cov=. --cov-report=html
	@echo "$(GREEN)✓ Unit tests complete$(NC)"
	@echo "$(YELLOW)Coverage report: htmlcov/index.html$(NC)"

lint: ## Run code linting
	@echo "$(BLUE)Running linters...$(NC)"
	$(PYTHON) -m pylint *.py --exit-zero
	@echo "$(GREEN)✓ Linting complete$(NC)"

security-scan: ## Run security scans
	@echo "$(BLUE)Running security scans...$(NC)"
	$(PIP) install bandit safety
	bandit -r . -f screen
	safety check
	@echo "$(GREEN)✓ Security scan complete$(NC)"

rollback: ## Rollback to previous Lambda version
	@echo "$(BLUE)Rolling back Lambda function...$(NC)"
	chmod +x rollback.sh
	./rollback.sh
	@echo "$(GREEN)✓ Rollback complete$(NC)"

logs: ## Tail Lambda function logs
	@echo "$(BLUE)Tailing Lambda logs...$(NC)"
	aws logs tail /aws/lambda/$(FUNCTION_NAME) --follow --region $(REGION)

logs-errors: ## Show only error logs
	@echo "$(BLUE)Showing error logs...$(NC)"
	aws logs tail /aws/lambda/$(FUNCTION_NAME) \
		--filter-pattern "ERROR" \
		--since 1h \
		--region $(REGION)

invoke-test: ## Invoke Lambda with test event
	@echo "$(BLUE)Invoking Lambda function...$(NC)"
	aws lambda invoke \
		--function-name $(FUNCTION_NAME) \
		--payload file://tests/test-event.json \
		--region $(REGION) \
		response.json
	@cat response.json | $(PYTHON) -m json.tool
	@rm response.json

metrics: ## Show Lambda metrics
	@echo "$(BLUE)Lambda Metrics (Last 1 hour):$(NC)"
	@aws cloudwatch get-metric-statistics \
		--namespace AWS/Lambda \
		--metric-name Invocations \
		--dimensions Name=FunctionName,Value=$(FUNCTION_NAME) \
		--start-time $$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
		--end-time $$(date -u +%Y-%m-%dT%H:%M:%S) \
		--period 300 \
		--statistics Sum \
		--region $(REGION) \
		--query 'Datapoints[*].[Timestamp,Sum]' \
		--output table

status: ## Check Lambda function status
	@echo "$(BLUE)Lambda Function Status:$(NC)"
	@aws lambda get-function-configuration \
		--function-name $(FUNCTION_NAME) \
		--region $(REGION) \
		--query '{Name:FunctionName,Runtime:Runtime,Memory:MemorySize,Timeout:Timeout,LastModified:LastModified,State:State}' \
		--output table

package: ## Create deployment package
	@echo "$(BLUE)Creating deployment package...$(NC)"
	@rm -f lambda-deployment-package.zip
	@zip -r lambda-deployment-package.zip *.py -x "*test*" -x "*__pycache__*" -q
	@echo "$(GREEN)✓ Package created: lambda-deployment-package.zip$(NC)"
	@du -h lambda-deployment-package.zip

package-layer: ## Create Lambda layer package
	@echo "$(BLUE)Creating Lambda layer...$(NC)"
	@rm -rf layer lambda-layer.zip
	@mkdir -p layer/python
	@$(PIP) install -r requirements.txt -t layer/python/ --upgrade
	@cd layer && zip -r ../lambda-layer.zip . -q
	@echo "$(GREEN)✓ Layer created: lambda-layer.zip$(NC)"
	@du -h lambda-layer.zip
	@rm -rf layer

clean: ## Clean up generated files
	@echo "$(BLUE)Cleaning up...$(NC)"
	@rm -rf layer
	@rm -f lambda-deployment-package.zip lambda-layer.zip
	@rm -f response.json
	@rm -rf __pycache__ .pytest_cache htmlcov .coverage
	@rm -rf *.pyc
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

validate: ## Validate Python syntax
	@echo "$(BLUE)Validating Python syntax...$(NC)"
	@$(PYTHON) -m py_compile *.py
	@echo "$(GREEN)✓ Syntax validation complete$(NC)"

format: ## Format code with black
	@echo "$(BLUE)Formatting code...$(NC)"
	@$(PIP) install black
	@black *.py
	@echo "$(GREEN)✓ Code formatted$(NC)"

docs: ## Generate documentation
	@echo "$(BLUE)Generating documentation...$(NC)"
	@$(PIP) install pdoc3
	@pdoc --html --output-dir docs *.py
	@echo "$(GREEN)✓ Documentation generated in docs/$(NC)"

update-secrets: ## Update Secrets Manager
	@echo "$(BLUE)Updating Secrets Manager...$(NC)"
	@aws secretsmanager put-secret-value \
		--secret-id zoho-automation-secrets \
		--secret-string file://secrets.json \
		--region $(REGION)
	@echo "$(GREEN)✓ Secrets updated$(NC)"

create-alias: ## Create production alias
	@echo "$(BLUE)Creating production alias...$(NC)"
	@LATEST=$$(aws lambda publish-version \
		--function-name $(FUNCTION_NAME) \
		--region $(REGION) \
		--query 'Version' \
		--output text); \
	aws lambda create-alias \
		--function-name $(FUNCTION_NAME) \
		--name production \
		--function-version $$LATEST \
		--region $(REGION) || \
	aws lambda update-alias \
		--function-name $(FUNCTION_NAME) \
		--name production \
		--function-version $$LATEST \
		--region $(REGION)
	@echo "$(GREEN)✓ Production alias created/updated$(NC)"

enable-insights: ## Enable Lambda Insights
	@echo "$(BLUE)Enabling Lambda Insights...$(NC)"
	@aws lambda update-function-configuration \
		--function-name $(FUNCTION_NAME) \
		--layers arn:aws:lambda:$(REGION):580247275435:layer:LambdaInsightsExtension:14 \
		--region $(REGION)
	@echo "$(GREEN)✓ Lambda Insights enabled$(NC)"

enable-xray: ## Enable X-Ray tracing
	@echo "$(BLUE)Enabling X-Ray tracing...$(NC)"
	@aws lambda update-function-configuration \
		--function-name $(FUNCTION_NAME) \
		--tracing-config Mode=Active \
		--region $(REGION)
	@echo "$(GREEN)✓ X-Ray tracing enabled$(NC)"

cost-estimate: ## Estimate monthly Lambda costs
	@echo "$(BLUE)Estimating monthly costs...$(NC)"
	@echo "Based on:"
	@echo "  - 100,000 requests/month"
	@echo "  - 2048 MB memory"
	@echo "  - 10 second average duration"
	@echo ""
	@echo "$(YELLOW)Estimated cost: ~\$$15-20/month$(NC)"
	@echo ""
	@echo "Use AWS Cost Explorer for actual costs"

backup: ## Backup Lambda function code
	@echo "$(BLUE)Backing up Lambda function...$(NC)"
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	aws lambda get-function \
		--function-name $(FUNCTION_NAME) \
		--region $(REGION) \
		--query 'Code.Location' \
		--output text | xargs curl -o backups/$(FUNCTION_NAME)_$$TIMESTAMP.zip
	@echo "$(GREEN)✓ Backup created in backups/$(NC)"

all: clean install validate lint test package update ## Run all steps

.DEFAULT_GOAL := help
