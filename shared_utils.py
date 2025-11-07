"""
Shared utility functions to eliminate code duplication across modules.
Includes email extraction, token management, and common AWS operations.
"""
import re
import json
import time
import boto3
import logging
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# EMAIL UTILITIES
# ============================================================================

def extract_email_address(email_input) -> Optional[str]:
    """
    Extract email address from various formats:
    - '"Name" <email@domain.com>'
    - ['email@domain.com']
    - 'email@domain.com'
    """
    if not email_input:
        return None
    
    # Handle list input
    if isinstance(email_input, list):
        if not email_input:
            return None
        email_input = email_input[0]
    
    # Convert to string and clean
    email_string = str(email_input).strip('[]"\'')
    
    # Extract email using regex
    email_pattern = r'<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    match = re.search(email_pattern, email_string)
    
    if match:
        return match.group(1) if match.group(1) else match.group(2)
    
    return None

def clean_email_address(email: str) -> str:
    """Clean and normalize email address to lowercase"""
    if not email:
        return ""
    match = re.search(r'[\w\.-]+@[\w\.-]+', email)
    return match.group(0).lower() if match else email.lower()

def extract_emails_from_string(email_string: str) -> List[str]:
    """Extract multiple emails from comma-separated string"""
    if not email_string:
        return []
    
    parts = [p.strip() for p in email_string.split(",") if p.strip()]
    return [clean_email_address(p) for p in parts if clean_email_address(p)]

# ============================================================================
# TOKEN MANAGEMENT (Zoho OAuth)
# ============================================================================

class TokenManager:
    """Centralized token management with caching and automatic refresh"""
    
    def __init__(self, secret_name: str, region: str = 'ap-south-1'):
        self.secret_name = secret_name
        self.region = region
        self.secrets_client = boto3.client('secretsmanager', region_name=region)
        self._cache = {}
        self._cache_expiry = {}
        self.token_validity_seconds = 3600
        self.token_buffer_seconds = 300  # Refresh 5 min before expiry
    
    def get_secret(self) -> Dict[str, Any]:
        """Get secrets from AWS Secrets Manager"""
        response = self.secrets_client.get_secret_value(SecretId=self.secret_name)
        return json.loads(response['SecretString'])
    
    def update_secret(self, updated_data: Dict[str, Any]) -> None:
        """Update secrets in AWS Secrets Manager"""
        self.secrets_client.put_secret_value(
            SecretId=self.secret_name,
            SecretString=json.dumps(updated_data)
        )
    
    def get_access_token(self, token_key: str = 'ACCESS_TOKEN', 
                        refresh_token_key: str = 'REFRESH_TOKEN',
                        client_id_key: str = 'CLIENT_ID',
                        client_secret_key: str = 'CLIENT_SECRET') -> str:
        """
        Get access token with automatic refresh.
        Supports multiple token types (ACCESS_TOKEN, ACCESS_TOKEN_TEAM, etc.)
        """
        cache_key = f"{token_key}_cached"
        expiry_key = f"{token_key}_EXPIRY"
        
        # Check cache first
        if cache_key in self._cache:
            expiry_time = self._cache_expiry.get(cache_key, 0)
            if time.time() < (expiry_time - self.token_buffer_seconds):
                logger.debug(f"Using cached {token_key}")
                return self._cache[cache_key]
        
        # Get from Secrets Manager
        logger.info(f"Retrieving {token_key} from Secrets Manager")
        secrets = self.get_secret()
        
        access_token = secrets.get(token_key)
        expiry_time = secrets.get(expiry_key, 0)
        current_time = int(time.time())
        
        # Check if token is still valid
        if access_token and expiry_time and current_time < (expiry_time - self.token_buffer_seconds):
            logger.info(f"Using existing {token_key}")
            self._cache[cache_key] = access_token
            self._cache_expiry[cache_key] = expiry_time
            return access_token
        
        # Refresh token
        logger.info(f"{token_key} expired or missing, refreshing...")
        
        import requests
        token_url = "https://accounts.zoho.com/oauth/v2/token"
        params = {
            "client_id": secrets.get(client_id_key),
            "client_secret": secrets.get(client_secret_key),
            "grant_type": "refresh_token",
            "refresh_token": secrets.get(refresh_token_key)
        }
        
        try:
            response = requests.post(token_url, params=params, timeout=10)
            response.raise_for_status()
            new_token = response.json().get("access_token")
            
            if not new_token:
                raise ValueError(f"No access token in Zoho response for {token_key}")
            
            # Update Secrets Manager
            secrets[token_key] = new_token
            secrets[expiry_key] = current_time + self.token_validity_seconds
            self.update_secret(secrets)
            
            # Update cache
            self._cache[cache_key] = new_token
            self._cache_expiry[cache_key] = secrets[expiry_key]
            
            logger.info(f"{token_key} refreshed and cached successfully")
            return new_token
            
        except requests.RequestException as e:
            logger.error(f"Failed to refresh {token_key}: {e}")
            raise Exception(f"Failed to refresh {token_key}: {str(e)}")

