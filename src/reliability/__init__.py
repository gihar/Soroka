"""
Компоненты для повышения надежности системы
"""

from .retry import RetryManager, retry_on_failure, LLM_RETRY_CONFIG, API_RETRY_CONFIG, TRANSCRIPTION_RETRY_CONFIG
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerConfig,
    DEFAULT_CIRCUIT_BREAKER_CONFIG,
    FAST_RECOVERY_CONFIG,
    CONSERVATIVE_CONFIG,
)
from .rate_limiter import RateLimiter, RateLimitExceeded, global_rate_limiter, OPENAI_API_LIMIT, ANTHROPIC_API_LIMIT, USER_REQUEST_LIMIT
from .health_check import HealthChecker, HealthStatus, health_checker
from .fallback import FallbackManager, FallbackStrategy, create_llm_fallback_manager

# Глобальные экземпляры компонентов
_circuit_breakers = {}
_fallback_managers = {}

def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Получить или создать circuit breaker"""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            config=DEFAULT_CIRCUIT_BREAKER_CONFIG
        )
    return _circuit_breakers[name]

def get_fallback_manager(name: str) -> FallbackManager:
    """Получить или создать fallback manager"""
    if name not in _fallback_managers:
        _fallback_managers[name] = FallbackManager(name)
    return _fallback_managers[name]

__all__ = [
    "RetryManager", "retry_on_failure", "LLM_RETRY_CONFIG", "API_RETRY_CONFIG", "TRANSCRIPTION_RETRY_CONFIG",
    "CircuitBreaker", "CircuitBreakerState", "CircuitBreakerConfig", "DEFAULT_CIRCUIT_BREAKER_CONFIG", "FAST_RECOVERY_CONFIG", "CONSERVATIVE_CONFIG",
    "RateLimiter", "RateLimitExceeded", "global_rate_limiter", "OPENAI_API_LIMIT", "ANTHROPIC_API_LIMIT", "USER_REQUEST_LIMIT",
    "HealthChecker", "HealthStatus", "health_checker",
    "FallbackManager", "FallbackStrategy", "create_llm_fallback_manager",
    "get_circuit_breaker", "get_fallback_manager"
]
