#!/bin/bash

################################################################################
# GitHub Repository Setup Script - LOCAL USER ONLY
# Sets CWM user for THIS repository only (no global changes)
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
REPO_URL="https://github.com/cwm-mrinal/CWM-IntelliOps.git"
LOCAL_USER="cwm-mrinal"
LOCAL_EMAIL="mrinal.b@cloudworkmates.com"
COLLABORATOR="keshav.a@cloudworkmates.com"

print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  GitHub Setup (Local User Only)       ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo ""
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_info() { echo -e "${BLUE}ℹ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

check_users() {
    print_info "Checking git configuration..."
    
    GLOBAL_USER=$(git config --global user.name || echo "Not set")
    GLOBAL_EMAIL=$(git config --global user.email || echo "Not set")
    LOCAL_USER_CURRENT=$(git config user.name 2>/dev/null || echo "Not set")
    LOCAL_EMAIL_CURRENT=$(git config user.email 2>/dev/null || echo "Not set")
    
    echo ""
    echo -e "${YELLOW}Global Git User (unchanged):${NC}"
    echo "  Name:  $GLOBAL_USER"
    echo "  Email: $GLOBAL_EMAIL"
    echo ""
    echo -e "${GREEN}Local Git User (for this repo):${NC}"
    echo "  Name:  $LOCAL_USER_CURRENT"
    echo "  Email: $LOCAL_EMAIL_CURRENT"
    echo ""
}

configure_local_user() {
    print_info "Setting CWM user for THIS repository only..."
    
    # Set user for THIS repository only (not global)
    git config user.name "$LOCAL_USER"
    git config user.email "$LOCAL_EMAIL"
    
    print_success "Local git user configured:"
    echo "  Name:  $(git config user.name)"
    echo "  Email: $(git config user.email)"
    echo ""
    print_info "Your global git user remains unchanged!"
}

create_gitignore() {
    print_info "Creating .gitignore file..."
    
    cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
*.egg-info/
dist/
build/

# AWS
*.pem
*.key
credentials
config

# Secrets
secrets.json
*.secret
.env

# Deployment
lambda-*.zip
layer/
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Test
.pytest_cache/
.coverage
htmlcov/
*.cover

# Terraform
.terraform/
*.tfstate
*.tfstate.backup
.terraform.lock.hcl
EOF
    
    print_success ".gitignore created"
}

initialize_repository() {
    print_info "Initializing git repository..."
    
    if [ -d .git ]; then
        print_warning "Git repository already initialized"
    else
        git init
        print_success "Git repository initialized"
    fi
    
    # Check if remote exists
    if git remote get-url origin &> /dev/null; then
        print_warning "Remote 'origin' already exists"
        EXISTING_REMOTE=$(git remote get-url origin)
        if [ "$EXISTING_REMOTE" != "$REPO_URL" ]; then
            print_warning "Remote URL is different: $EXISTING_REMOTE"
            read -p "Update remote URL? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                git remote set-url origin "$REPO_URL"
                print_success "Remote URL updated"
            fi
        fi
    else
        git remote add origin "$REPO_URL"
        print_success "Remote 'origin' added"
    fi
}

commit_and_push_main() {
    print_info "Committing and pushing to main branch..."
    
    git add .
    
    # Check if there's anything to commit
    if git diff --cached --quiet; then
        print_warning "No changes to commit"
    else
        git commit -m "Initial commit: Lambda deployment automation"
        print_success "Changes committed"
    fi
    
    git branch -M main
    
    print_info "Pushing to main branch..."
    git push -u origin main
    
    print_success "Main branch pushed"
}

create_branches() {
    print_info "Creating additional branches..."
    
    BRANCHES=("production" "development" "staging")
    
    for BRANCH in "${BRANCHES[@]}"; do
        print_info "Creating $BRANCH branch..."
        
        # Check if branch exists locally
        if git show-ref --verify --quiet refs/heads/"$BRANCH"; then
            print_warning "$BRANCH branch already exists locally"
            git checkout "$BRANCH"
        else
            git checkout -b "$BRANCH"
        fi
        
        # Push to remote
        git push -u origin "$BRANCH" 2>/dev/null || print_warning "$BRANCH branch already exists on remote"
        
        print_success "$BRANCH branch ready"
    done
    
    # Return to main
    git checkout main
    print_success "Returned to main branch"
}

verify_setup() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     Verification                       ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    
    echo -e "${YELLOW}Global Git User (unchanged):${NC}"
    echo "  Name:  $(git config --global user.name)"
    echo "  Email: $(git config --global user.email)"
    echo ""
    
    echo -e "${GREEN}Local Git User (this repository):${NC}"
    echo "  Name:  $(git config user.name)"
    echo "  Email: $(git config user.email)"
    echo ""
    
    echo -e "${BLUE}Branches:${NC}"
    git branch -a | grep -v "HEAD"
    echo ""
}

show_next_steps() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     Setup Complete! ✓                  ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Repository:${NC} $REPO_URL"
    echo -e "${BLUE}Local User:${NC} $LOCAL_USER ($LOCAL_EMAIL)"
    echo -e "${BLUE}Global User:${NC} Unchanged!"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo ""
    echo "1. Add GitHub Secrets:"
    echo "   https://github.com/cwm-mrinal/CWM-IntelliOps/settings/secrets/actions"
    echo "   - AWS_ACCESS_KEY_ID"
    echo "   - AWS_SECRET_ACCESS_KEY"
    echo "   - AWS_ACCOUNT_ID (036160411876)"
    echo ""
    echo "2. Add Collaborator:"
    echo "   https://github.com/cwm-mrinal/CWM-IntelliOps/settings/access"
    echo "   - Invite: $COLLABORATOR"
    echo "   - Role: Write"
    echo ""
    echo "3. Test Deployment:"
    echo "   git push origin main"
    echo "   # Or"
    echo "   make update"
    echo ""
    echo -e "${GREEN}✓ Your global git user remains unchanged!${NC}"
    echo -e "${GREEN}✓ This repository will use: $LOCAL_USER${NC}"
}

main() {
    print_header
    
    # Check current users
    check_users
    
    # Configure local user (repository-specific)
    print_info "This will set CWM user for THIS repository only."
    print_info "Your global git user will NOT be changed."
    echo ""
    read -p "Continue? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "Setup cancelled"
        exit 1
    fi
    
    configure_local_user
    
    # Create .gitignore
    create_gitignore
    
    # Initialize repository
    initialize_repository
    
    # Commit and push main
    read -p "Commit and push to main branch? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        commit_and_push_main
    else
        print_warning "Skipped pushing to main"
    fi
    
    # Create branches
    read -p "Create production, development, and staging branches? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        create_branches
    else
        print_warning "Skipped branch creation"
    fi
    
    # Verify setup
    verify_setup
    
    # Show next steps
    show_next_steps
}

main "$@"
