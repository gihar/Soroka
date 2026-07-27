"""
Трекер позиции задачи в очереди
"""

import asyncio
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.utils.telegram_safe import safe_bot_edit_message, safe_send_message
from src.ux.html_text import esc


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
        """Создать кнопку отмены задачи (без эмодзи: отмена — не ошибка)."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отменить задачу",
                callback_data=f"cancel_task_{self.task_id}"
            )]
        ])

    @staticmethod
    def _tasks_word(position: int) -> str:
        """Русское склонение «задача/задачи/задач» по числу впереди стоящих."""
        if position % 100 in (11, 12, 13, 14):
            return "задач"
        if position % 10 == 1:
            return "задача"
        if position % 10 in (2, 3, 4):
            return "задачи"
        return "задач"

    def _format_queue_message(self, position: int, total_in_queue: int) -> str:
        """Сообщение о позиции в очереди: факты без SMM-тона.

        Позиция, всего в очереди и оценка ожидания — этого достаточно; отмена
        всегда доступна кнопкой ниже. Никаких «Скоро начнём!» и советов-подсказок.
        """
        if position == 0:
            return (
                "<b>Задача готова к обработке</b>\n\n"
                "Ожидаем освобождения ресурсов.\n"
                f"Задач в очереди: {total_in_queue}"
            )

        lines = [
            "<b>Задача в очереди</b>",
            "",
            f"Впереди: {position} {self._tasks_word(position)}",
            f"Всего в очереди: {total_in_queue}",
        ]

        if position > 3:
            # Примерное время ожидания (приблизительно 2-3 минуты на задачу).
            estimated_minutes = position * 2.5
            if estimated_minutes < 60:
                time_estimate = f"~{int(estimated_minutes)} мин"
            else:
                hours = int(estimated_minutes / 60)
                minutes = int(estimated_minutes % 60)
                time_estimate = f"~{hours}ч {minutes}мин" if minutes > 0 else f"~{hours}ч"
            lines.append(f"Примерное время ожидания: {time_estimate}")

        return "\n".join(lines)
    
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
                    parse_mode="HTML"
                )
                if result is not None:
                    self._last_text = text
            else:
                # Если message_id еще не установлен, создаем новое сообщение
                msg = await safe_send_message(self.bot,
                    chat_id=self.chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                if msg is not None:
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
                "<b>Начинаю обработку файла</b>\n\n"
                "⏳ Подготовка к обработке..."
            )
            
            result = await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="HTML"
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
                "<b>Задача отменена</b>\n\n"
                "Обработка файла была отменена по вашему запросу."
            )
            
            await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="HTML"
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
                "❌ <b>Ошибка при обработке</b>\n\n"
                f"{esc(error_message)}\n\n"
                "Попробуйте загрузить файл снова."
            )
            
            await safe_bot_edit_message(
                self.bot,
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode="HTML"
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
            msg = await safe_send_message(bot,
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            if msg is not None:
                tracker.message_id = msg.message_id
                tracker._last_text = text
                tracker.last_position = initial_position
                tracker.last_total = total_in_queue
            
        except Exception as e:
            logger.error(f"Ошибка создания трекера очереди: {e}")
        
        return tracker

