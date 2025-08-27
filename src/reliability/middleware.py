"""
Middleware для мониторинга и обработки ошибок
"""

import time
import asyncio
from typing import Callable, Any, Dict, Optional
from functools import wraps
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User, Update, Message
from loguru import logger

from exceptions import BotException
from reliability.health_check import health_checker
from reliability.rate_limiter import global_rate_limiter, USER_REQUEST_LIMIT, RateLimitExceeded


class ErrorHandlingMiddleware(BaseMiddleware):
    """Middleware для централизованной обработки ошибок"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        
        except RateLimitExceeded as e:
            logger.warning(f"Rate limit exceeded: {e}")
            if isinstance(event, Message):
                await event.answer(
                    f"⏱️ Слишком много запросов. Попробуйте через {e.retry_after:.0f} секунд."
                )
            return
        
        except BotException as e:
            logger.error(f"Bot exception: {e.to_dict()}")
            if isinstance(event, Message):
                await event.answer(f"❌ {e.message}")
            return
        
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            if isinstance(event, Message):
                await event.answer(
                    "❌ Произошла неожиданная ошибка. "
                    "Попробуйте еще раз или обратитесь в поддержку."
                )
            return


class MonitoringMiddleware(BaseMiddleware):
    """Middleware для мониторинга производительности и использования"""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.processing_times = []
        self.user_activity = {}
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        start_time = time.time()
        self.request_count += 1
        
        # Получаем информацию о пользователе
        user: Optional[User] = data.get("event_from_user")
        user_id = user.id if user else None
        
        if user_id:
            self.user_activity[user_id] = time.time()
        
        try:
            result = await handler(event, data)
            
            # Логируем успешный запрос
            processing_time = time.time() - start_time
            self.processing_times.append(processing_time)
            
            # Ограничиваем размер массива времен обработки
            if len(self.processing_times) > 1000:
                self.processing_times = self.processing_times[-500:]
            
            logger.debug(
                f"Request processed in {processing_time:.3f}s "
                f"(user: {user_id}, type: {type(event).__name__})"
            )
            
            return result
        
        except Exception as e:
            self.error_count += 1
            processing_time = time.time() - start_time
            
            logger.error(
                f"Request failed after {processing_time:.3f}s "
                f"(user: {user_id}, type: {type(event).__name__}): {e}"
            )
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику мониторинга"""
        if not self.processing_times:
            avg_time = 0
            max_time = 0
            min_time = 0
        else:
            avg_time = sum(self.processing_times) / len(self.processing_times)
            max_time = max(self.processing_times)
            min_time = min(self.processing_times)
        
        return {
            "total_requests": self.request_count,
            "total_errors": self.error_count,
            "error_rate": (self.error_count / max(1, self.request_count)) * 100,
            "average_processing_time": avg_time,
            "max_processing_time": max_time,
            "min_processing_time": min_time,
            "active_users": len(self.user_activity),
            "recent_processing_times": self.processing_times[-10:] if self.processing_times else []
        }


class RateLimitingMiddleware(BaseMiddleware):
    """Middleware для rate limiting"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Применяем rate limiting только к сообщениям от пользователей
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            
            # Создаем персональный rate limiter для пользователя
            user_limiter = global_rate_limiter.get_or_create(
                f"user_messages_{user_id}",
                USER_REQUEST_LIMIT
            )
            
            # Проверяем лимит
            await user_limiter.acquire()
        
        return await handler(event, data)


class HealthCheckMiddleware(BaseMiddleware):
    """Middleware для проверки здоровья системы"""
    
    def __init__(self):
        self.last_health_check = 0
        self.health_check_interval = 60  # Проверяем каждую минуту
        self.system_healthy = True
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        current_time = time.time()
        
        # Периодически проверяем здоровье системы
        if current_time - self.last_health_check > self.health_check_interval:
            try:
                overall_status = health_checker.get_overall_status()
                self.system_healthy = overall_status.value in ["healthy", "degraded"]
                self.last_health_check = current_time
                
                if not self.system_healthy:
                    logger.warning(f"System health check failed: {overall_status.value}")
                
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                self.system_healthy = False
        
        # Если система нездорова, уведомляем пользователя
        if not self.system_healthy and isinstance(event, Message):
            # Не блокируем полностью, но предупреждаем
            await event.answer(
                "⚠️ Система работает в ограниченном режиме. "
                "Обработка может занять больше времени."
            )
        
        return await handler(event, data)


def monitor_async_function(func_name: str):
    """Декоратор для мониторинга асинхронных функций"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                processing_time = time.time() - start_time
                
                logger.debug(f"{func_name} completed in {processing_time:.3f}s")
                return result
            
            except Exception as e:
                processing_time = time.time() - start_time
                logger.error(f"{func_name} failed after {processing_time:.3f}s: {e}")
                raise
        
        return wrapper
    return decorator


def monitor_sync_function(func_name: str):
    """Декоратор для мониторинга синхронных функций"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                processing_time = time.time() - start_time
                
                logger.debug(f"{func_name} completed in {processing_time:.3f}s")
                return result
            
            except Exception as e:
                processing_time = time.time() - start_time
                logger.error(f"{func_name} failed after {processing_time:.3f}s: {e}")
                raise
        
        return wrapper
    return decorator


# Глобальные экземпляры middleware
error_handling_middleware = ErrorHandlingMiddleware()
monitoring_middleware = MonitoringMiddleware()
rate_limiting_middleware = RateLimitingMiddleware()
health_check_middleware = HealthCheckMiddleware()
