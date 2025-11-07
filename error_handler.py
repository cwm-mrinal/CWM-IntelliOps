"""
Centralized error handling with proper exception hierarchy and rollback mechanisms.
"""
import logging
import traceback
from typing import Dict, Any, Optional, Callable
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class AutomationError(Exception):
    """Base exception for all automation errors"""
    def __init__(self, message: str, details: Optional[Dict] = None):
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp
        }

class ValidationError(AutomationError):
    """Raised when input validation fails"""
    pass

class ConfigurationError(AutomationError):
    """Raised when configuration is invalid or missing"""
    pass

class AWSServiceError(AutomationError):
    """Raised when AWS service calls fail"""
    pass

class ZohoAPIError(AutomationError):
    """Raised when Zoho API calls fail"""
    pass

class BedrockError(AutomationError):
    """Raised when Bedrock/AI calls fail"""
    pass

class RollbackError(AutomationError):
    """Raised when rollback operations fail"""
    pass

# ============================================================================
# ROLLBACK MANAGER
# ============================================================================

class RollbackManager:
    """
    Manages rollback operations for automation workflows.
    Tracks changes and provides rollback capability.
    """
    
    def __init__(self):
        self.rollback_stack = []
        self.context = {}
    
    def add_rollback(self, rollback_func: Callable, *args, **kwargs):
        """
        Add a rollback function to the stack.
        
        Usage:
            manager.add_rollback(ec2.stop_instances, InstanceIds=['i-123'])
        """
        self.rollback_stack.append((rollback_func, args, kwargs))
        logger.debug(f"Added rollback: {rollback_func.__name__}")
    
    def execute_rollback(self) -> Dict[str, Any]:
        """
        Execute all rollback functions in reverse order (LIFO).
        Returns summary of rollback operations.
        """
        if not self.rollback_stack:
            logger.info("No rollback operations to execute")
            return {'status': 'success', 'operations': 0}
        
        logger.warning(f"Executing {len(self.rollback_stack)} rollback operations")
        
        results = []
        errors = []
        
        # Execute in reverse order
        while self.rollback_stack:
            rollback_func, args, kwargs = self.rollback_stack.pop()
            
            try:
                logger.info(f"Rolling back: {rollback_func.__name__}")
                result = rollback_func(*args, **kwargs)
                results.append({
                    'function': rollback_func.__name__,
                    'status': 'success',
                    'result': str(result)
                })
            except Exception as e:
                error_msg = f"Rollback failed for {rollback_func.__name__}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append({
                    'function': rollback_func.__name__,
                    'status': 'failed',
                    'error': str(e)
                })
        
        return {
            'status': 'completed_with_errors' if errors else 'success',
            'operations': len(results) + len(errors),
            'successful': results,
            'failed': errors
        }
    
    def clear(self):
        """Clear all rollback operations"""
        self.rollback_stack.clear()
        logger.debug("Rollback stack cleared")
    
    def set_context(self, key: str, value: Any):
        """Store context information for rollback operations"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """Retrieve context information"""
        return self.context.get(key, default)

# ============================================================================
# ERROR HANDLING DECORATORS
# ============================================================================

def handle_errors(error_type: type = AutomationError, 
                 rollback_manager: Optional[RollbackManager] = None,
                 log_traceback: bool = True):
    """
    Decorator to handle errors and optionally trigger rollback.
    
    Usage:
        @handle_errors(error_type=AWSServiceError, rollback_manager=manager)
        def create_instance(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except error_type as e:
                logger.error(f"Error in {func.__name__}: {e}")
                if log_traceback:
                    logger.error(traceback.format_exc())
                
                # Execute rollback if manager provided
                if rollback_manager:
                    logger.warning("Triggering rollback due to error")
                    rollback_result = rollback_manager.execute_rollback()
                    logger.info(f"Rollback result: {rollback_result}")
                
                raise
            except Exception as e:
                logger.error(f"Unexpected error in {func.__name__}: {e}")
                if log_traceback:
                    logger.error(traceback.format_exc())
                
                # Execute rollback for unexpected errors too
                if rollback_manager:
                    logger.warning("Triggering rollback due to unexpected error")
                    rollback_result = rollback_manager.execute_rollback()
                    logger.info(f"Rollback result: {rollback_result}")
                
                # Wrap in automation error
                raise AutomationError(
                    f"Unexpected error in {func.__name__}",
                    details={'original_error': str(e), 'type': type(e).__name__}
                )
        return wrapper
    return decorator

def validate_input(**validators):
    """
    Decorator to validate function inputs.
    
    Usage:
        @validate_input(
            account_id=lambda x: len(x) == 12,
            instance_id=lambda x: x.startswith('i-')
        )
        def process_instance(account_id, instance_id):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            # Validate each parameter
            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    if not validator(value):
                        raise ValidationError(
                            f"Validation failed for parameter '{param_name}'",
                            details={'value': str(value), 'function': func.__name__}
                        )
            
            return func(*args, **kwargs)
        return wrapper
    return decorator

# ============================================================================
# ERROR RESPONSE BUILDERS
# ============================================================================

def build_error_response(error: Exception, status_code: int = 500, 
                        request_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build standardized error response for Lambda.
    
    Usage:
        return build_error_response(e, status_code=400, request_id=context.aws_request_id)
    """
    import json
    
    error_data = {
        'error': True,
        'error_type': type(error).__name__,
        'message': str(error),
        'timestamp': datetime.utcnow().isoformat()
    }
    
    if request_id:
        error_data['request_id'] = request_id
    
    # Add details if it's our custom exception
    if isinstance(error, AutomationError):
        error_data.update(error.to_dict())
    
    return {
        'statusCode': status_code,
        'body': json.dumps(error_data),
        'headers': {
            'Content-Type': 'application/json',
            'X-Error-Type': type(error).__name__
        }
    }

def build_success_response(data: Any, status_code: int = 200, 
                          request_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build standardized success response for Lambda.
    
    Usage:
        return build_success_response({'ticket_id': '123'}, request_id=context.aws_request_id)
    """
    import json
    
    response_data = {
        'success': True,
        'data': data,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    if request_id:
        response_data['request_id'] = request_id
    
    return {
        'statusCode': status_code,
        'body': json.dumps(response_data),
        'headers': {
            'Content-Type': 'application/json'
        }
    }

# ============================================================================
# SAFE EXECUTION CONTEXT
# ============================================================================

class SafeExecutionContext:
    """
    Context manager for safe execution with automatic rollback on error.
    
    Usage:
        with SafeExecutionContext() as ctx:
            instance_id = create_instance()
            ctx.add_rollback(terminate_instance, instance_id)
            
            sg_id = create_security_group()
            ctx.add_rollback(delete_security_group, sg_id)
    """
    
    def __init__(self, auto_rollback: bool = True):
        self.rollback_manager = RollbackManager()
        self.auto_rollback = auto_rollback
        self.error_occurred = False
    
    def __enter__(self):
        return self.rollback_manager
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error_occurred = True
            logger.error(f"Error in safe execution context: {exc_val}")
            
            if self.auto_rollback:
                logger.warning("Executing automatic rollback")
                rollback_result = self.rollback_manager.execute_rollback()
                logger.info(f"Rollback completed: {rollback_result}")
        
        # Don't suppress the exception
        return False

# ============================================================================
# RETRY WITH ERROR HANDLING
# ============================================================================

def retry_on_error(max_attempts: int = 3, delay: float = 1.0, 
                  backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Decorator to retry function on specific exceptions.
    
    Usage:
        @retry_on_error(max_attempts=3, exceptions=(ClientError, TimeoutError))
        def call_aws_api():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        logger.warning(
                            f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {current_delay}s..."
                        )
                        import time
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            
            raise last_exception
        return wrapper
    return decorator
