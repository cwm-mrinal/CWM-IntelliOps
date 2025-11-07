# Deployment Strategy - Zoho Automation Lambda

## 📋 Overview

This document outlines the deployment strategy for the Zoho Automation Lambda function, including setup, deployment methods, and operational procedures.

---

## 🎯 Deployment Philosophy

**Principle:** Update code only, no infrastructure changes.

✅ **What We Deploy:**
- Lambda function code (Python files)
- New versions
- Production alias updates

❌ **What We Don't Touch:**
- DynamoDB tables (already exist)
- IAM roles (already configured)
- Secrets Manager (already set up)
- API Gateway (already configured)

---

## 🏗️ Infrastructure (Pre-Existing)

### Lambda Function
- **Name:** Zoho-Automation-Lambda
- **ARN:** `arn:aws:lambda:ap-south-1:036160411876:function:Zoho-Automation-Lambda`
- **Region:** ap-south-1
- **Runtime:** Python 3.11
- **Memory:** 2048 MB
- **Timeout:** 60 seconds

### DynamoDB Tables
- `CWM-Account-Details-Table`
- `CWM-Account-Restriction-Table`
- `cwm-feedback-response-table`
- `CWM-Ticket-Embeddings-Table`

### Secrets Manager
- `zoho-automation-secrets-sMdisV`

### GitHub Repository
- **URL:** https://github.com/cwm-mrinal/CWM-IntelliOps.git
- **Type:** Private
- **Branches:** main, production, development, staging

---

## 🚀 Deployment Methods

### Method 1: Makefile (Recommended for Daily Use)

**Use Case:** Quick updates during development

```bash
make update
```

**What It Does:**
1. Packages all Python files into ZIP
2. Updates Lambda function code
3. Publishes new version
4. Updates production alias
5. Shows deployment summary

**Time:** ~30 seconds

**Best For:**
- Daily development
- Quick bug fixes
- Rapid iterations

---

### Method 2: Bash Script (Alternative)

**Use Case:** Direct script execution

```bash
./deploy-update.sh
```

**What It Does:**
- Same as Makefile method
- More verbose output
- Detailed progress tracking

**Time:** ~30 seconds

**Best For:**
- CI/CD integration
- Automated deployments
- Scripted workflows

---

### Method 3: GitHub Actions (Automated CI/CD)

**Use Case:** Automated deployments on code push

**Trigger:** Push to `main` branch

**Workflow:**
```
1. Code pushed to main
2. GitHub Actions triggered
3. Validates code (lint, security scan)
4. Packages Lambda function
5. Updates Lambda code
6. Publishes new version
7. Updates production alias
8. Runs smoke tests
9. Sends notification
```

**Time:** ~5 minutes

**Best For:**
- Team collaboration
- Production deployments
- Automated testing
- Audit trail

---

## 📝 Deployment Procedures

### Initial Setup (One-Time)

#### 1. Configure Git (Local User)

```bash
# Set CWM user for this repository only
git config user.name "cwm-mrinal"
git config user.email "mrinal.b@cloudworkmates.com"

# Verify
git config user.name  # Should show: cwm-mrinal
```

**Note:** This keeps your global git user unchanged.

#### 2. Initialize GitHub Repository

```bash
# Run automated setup
chmod +x setup-github-local.sh
./setup-github-local.sh
```

**This Creates:**
- .gitignore file
- Git repository
- Remote connection
- All branches (main, production, development, staging)

#### 3. Add GitHub Secrets

Go to: https://github.com/cwm-mrinal/CWM-IntelliOps/settings/secrets/actions

Add these secrets:

| Secret Name | Value | Purpose |
|-------------|-------|---------|
| `AWS_ACCESS_KEY_ID` | Your AWS access key | AWS authentication |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key | AWS authentication |
| `AWS_ACCOUNT_ID` | `Account-Id` | Account identification |

#### 4. Add Collaborator

Go to: https://github.com/cwm-mrinal/CWM-IntelliOps/settings/access

- Invite: `keshav.a@cloudworkmates.com`
- Role: **Write** (can push to all branches)

