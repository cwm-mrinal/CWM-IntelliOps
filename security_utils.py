"""
Security utilities for handling sensitive data, password generation, and validation.
Addresses security concerns in password logging and credential management.
"""
import re
import secrets
import string
import hashlib
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# PASSWORD GENERATION
# ============================================================================

def generate_secure_password(length: int = 16, 
                            include_special: bool = True,
                            include_numbers: bool = True,
                            include_uppercase: bool = True,
                            include_lowercase: bool = True) -> str:
    """
    Generate cryptographically secure password.
    NEVER log the generated password!
    """
    if length < 8:
        raise ValueError("Password length must be at least 8 characters")
    
    chars = ""
    if include_lowercase:
        chars += string.ascii_lowercase
    if include_uppercase:
        chars += string.ascii_uppercase
    if include_numbers:
        chars += string.digits
    if include_special:
        chars += "!@#$%^&*()_+-=[]{}|;:,.<>?"
    
    if not chars:
        raise ValueError("At least one character type must be included")
    
    # Generate password
    password = ''.join(secrets.choice(chars) for _ in range(length))
    
    # Ensure at least one of each required type
    if include_lowercase and not any(c in string.ascii_lowercase for c in password):
        password = secrets.choice(string.ascii_lowercase) + password[1:]
    if include_uppercase and not any(c in string.ascii_uppercase for c in password):
        password = secrets.choice(string.ascii_uppercase) + password[1:]
    if include_numbers and not any(c in string.digits for c in password):
        password = secrets.choice(string.digits) + password[1:]
    if include_special and not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        password = secrets.choice("!@#$%^&*()_+-=[]{}|;:,.<>?") + password[1:]
    
    return password

def hash_password(password: str) -> str:
    """Hash password for secure storage (use for audit logs only)"""
    return hashlib.sha256(password.encode()).hexdigest()

def mask_sensitive_data(data: str, mask_char: str = '*', 
                       visible_chars: int = 4) -> str:
    """
    Mask sensitive data for logging.
    Example: mask_sensitive_data('password123') -> '****word123'
    """
    if not data or len(data) <= visible_chars:
        return mask_char * len(data) if data else ""
    
    return mask_char * (len(data) - visible_chars) + data[-visible_chars:]

# ============================================================================
# CREDENTIAL VALIDATION
# ============================================================================

def validate_password_strength(password: str) -> Dict[str, Any]:
    """
    Validate password strength and return detailed feedback.
    """
    result = {
        'valid': True,
        'score': 0,
        'issues': []
    }
    
    if len(password) < 8:
        result['valid'] = False
        result['issues'].append('Password must be at least 8 characters')
    else:
        result['score'] += 1
    
    if not re.search(r'[a-z]', password):
        result['issues'].append('Password should contain lowercase letters')
    else:
        result['score'] += 1
    
    if not re.search(r'[A-Z]', password):
        result['issues'].append('Password should contain uppercase letters')
    else:
        result['score'] += 1
    
    if not re.search(r'\d', password):
        result['issues'].append('Password should contain numbers')
    else:
        result['score'] += 1
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', password):
        result['issues'].append('Password should contain special characters')
    else:
        result['score'] += 1
    
    if result['issues']:
        result['valid'] = False
    
    return result

# ============================================================================
# SECURE LOGGING
# ============================================================================

class SecureLogger:
    """
    Logger wrapper that automatically masks sensitive data.
    """
    
    SENSITIVE_PATTERNS = [
        (r'password["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', 'password'),
        (r'secret["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', 'secret'),
        (r'token["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', 'token'),
        (r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', 'api_key'),
        (r'\b\d{12}\b', 'account_id'),  # AWS Account IDs
        (r'i-[a-f0-9]{8,17}', 'instance_id'),
    ]
    
    def __init__(self, logger_instance):
        self.logger = logger_instance
    
    def _mask_message(self, message: str) -> str:
        """Mask sensitive data in log message"""
        masked = message
        for pattern, label in self.SENSITIVE_PATTERNS:
            masked = re.sub(pattern, f'{label}=***MASKED***', masked, flags=re.IGNORECASE)
        return masked
    
    def info(self, message: str, *args, **kwargs):
        self.logger.info(self._mask_message(str(message)), *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        self.logger.warning(self._mask_message(str(message)), *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        self.logger.error(self._mask_message(str(message)), *args, **kwargs)
    
    def debug(self, message: str, *args, **kwargs):
        self.logger.debug(self._mask_message(str(message)), *args, **kwargs)

def get_secure_logger(name: str) -> SecureLogger:
    """Get a secure logger instance"""
    return SecureLogger(logging.getLogger(name))
