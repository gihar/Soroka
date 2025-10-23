"""
Rate Limiter для контроля нагрузки
"""

import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass
from loguru import logger


class RateLimitExceeded(Exception):
    """Исключение при превышении лимита запросов"""
    
    def __init__(self, limit: int, window: float, retry_after: float):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        super().__init__(
            f"Превышен лимит {limit} запросов за {window}с. "
            f"Повторите через {retry_after:.1f}с"
        )


@dataclass
class RateLimitConfig:
    """Конфигурация Rate Limiter"""
    requests_per_window: int    # Количество запросов
    window_size: float          # Размер окна в секундах
    burst_limit: Optional[int] = None  # Лимит пиковых запросов


class TokenBucket:
    """Реализация алгоритма Token Bucket"""
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity        # Максимальное количество токенов
        self.tokens = capacity          # Текущее количество токенов
        self.refill_rate = refill_rate  # Скорость пополнения токенов/сек
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Попытаться потребить токены"""
        async with self._lock:
            now = time.time()
            
            # Пополняем токены
            time_passed = now - self.last_refill
            tokens_to_add = time_passed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now
            
            # Проверяем доступность токенов
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False
    
    def time_until_available(self, tokens: int = 1) -> float:
        """Время до доступности токенов"""
        if self.tokens >= tokens:
            return 0.0
        
        needed_tokens = tokens - self.tokens
        return needed_tokens / self.refill_rate


class SlidingWindowLimiter:
    """Реализация алгоритма Sliding Window"""
    
    def __init__(self, limit: int, window_size: float):
        self.limit = limit
        self.window_size = window_size
        self.requests: list = []
        self._lock = asyncio.Lock()
    
    async def is_allowed(self) -> tuple[bool, float]:
        """Проверить разрешен ли запрос"""
        async with self._lock:
            now = time.time()
            
            # Удаляем старые запросы
            cutoff = now - self.window_size
            self.requests = [req_time for req_time in self.requests if req_time > cutoff]
            
            # Проверяем лимит
            if len(self.requests) < self.limit:
                self.requests.append(now)
                return True, 0.0
            
            # Вычисляем время до следующего доступного слота
            oldest_request = min(self.requests)
            retry_after = (oldest_request + self.window_size) - now
            
            return False, max(0, retry_after)


class RateLimiter:
    """Основной класс Rate Limiter"""
    
    def __init__(self, name: str, config: RateLimitConfig):
        self.name = name
        self.config = config
        
        # Используем Token Bucket для основного лимита
        refill_rate = config.requests_per_window / config.window_size
        self.token_bucket = TokenBucket(config.requests_per_window, refill_rate)
        
        # Sliding Window для burst защиты
        if config.burst_limit:
            self.burst_limiter = SlidingWindowLimiter(
                config.burst_limit, 
                min(config.window_size, 10.0)  # Короткое окно для burst
            )
        else:
            self.burst_limiter = None
        
        self.total_requests = 0
        self.blocked_requests = 0
    
    async def acquire(self, tokens: int = 1) -> None:
        """Получить разрешение на выполнение запроса"""
        self.total_requests += 1
        
        # Проверяем burst лимит
        if self.burst_limiter:
            burst_allowed, burst_retry_after = await self.burst_limiter.is_allowed()
            if not burst_allowed:
                self.blocked_requests += 1
                logger.warning(
                    f"Rate limiter '{self.name}': заблокирован burst запрос. "
                    f"Повтор через {burst_retry_after:.1f}с"
                )
                raise RateLimitExceeded(
                    self.config.burst_limit or 0,
                    10.0,
                    burst_retry_after
                )
        
        # Проверяем основной лимит
        if not await self.token_bucket.consume(tokens):
            self.blocked_requests += 1
            retry_after = self.token_bucket.time_until_available(tokens)
            
            logger.warning(
                f"Rate limiter '{self.name}': лимит исчерпан. "
                f"Повтор через {retry_after:.1f}с"
            )
            
            raise RateLimitExceeded(
                self.config.requests_per_window,
                self.config.window_size,
                retry_after
            )
        
        logger.debug(f"Rate limiter '{self.name}': запрос разрешен")
    
    async def try_acquire(self, tokens: int = 1) -> bool:
        """Попытаться получить разрешение без исключения"""
        try:
            await self.acquire(tokens)
            return True
        except RateLimitExceeded:
            return False
    
    def get_stats(self) -> Dict[str, any]:
        """Получить статистику"""
        return {
            "name": self.name,
            "total_requests": self.total_requests,
            "blocked_requests": self.blocked_requests,
            "block_rate": (self.blocked_requests / max(1, self.total_requests)) * 100,
            "available_tokens": self.token_bucket.tokens,
            "token_capacity": self.token_bucket.capacity,
            "requests_per_window": self.config.requests_per_window,
            "window_size": self.config.window_size,
            "burst_limit": self.config.burst_limit
        }


class GlobalRateLimiter:
    """Глобальный менеджер Rate Limiter'ов"""
    
    def __init__(self):
        self.limiters: Dict[str, RateLimiter] = {}
    
    def get_or_create(self, name: str, config: RateLimitConfig) -> RateLimiter:
        """Получить или создать лимитер"""
        if name not in self.limiters:
            self.limiters[name] = RateLimiter(name, config)
            logger.info(f"Создан rate limiter '{name}': {config}")
        
        return self.limiters[name]
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Получить статистику всех лимитеров"""
        return {name: limiter.get_stats() for name, limiter in self.limiters.items()}


# Глобальный экземпляр
global_rate_limiter = GlobalRateLimiter()


# Предустановленные конфигурации
TELEGRAM_API_LIMIT = RateLimitConfig(
    requests_per_window=20,  # 20 сообщений (консервативно, реальный лимит ~30/сек)
    window_size=1.0,         # за секунду
    burst_limit=3            # максимум 3 подряд для защиты от всплесков
)

OPENAI_API_LIMIT = RateLimitConfig(
    requests_per_window=60,   # 60 запросов  
    window_size=60.0,         # за минуту
    burst_limit=20            # максимум 20 запросов подряд
)

ANTHROPIC_API_LIMIT = RateLimitConfig(
    requests_per_window=100,  # 100 запросов
    window_size=60.0,         # за минуту  
    burst_limit=30            # максимум 30 запросов подряд
)

USER_REQUEST_LIMIT = RateLimitConfig(
    requests_per_window=10,   # 10 запросов
    window_size=60.0,         # за минуту от одного пользователя
    burst_limit=5             # максимум 5 запросов подряд
)