---

### Daily Deployment Workflow

#### Option A: Manual Deployment

```bash
# 1. Make code changes
vim lambda_function.py

# 2. Deploy
make update

# 3. Monitor
make logs

# 4. Verify
make status
```

#### Option B: Automated Deployment

```bash
# 1. Make code changes
vim lambda_function.py

# 2. Commit and push
git add .
git commit -m "Update: description of changes"
git push origin main

# 3. GitHub Actions deploys automatically
# 4. Check: https://github.com/cwm-mrinal/CWM-IntelliOps/actions
```

---

## 🔄 Rollback Procedures

### Quick Rollback

```bash
make rollback
```

**Interactive Menu:**
1. Shows recent versions
2. Shows current production version
3. Prompts for version to rollback to
4. Updates production alias

### Manual Rollback

```bash
# List versions
aws lambda list-versions-by-function \
    --function-name Zoho-Automation-Lambda \
    --region ap-south-1

# Rollback to specific version
aws lambda update-alias \
    --function-name Zoho-Automation-Lambda \
    --name production \
    --function-version <version-number> \
    --region ap-south-1
```

---

## 📊 Monitoring & Verification

### View Logs

```bash
# Real-time logs
make logs

# Error logs only
make logs-errors

# Specific time range
aws logs tail /aws/lambda/Zoho-Automation-Lambda \
    --since 1h \
    --region ap-south-1
```

### Check Function Status

```bash
make status
```

**Shows:**
- Function name
- Runtime
- Memory size
- Timeout
- Last modified
- Current state

### View Metrics

```bash
make metrics
```

**Shows:**
- Invocations (last 1 hour)
- Duration
- Errors
- Throttles

### Run Tests

```bash
make test
```

**Test Scenarios:**
1. CloudWatch alarm ticket
2. EC2 start/stop request
3. Security group modification
4. Invalid ticket (error handling)
5. Performance test (10 concurrent)

---

## 🔐 Security Considerations

### Secrets Management
- All credentials in AWS Secrets Manager
- GitHub secrets for CI/CD
- No credentials in code
- Automatic token refresh

### Access Control
- Private GitHub repository
- IAM roles with least privilege
- Cross-account role assumption
- Account whitelist validation

### Code Security
- Security scanning in CI/CD
- Dependency vulnerability checks
- Automated linting
- Code review via Pull Requests

---

## 🎯 Branch Strategy

### Main Branch
- **Purpose:** Production-ready code
- **Protection:** Recommended (require PR approval)
- **Deployment:** Automatic via GitHub Actions
- **Testing:** Full test suite

### Production Branch
- **Purpose:** Production releases
- **Protection:** Recommended
- **Deployment:** Manual or scheduled
- **Testing:** Smoke tests

### Development Branch
- **Purpose:** Active development
- **Protection:** Optional
- **Deployment:** To dev environment (if configured)
- **Testing:** Unit tests

### Staging Branch
- **Purpose:** Pre-production testing
- **Protection:** Optional
- **Deployment:** To staging environment (if configured)
- **Testing:** Integration tests

---

## 📋 Pre-Deployment Checklist

Before deploying:
- [ ] Code changes tested locally
- [ ] No syntax errors (`make validate`)
- [ ] Linting passed (`make lint`)
- [ ] Security scan clean (`make security-scan`)
- [ ] Secrets Manager has required secrets
- [ ] AWS credentials configured
- [ ] Function name is correct

---

## ✅ Post-Deployment Checklist

After deploying:
- [ ] Check logs for errors (`make logs-errors`)
- [ ] Verify function works (`make test`)
- [ ] Monitor metrics (`make metrics`)
- [ ] Test with real ticket (if possible)
- [ ] Confirm team notifications work
- [ ] Verify Zoho integration

---

## 🚨 Emergency Procedures

### Lambda Function Not Responding

```bash
# 1. Check logs
make logs-errors

# 2. Check function status
make status

# 3. Rollback if needed
make rollback

# 4. Contact DevOps team
```

### High Error Rate

