"""
Middleware для мониторинга и обработки ошибок
"""

import time
import asyncio
from typing import Callable, Any, Dict, Optional
from functools import wraps
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User, Update, Message
from aiogram.exceptions import TelegramRetryAfter
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
        
        except TelegramRetryAfter as e:
            # Импортируем здесь, чтобы избежать циклических зависимостей
            from src.reliability.telegram_rate_limiter import telegram_rate_limiter
            
            # Регистрируем flood control
            chat_id = event.chat.id if isinstance(event, Message) and event.chat else None
            await telegram_rate_limiter.flood_control.register_flood_control(
                e.retry_after, 
                chat_id
            )
            
            # НЕ отправляем сообщение пользователю, чтобы не усугублять flood control
            logger.error(
                f"Telegram Flood Control: заблокировано на {e.retry_after}с "
                f"(чат: {chat_id}). Сообщения не отправляются."
            )
            return
        
        except RateLimitExceeded as e:
            logger.warning(f"Rate limit exceeded: {e}")
            # Пытаемся отправить только если блокировка короткая
            if e.retry_after < 5 and isinstance(event, Message):
                try:
                    await event.answer(
                        f"⏱️ Слишком много запросов. Попробуйте через {e.retry_after:.0f} секунд."
                    )
                except TelegramRetryAfter:
                    # Игнорируем, если и это вызвало flood control
                    logger.debug("Не удалось отправить сообщение о rate limit")
            return
        
        except BotException as e:
            logger.error(f"Bot exception: {e.to_dict()}")
            if isinstance(event, Message):
                # Используем безопасную отправку
                try:
                    from src.utils.telegram_safe import safe_answer
                    await safe_answer(event, f"❌ {e.message}")
                except Exception:
                    logger.error("Не удалось отправить сообщение об ошибке пользователю")
            return
        
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            if isinstance(event, Message):
                # Используем безопасную отправку
                try:
                    from src.utils.telegram_safe import safe_answer
                    await safe_answer(
                        event,
                        "❌ Произошла неожиданная ошибка. "
                        "Попробуйте еще раз или обратитесь в поддержку."
                    )
                except Exception:
                    logger.error("Не удалось отправить сообщение об ошибке пользователю")
            return


class MonitoringMiddleware(BaseMiddleware):
    """Middleware для мониторинга производительности и использования"""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.processing_times = []
        self.user_activity = {}
        self.protocol_request_count = 0
        self.protocol_error_count = 0
        self.protocol_processing_times = []
        self.protocol_users = set()
    
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

    def record_protocol_request(
        self,
        user_id: Optional[int],
        duration: float,
        success: bool = True
    ) -> None:
        """Зафиксировать запрос на создание протокола"""
        self.protocol_request_count += 1
        if not success:
            self.protocol_error_count += 1

        if user_id:
            self.protocol_users.add(user_id)

        if duration is not None:
            self.protocol_processing_times.append(duration)
            if len(self.protocol_processing_times) > 1000:
                self.protocol_processing_times = self.protocol_processing_times[-500:]

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику мониторинга"""
        relevant_times = (
            self.protocol_processing_times
            if self.protocol_processing_times
            else self.processing_times
        )

        if not relevant_times:
            avg_time = 0
            max_time = 0
            min_time = 0
        else:
            avg_time = sum(relevant_times) / len(relevant_times)
            max_time = max(relevant_times)
            min_time = min(relevant_times)

        total_requests = self.protocol_request_count
        total_errors = self.protocol_error_count
        error_rate = (
            (total_errors / max(1, total_requests)) * 100
            if total_requests > 0
            else 0
        )

        active_users = (
            len(self.protocol_users)
            if self.protocol_users
            else len(self.user_activity)
        )

        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": error_rate,
            "average_processing_time": avg_time,
            "max_processing_time": max_time,
            "min_processing_time": min_time,
            "active_users": active_users,
            "recent_processing_times": relevant_times[-10:] if relevant_times else [],
            "total_events": self.request_count,
            "total_event_errors": self.error_count
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
            # Исключаем административные команды из предупреждений
            admin_commands = [
                '/status', '/health', '/stats', '/export_stats', '/reset_reliability',
                '/transcription_mode', '/admin_help', '/performance', '/optimize',
                '/cleanup', '/cleanup_force'
            ]
            
            if event.text and event.text.strip() not in admin_commands:
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
