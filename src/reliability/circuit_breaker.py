"""
Circuit Breaker для защиты от каскадных сбоев
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass
from loguru import logger


class CircuitBreakerState(Enum):
    """Состояния Circuit Breaker"""
    CLOSED = "closed"      # Нормальная работа
    OPEN = "open"          # Блокирует все запросы
    HALF_OPEN = "half_open"  # Тестирует восстановление


@dataclass
class CircuitBreakerConfig:
    """Конфигурация Circuit Breaker"""
    failure_threshold: int = 5      # Количество ошибок для открытия
    recovery_timeout: float = 60.0  # Время до попытки восстановления (сек)
    success_threshold: int = 3      # Количество успехов для закрытия
    timeout: float = 30.0           # Таймаут операции


class CircuitBreakerStats:
    """Статистика Circuit Breaker"""
    
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_failure_time: Optional[float] = None
        self.state_changes = 0
    
    def record_success(self):
        """Записать успешный запрос"""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
    
    def record_failure(self):
        """Записать неудачный запрос"""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
    
    def record_state_change(self):
        """Записать смену состояния"""
        self.state_changes += 1
    
    @property
    def failure_rate(self) -> float:
        """Получить процент ошибок"""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100


class CircuitBreakerError(Exception):
    """Исключение когда Circuit Breaker открыт"""
    
    def __init__(self, service_name: str, state: CircuitBreakerState):
        self.service_name = service_name
        self.state = state
        super().__init__(f"Circuit breaker для {service_name} в состоянии {state.value}")


class CircuitBreaker:
    """Circuit Breaker для защиты сервисов"""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
    
    async def _should_attempt_reset(self) -> bool:
        """Проверить, стоит ли попытаться сбросить состояние"""
        if self.state != CircuitBreakerState.OPEN:
            return False
        
        if self.stats.last_failure_time is None:
            return False
        
        time_since_last_failure = time.time() - self.stats.last_failure_time
        return time_since_last_failure >= self.config.recovery_timeout
    
    async def _transition_to_state(self, new_state: CircuitBreakerState):
        """Перейти в новое состояние"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            self.stats.record_state_change()
            
            logger.info(
                f"Circuit breaker '{self.name}' переключен: {old_state.value} -> {new_state.value}"
            )
    
    async def _handle_success(self):
        """Обработать успешный вызов"""
        async with self._lock:
            self.stats.record_success()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                # В полуоткрытом состоянии проверяем достаточно ли успехов
                if self.stats.consecutive_successes >= self.config.success_threshold:
                    await self._transition_to_state(CircuitBreakerState.CLOSED)
            elif self.state == CircuitBreakerState.OPEN:
                # Если были в открытом состоянии, переходим в полуоткрытое
                await self._transition_to_state(CircuitBreakerState.HALF_OPEN)
    
    async def _handle_failure(self):
        """Обработать неудачный вызов"""
        async with self._lock:
            self.stats.record_failure()
            
            if (self.state == CircuitBreakerState.CLOSED and 
                self.stats.consecutive_failures >= self.config.failure_threshold):
                # Переходим в открытое состояние при превышении порога ошибок
                await self._transition_to_state(CircuitBreakerState.OPEN)
            elif self.state == CircuitBreakerState.HALF_OPEN:
                # Возвращаемся в открытое состояние при ошибке в полуоткрытом
                await self._transition_to_state(CircuitBreakerState.OPEN)
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Выполнить функцию через Circuit Breaker"""
        # Проверяем состояние и возможность сброса
        async with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if await self._should_attempt_reset():
                    await self._transition_to_state(CircuitBreakerState.HALF_OPEN)
                else:
                    raise CircuitBreakerError(self.name, self.state)
        
        # Выполняем функцию с таймаутом
        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout
                )
            else:
                result = func(*args, **kwargs)
            
            await self._handle_success()
            return result
            
        except Exception as e:
            await self._handle_failure()
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику"""
        return {
            "name": self.name,
            "state": self.state.value,
            "total_requests": self.stats.total_requests,
            "successful_requests": self.stats.successful_requests,
            "failed_requests": self.stats.failed_requests,
            "consecutive_failures": self.stats.consecutive_failures,
            "consecutive_successes": self.stats.consecutive_successes,
            "failure_rate": self.stats.failure_rate,
            "state_changes": self.stats.state_changes,
            "last_failure_time": self.stats.last_failure_time
        }
    
    async def reset(self):
        """Принудительно сбросить Circuit Breaker"""
        async with self._lock:
            await self._transition_to_state(CircuitBreakerState.CLOSED)
            self.stats = CircuitBreakerStats()
            logger.info(f"Circuit breaker '{self.name}' принудительно сброшен")


# Предустановленные конфигурации
DEFAULT_CIRCUIT_BREAKER_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout=60.0,
    success_threshold=3,
    timeout=30.0
)

FAST_RECOVERY_CONFIG = CircuitBreakerConfig(
    failure_threshold=3,
    recovery_timeout=30.0,
    success_threshold=2,
    timeout=15.0
)

CONSERVATIVE_CONFIG = CircuitBreakerConfig(
    failure_threshold=10,
    recovery_timeout=120.0,
    success_threshold=5,
    timeout=60.0
)
