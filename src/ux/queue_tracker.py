"""
Трекер позиции задачи в очереди
"""

import asyncio
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.utils.telegram_safe import safe_bot_edit_message


class QueuePositionTracker:
    """Отслеживает и отображает позицию задачи в очереди"""
    
    def __init__(self, bot: Bot, chat_id: int, task_id: str, message: Optional[Message] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.task_id = task_id
        self.message = message
        self.message_id: Optional[int] = message.message_id if message else None
        self.last_position: Optional[int] = None
        self.last_total: Optional[int] = None
        self.is_active = True
        self._update_task: Optional[asyncio.Task] = None
        self._last_text = ""
    
    def create_cancel_button(self) -> InlineKeyboardMarkup:
        """Создать кнопку отмены задачи"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отменить задачу",
                callback_data=f"cancel_task_{self.task_id}"
            )]
        ])
    
    def _format_queue_message(self, position: int, total_in_queue: int) -> str:
        """Форматировать сообщение о позиции в очереди"""
        if position == 0:
            # Задача на первом месте - скоро начнется обработка
            return (
                "🔄 **Ваша задача готова к обработке**\n\n"
                "⏳ Ожидаем освобождения ресурсов...\n"
                f"📊 Задач в очереди: {total_in_queue}"
            )
        elif position == 1:
            return (
                "🕐 **Задача в очереди**\n\n"
                f"📍 Впереди: **{position} задача**\n"
                f"📊 Всего в очереди: {total_in_queue}\n\n"
                "⚡ Скоро начнем обработку!"
            )
        elif position <= 3:
            return (
                "🕐 **Задача в очереди**\n\n"
                f"📍 Впереди: **{position} задачи**\n"
                f"📊 Всего в очереди: {total_in_queue}\n\n"
                "⚡ Ваша очередь скоро подойдет!"
            )
        else:
            # Определяем примерное время ожидания (приблизительно 2-3 минуты на задачу)
            estimated_minutes = position * 2.5
            if estimated_minutes < 60:
                time_estimate = f"~{int(estimated_minutes)} мин"
            else:
                hours = int(estimated_minutes / 60)
                minutes = int(estimated_minutes % 60)
                time_estimate = f"~{hours}ч {minutes}мин" if minutes > 0 else f"~{hours}ч"
            
            tasks_word = "задач" if position % 10 == 0 or position % 10 >= 5 or (position % 100 >= 11 and position % 100 <= 14) else (
                "задача" if position % 10 == 1 else "задачи"
            )
            
            return (
                "🕐 **Задача в очереди**\n\n"
                f"📍 Впереди: **{position} {tasks_word}**\n"
                f"📊 Всего в очереди: {total_in_queue}\n"
                f"⏱️ Примерное время ожидания: {time_estimate}\n\n"
                "💡 Вы можете отменить задачу кнопкой ниже"
            )
    
    async def update_position(self, position: int, total_in_queue: int, force: bool = False):
        """Обновить позицию в очереди (обновляется только при изменении)"""
        if not self.is_active:
            return
        
        # Обновляем только если позиция изменилась или force=True
        if not force and position == self.last_position and total_in_queue == self.last_total:
            return
        
        self.last_position = position
        self.last_total = total_in_queue
        
        try:
            text = self._format_queue_message(position, total_in_queue)
            keyboard = self.create_cancel_button()
            
            # Дедупликация: пропускаем если текст не изменился
            if text == self._last_text:
                return
            
            if self.message_id:
                result = await safe_bot_edit_message(
                    self.bot,
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                if result is not None:
                    self._last_text = text
            else:
                # Если message_id еще не установлен, создаем новое сообщение
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                self.message_id = msg.message_id
                self._last_text = text
                
        except Exception as e:
            logger.error(f"Ошибка обновления трекера очереди: {e}")
    
    async def show_processing_started(self):
        """Показать, что обработка началась"""
        if not self.is_active or not self.message_id:
            return
        
        try:
            text = (
                "🔄 **Начинаю обработку файла**\n\n"
                "⏳ Подготовка к обработке..."
            )
            
            result = await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="Markdown"
            )
            if result is not None:
                self._last_text = text
            
        except Exception as e:
            logger.error(f"Ошибка отображения начала обработки: {e}")
    
    async def show_cancelled(self):
        """Показать, что задача отменена"""
        if not self.is_active or not self.message_id:
            return
        
        self.is_active = False
        
        try:
            text = (
                "❌ **Задача отменена**\n\n"
                "Обработка файла была отменена по вашему запросу."
            )
            
            await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка отображения отмены: {e}")
    
    async def show_error(self, error_message: str):
        """Показать ошибку"""
        if not self.is_active or not self.message_id:
            return
        
        self.is_active = False
        
        try:
            text = (
                "❌ **Ошибка при обработке**\n\n"
                f"{error_message}\n\n"
                "Попробуйте загрузить файл снова."
            )
            
            await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка отображения ошибки: {e}")
    
    async def delete_message(self):
        """Удалить сообщение трекера"""
        if not self.message_id:
            return
        
        try:
            await self.bot.delete_message(
                chat_id=self.chat_id,
                message_id=self.message_id
            )
            logger.debug(f"Удалено сообщение очереди {self.message_id}")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение очереди: {e}")
    
    async def stop(self):
        """Остановить отслеживание"""
        self.is_active = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass


class QueueTrackerFactory:
    """Фабрика для создания трекеров очереди"""
    
    @staticmethod
    async def create_tracker(bot: Bot, chat_id: int, task_id: str, 
                           initial_position: int = 0, 
                           total_in_queue: int = 1) -> QueuePositionTracker:
        """Создать трекер с начальным сообщением"""
        tracker = QueuePositionTracker(bot, chat_id, task_id)
        
        # Создаем начальное сообщение
        text = tracker._format_queue_message(initial_position, total_in_queue)
        keyboard = tracker.create_cancel_button()
        
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            tracker.message_id = msg.message_id
            tracker._last_text = text
            tracker.last_position = initial_position
            tracker.last_total = total_in_queue
            
        except Exception as e:
            logger.error(f"Ошибка создания трекера очереди: {e}")
        
        return tracker

