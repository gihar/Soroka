"""
Система повторных попыток (Retry)
"""

import asyncio
import time
from typing import Callable, Any, Type, Union, List, Optional
from functools import wraps
from loguru import logger
import random

from src.exceptions.processing import LLMInsufficientCreditsError


class RetryConfig:
    """Конфигурация для повторных попыток"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[List[Type[Exception]]] = None
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or [Exception]


class RetryManager:
    """Менеджер повторных попыток"""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    def calculate_delay(self, attempt: int) -> float:
        """Вычислить задержку для попытки"""
        # Экспоненциальная задержка
        delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        
        # Ограничиваем максимальной задержкой
        delay = min(delay, self.config.max_delay)
        
        # Добавляем jitter для избежания thundering herd
        if self.config.jitter:
            delay *= (0.5 + random.random() * 0.5)
        
        return delay
    
    def is_retryable_exception(self, exception: Exception) -> bool:
        """Проверить, стоит ли повторять при данном исключении"""
        # Никогда не повторяем при недостатке кредитов
        if isinstance(exception, LLMInsufficientCreditsError):
            return False
        return any(isinstance(exception, exc_type) for exc_type in self.config.retryable_exceptions)
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Выполнить функцию с повторными попытками"""
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                logger.debug(f"Попытка {attempt}/{self.config.max_attempts} для {func.__name__}")
                
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                if attempt > 1:
                    logger.info(f"Успешно выполнено после {attempt} попыток: {func.__name__}")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                if not self.is_retryable_exception(e):
                    logger.error(f"Неповторяемое исключение в {func.__name__}: {e}")
                    raise
                
                if attempt == self.config.max_attempts:
                    logger.error(
                        f"Все попытки исчерпаны для {func.__name__}: {e} "
                        f"(попыток: {self.config.max_attempts})"
                    )
                    raise
                
                delay = self.calculate_delay(attempt)
                logger.warning(
                    f"Попытка {attempt} неудачна для {func.__name__}: {e}. "
                    f"Повтор через {delay:.2f}с"
                )
                
                await asyncio.sleep(delay)
        
        # Этот код не должен достигаться, но на всякий случай
        if last_exception:
            raise last_exception


def retry_on_failure(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[List[Type[Exception]]] = None
):
    """Декоратор для автоматических повторных попыток"""
    
    def decorator(func: Callable) -> Callable:
        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=exponential_base,
            jitter=jitter,
            retryable_exceptions=retryable_exceptions
        )
        retry_manager = RetryManager(config)
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_manager.execute_with_retry(func, *args, **kwargs)
        
        return wrapper
    
    return decorator


# Предустановленные конфигурации для разных случаев
API_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=[
        ConnectionError,
        TimeoutError,
        OSError,
    ]
)

TRANSCRIPTION_RETRY_CONFIG = RetryConfig(
    max_attempts=2,
    base_delay=2.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=[
        RuntimeError,
        OSError,
        FileNotFoundError,
    ]
)

LLM_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=45.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=[
        ConnectionError,
        TimeoutError,
        RuntimeError,
    ]
)