# Global token manager instance
_token_manager = None

def get_token_manager(secret_name: str = 'zoho-automation-secrets', 
                     region: str = 'ap-south-1') -> TokenManager:
    """Get or create global token manager instance"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager(secret_name, region)
    return _token_manager

# ============================================================================
# AWS CLIENT UTILITIES
# ============================================================================

@lru_cache(maxsize=10)
def get_aws_client(service: str, region: str = 'ap-south-1', 
                   credentials: Optional[Dict] = None):
    """
    Get AWS client with optional cross-account credentials.
    Cached to avoid recreating clients.
    """
    if credentials:
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
    return boto3.client(service, region_name=region)

# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_account_id(account_id: str) -> bool:
    """Validate AWS account ID format (12 digits)"""
    if not account_id:
        return False
    return bool(re.fullmatch(r'\d{12}', str(account_id)))

def validate_instance_id(instance_id: str) -> bool:
    """Validate EC2 instance ID format"""
    if not instance_id:
        return False
    return bool(re.match(r'^i-[a-f0-9]{8,17}$', instance_id))

def validate_security_group_id(sg_id: str) -> bool:
    """Validate security group ID format"""
    if not sg_id:
        return False
    return bool(re.match(r'^sg-[a-f0-9]{8,17}$', sg_id))

def sanitize_json_string(json_str: str) -> str:
    """Remove or escape invalid control characters from JSON string"""
    if not json_str:
        return json_str
    
    # Replace common problematic characters
    json_str = json_str.replace('\n', '\\n')
    json_str = json_str.replace('\r', '\\r')
    json_str = json_str.replace('\t', '\\t')
    json_str = json_str.replace('\b', '\\b')
    json_str = json_str.replace('\f', '\\f')
    
    # Remove other control characters
    json_str = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_str)
    
    return json_str

# ============================================================================
# LOGGING UTILITIES
# ============================================================================

def log_with_context(logger_instance, level: str, message: str, 
                     context: Optional[Dict] = None, **kwargs):
    """
    Structured logging with context.
    Usage: log_with_context(logger, 'info', 'Processing ticket', {'ticket_id': '123'})
    """
    log_data = {
        'message': message,
        'timestamp': datetime.utcnow().isoformat(),
        **(context or {}),
        **kwargs
    }
    
    log_method = getattr(logger_instance, level.lower(), logger_instance.info)
    log_method(json.dumps(log_data))

# ============================================================================
# RETRY UTILITIES
# ============================================================================

def retry_with_backoff(func, max_retries: int = 3, initial_delay: float = 1.0,
                      backoff_factor: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Retry function with exponential backoff.
    
    Usage:
        result = retry_with_backoff(
            lambda: some_api_call(),
            max_retries=3,
            exceptions=(ClientError, TimeoutError)
        )
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(f"All {max_retries} attempts failed")
    
    raise last_exception

# ============================================================================
# CACHE UTILITIES
# ============================================================================

class TTLCache:
    """Simple TTL cache for DynamoDB results"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._cache = {}
        self._timestamps = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        if key not in self._cache:
            return None
        
        if time.time() - self._timestamps[key] > self.ttl_seconds:
            # Expired
            del self._cache[key]
            del self._timestamps[key]
            return None
        
        return self._cache[key]
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp"""
        self._cache[key] = value
        self._timestamps[key] = time.time()
    
    def clear(self) -> None:
        """Clear all cache entries"""
        self._cache.clear()
        self._timestamps.clear()
    
    def size(self) -> int:
        """Get current cache size"""
        return len(self._cache)

# Global cache instances
_account_cache = TTLCache(ttl_seconds=300)  # 5 minutes
_team_cache = TTLCache(ttl_seconds=600)     # 10 minutes

def get_account_cache() -> TTLCache:
    """Get global account cache instance"""
    return _account_cache

def get_team_cache() -> TTLCache:
    """Get global team cache instance"""
    return _team_cache
