"""
Система управления Telegram API rate limiting и flood control
"""

import asyncio
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from collections import deque
from loguru import logger

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message


@dataclass
class FloodControlState:
    """Состояние flood control"""
    is_active: bool = False
    blocked_until: float = 0.0
    retry_after: int = 0
    blocked_chats: Dict[int, float] = field(default_factory=dict)
    total_blocks: int = 0
    last_block_time: Optional[float] = None


@dataclass
class QueuedMessage:
    """Сообщение в очереди"""
    chat_id: int
    text: str
    kwargs: Dict[str, Any]
    callback: Optional[Callable] = None
    priority: int = 0
    created_at: float = field(default_factory=time.time)


class TelegramFloodControl:
    """Управление состоянием flood control от Telegram"""
    
    def __init__(self):
        self.state = FloodControlState()
        self._lock = asyncio.Lock()
    
    async def register_flood_control(self, retry_after: int, chat_id: Optional[int] = None):
        """Зарегистрировать flood control блокировку"""
        async with self._lock:
            self.state.is_active = True
            self.state.blocked_until = time.time() + retry_after
            self.state.retry_after = retry_after
            self.state.total_blocks += 1
            self.state.last_block_time = time.time()
            
            if chat_id:
                self.state.blocked_chats[chat_id] = self.state.blocked_until
            
            logger.critical(
                f"🚨 FLOOD CONTROL активирован! "
                f"Блокировка на {retry_after} секунд (до {time.strftime('%H:%M:%S', time.localtime(self.state.blocked_until))})"
            )
            
            # Если блокировка долгая, логируем особо
            if retry_after > 300:  # > 5 минут
                logger.critical(
                    f"⚠️ КРИТИЧЕСКАЯ БЛОКИРОВКА: {retry_after // 60} минут! "
                    f"Требуется проверка причин."
                )
    
    async def is_blocked(self, chat_id: Optional[int] = None) -> tuple[bool, float]:
        """Проверить, активна ли блокировка"""
        async with self._lock:
            current_time = time.time()
            
            # Проверяем глобальную блокировку
            if self.state.is_active:
                if current_time < self.state.blocked_until:
                    remaining = self.state.blocked_until - current_time
                    return True, remaining
                else:
                    # Блокировка истекла
                    self.state.is_active = False
                    logger.info("✅ Flood control снят")
            
            # Проверяем блокировку для конкретного чата
            if chat_id and chat_id in self.state.blocked_chats:
                if current_time < self.state.blocked_chats[chat_id]:
                    remaining = self.state.blocked_chats[chat_id] - current_time
                    return True, remaining
                else:
                    del self.state.blocked_chats[chat_id]
            
            return False, 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику flood control"""
        current_time = time.time()
        
        return {
            "is_active": self.state.is_active,
            "retry_after": self.state.retry_after if self.state.is_active else 0,
            "time_remaining": max(0, self.state.blocked_until - current_time) if self.state.is_active else 0,
            "blocked_chats_count": len(self.state.blocked_chats),
            "total_blocks": self.state.total_blocks,
            "last_block_time": self.state.last_block_time,
            "blocked_until": self.state.blocked_until if self.state.is_active else None
        }


class TelegramMessageQueue:
    """Очередь сообщений для отправки после снятия flood control"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.queue: deque[QueuedMessage] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
    
    async def enqueue(self, message: QueuedMessage) -> bool:
        """Добавить сообщение в очередь"""
        async with self._lock:
            if len(self.queue) >= self.max_size:
                logger.warning(
                    f"Очередь сообщений переполнена ({self.max_size}). "
                    f"Удаляем старое сообщение."
                )
                # Удаляем самое старое неприоритетное сообщение
                for i, msg in enumerate(self.queue):
                    if msg.priority == 0:
                        del self.queue[i]
                        break
            
            self.queue.append(message)
            logger.debug(f"Сообщение добавлено в очередь (размер: {len(self.queue)})")
            return True
    
    async def dequeue_all(self) -> list[QueuedMessage]:
        """Извлечь все сообщения из очереди"""
        async with self._lock:
            messages = list(self.queue)
            self.queue.clear()
            return messages
    
    def get_size(self) -> int:
        """Получить размер очереди"""
        return len(self.queue)