```bash
# 1. Check CloudWatch Alarms
aws cloudwatch describe-alarms \
    --alarm-name-prefix Zoho-Automation-Lambda \
    --region ap-south-1

# 2. View error logs
make logs-errors

# 3. Rollback to last known good version
make rollback
```

### Deployment Failed

```bash
# 1. Check GitHub Actions logs
# Go to: https://github.com/cwm-mrinal/CWM-IntelliOps/actions

# 2. Check AWS credentials
aws sts get-caller-identity

# 3. Retry deployment
make update
```

---

## 🛠️ Useful Commands

### Deployment
```bash
make update          # Update Lambda function
make quick           # Same as update
```

### Monitoring
```bash
make logs            # View logs (real-time)
make logs-errors     # View error logs only
make status          # Check function status
make metrics         # View metrics
```

### Testing
```bash
make test            # Run all tests
make invoke-test     # Invoke with test event
```

### Maintenance
```bash
make rollback        # Rollback to previous version
make clean           # Clean up files
make backup          # Backup function code
```

### Development
```bash
make validate        # Validate Python syntax
make lint            # Run linting
make security-scan   # Run security scan
make format          # Format code
```

---

## 📞 Support & Escalation

### Self-Service
1. Check logs: `make logs-errors`
2. Check status: `make status`
3. Review this document

### Team Support
- **Owner:** mrinal.b@cloudworkmates.com
- **Collaborator:** keshav.a@cloudworkmates.com
- **DevOps Team:** devops@cloudworkmates.com

### Emergency Contact
- Create Zoho Desk ticket
- Tag: "Lambda Deployment Issue"
- Priority: High

---

## 📈 Performance Optimization

### Current Configuration
- Memory: 2048 MB
- Timeout: 60 seconds
- Concurrent executions: Unlimited

### Optimization Tips
1. Monitor duration metrics
2. Adjust memory if needed
3. Use provisioned concurrency for consistent traffic
4. Implement caching for DynamoDB lookups
5. Optimize cold start time

---

## 🎓 Best Practices

### Code Changes
1. Test locally before deploying
2. Use descriptive commit messages
3. Create feature branches for major changes
4. Request code review via Pull Requests
5. Keep changes small and focused

### Deployment
1. Deploy during low-traffic periods
2. Monitor logs after deployment
3. Keep production alias updated
4. Tag versions with meaningful descriptions
5. Document breaking changes

### Monitoring
1. Check logs daily
2. Review metrics weekly
3. Set up CloudWatch Alarms
4. Monitor DLQ for failed events
5. Track custom business metrics

---

## 📚 Additional Resources

### Documentation
- **Lambda Function:** LAMBDA_FUNCTION_DOCUMENTATION.md
- **Deployment:** This document
- **Makefile:** All available commands

### AWS Console Links
- **Lambda:** https://ap-south-1.console.aws.amazon.com/lambda/home?region=ap-south-1#/functions/Zoho-Automation-Lambda
- **CloudWatch Logs:** https://ap-south-1.console.aws.amazon.com/cloudwatch/home?region=ap-south-1#logsV2:log-groups/log-group/$252Faws$252Flambda$252FZoho-Automation-Lambda
- **DynamoDB:** https://ap-south-1.console.aws.amazon.com/dynamodbv2/home?region=ap-south-1#tables

### GitHub Links
- **Repository:** https://github.com/cwm-mrinal/CWM-IntelliOps
- **Actions:** https://github.com/cwm-mrinal/CWM-IntelliOps/actions
- **Settings:** https://github.com/cwm-mrinal/CWM-IntelliOps/settings

---

## 🎉 Summary

**Deployment is simple:**
1. Make code changes
2. Run `make update` or push to GitHub
3. Monitor logs
4. Done!

**Key Points:**
- ✅ Only updates Lambda code
- ✅ No infrastructure changes
- ✅ Fast (30 seconds)
- ✅ Safe (easy rollback)
- ✅ Automated (GitHub Actions)

---

**Last Updated:** January 7, 2025  
**Version:** 1.0  
**Maintained By:** CloudWorkMates DevOps Team