class TelegramRateLimiter:
    """
    Менеджер для безопасной работы с Telegram API
    с превентивным rate limiting и обработкой flood control
    """
    
    def __init__(self):
        self.flood_control = TelegramFloodControl()
        self.message_queue = TelegramMessageQueue()
        
        # Rate limiting (консервативные значения)
        self.messages_per_second = 20
        self.burst_limit = 3
        
        # Отслеживание отправленных сообщений
        self.sent_messages: deque[float] = deque(maxlen=100)
        self._rate_lock = asyncio.Lock()
    
    async def check_rate_limit(self) -> tuple[bool, float]:
        """
        Проверить rate limit перед отправкой
        Returns: (allowed, wait_time)
        """
        async with self._rate_lock:
            current_time = time.time()
            
            # Удаляем старые записи (старше 1 секунды)
            while self.sent_messages and current_time - self.sent_messages[0] > 1.0:
                self.sent_messages.popleft()
            
            # Проверяем лимит за последнюю секунду
            if len(self.sent_messages) >= self.messages_per_second:
                # Вычисляем время ожидания
                oldest = self.sent_messages[0]
                wait_time = 1.0 - (current_time - oldest)
                return False, max(0, wait_time)
            
            # Проверяем burst лимит (последние 3 сообщения)
            recent_messages = [t for t in self.sent_messages if current_time - t < 0.1]
            if len(recent_messages) >= self.burst_limit:
                return False, 0.1
            
            return True, 0.0
    
    async def register_sent_message(self):
        """Зарегистрировать отправленное сообщение"""
        async with self._rate_lock:
            self.sent_messages.append(time.time())
    
    async def safe_send_with_retry(
        self,
        send_func: Callable,
        *args,
        chat_id: Optional[int] = None,
        max_retries: int = 2,
        **kwargs
    ) -> Optional[Any]:
        """
        Безопасно отправить сообщение с retry логикой
        
        Args:
            send_func: Функция отправки (message.answer, message.edit_text и т.д.)
            chat_id: ID чата для проверки блокировки
            max_retries: Максимальное количество попыток
        """
        # Проверяем flood control
        is_blocked, remaining = await self.flood_control.is_blocked(chat_id)
        if is_blocked:
            logger.warning(
                f"Сообщение заблокировано flood control. "
                f"Осталось {remaining:.0f} секунд."
            )
            return None
        
        for attempt in range(max_retries + 1):
            try:
                # Проверяем rate limit
                allowed, wait_time = await self.check_rate_limit()
                if not allowed:
                    logger.debug(f"Rate limit: ожидание {wait_time:.2f}с")
                    await asyncio.sleep(wait_time)
                
                # Отправляем сообщение
                result = await send_func(*args, **kwargs)
                
                # Регистрируем успешную отправку
                await self.register_sent_message()
                
                return result
            
            except TelegramRetryAfter as e:
                retry_after = e.retry_after
                
                # Регистрируем flood control
                await self.flood_control.register_flood_control(retry_after, chat_id)
                
                # Если блокировка короткая и это не последняя попытка, ждем
                if retry_after <= 5 and attempt < max_retries:
                    logger.warning(
                        f"Короткая блокировка {retry_after}с, "
                        f"ожидание (попытка {attempt + 1}/{max_retries + 1})"
                    )
                    await asyncio.sleep(retry_after + 0.5)
                    continue
                else:
                    logger.error(
                        f"Flood control: {retry_after}с. "
                        f"Сообщение не отправлено."
                    )
                    return None
            
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                return None
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить полную статистику"""
        return {
            "flood_control": self.flood_control.get_stats(),
            "queue_size": self.message_queue.get_size(),
            "messages_sent_last_second": len([
                t for t in self.sent_messages 
                if time.time() - t < 1.0
            ]),
            "rate_limit": {
                "messages_per_second": self.messages_per_second,
                "burst_limit": self.burst_limit
            }
        }


# Глобальный экземпляр
telegram_rate_limiter = TelegramRateLimiter()

