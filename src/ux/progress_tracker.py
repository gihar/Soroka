"""
Система отслеживания прогресса обработки файлов (оптимизированная)
"""

import asyncio
from typing import Dict, Any, Callable, Optional
from aiogram import Bot
from aiogram.types import Message
from loguru import logger
from datetime import datetime, timedelta


class ProgressStage:
    """Упрощенный этап обработки"""
    
    def __init__(self, name: str, emoji: str, description: str):
        self.name = name
        self.emoji = emoji  
        self.description = description
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.is_active = False
        self.is_completed = False


class ProgressTracker:
    """Упрощенный трекер прогресса"""
    
    def __init__(self, bot: Bot, chat_id: int, message: Message):
        self.bot = bot
        self.chat_id = chat_id
        self.message = message
        self.stages: Dict[str, ProgressStage] = {}
        self.current_stage: Optional[str] = None
        self.start_time = datetime.now()
        self.update_task: Optional[asyncio.Task] = None
        self.update_interval = 5  # Увеличили интервал до 5 секунд
        
    def add_stage(self, stage_id: str, name: str, emoji: str, description: str):
        """Добавить этап обработки"""
        self.stages[stage_id] = ProgressStage(name, emoji, description)
    
    def setup_default_stages(self):
        """Настройка упрощенных этапов обработки"""
        self.stages = {}
        
        # Объединили технические этапы в более понятные для пользователя
        self.add_stage(
            "preparation", "Подготовка", "📁", 
            "Подготавливаю файл к обработке..."
        )
        self.add_stage(
            "transcription", "Транскрипция", "🎯", 
            "Преобразую аудио в текст..."
        )
        self.add_stage(
            "analysis", "Анализ", "🤖", 
            "Анализирую содержание и создаю протокол..."
        )
    
    async def start_stage(self, stage_id: str):
        """Начать выполнение этапа"""
        if stage_id not in self.stages:
            logger.warning(f"Неизвестный этап: {stage_id}")
            return
        
        # Завершаем предыдущий этап
        if self.current_stage:
            await self.complete_stage(self.current_stage)
        
        stage = self.stages[stage_id]
        stage.is_active = True
        stage.started_at = datetime.now()
        self.current_stage = stage_id
        
        logger.info(f"Начат этап: {stage.name}")
        
        # Запускаем автообновление прогресса
        if self.update_task:
            self.update_task.cancel()
        self.update_task = asyncio.create_task(self._auto_update())
        
        await self.update_display()
    
    async def complete_stage(self, stage_id: str, compression_info: dict = None):
        """Завершить этап"""
        if stage_id not in self.stages:
            return
        
        stage = self.stages[stage_id]
        stage.is_active = False
        stage.is_completed = True
        stage.completed_at = datetime.now()
        
        if stage_id == self.current_stage:
            self.current_stage = None
            
        logger.info(f"Завершен этап: {stage.name}")
        
        # Показываем информацию о сжатии только если есть значительная экономия
        if compression_info and compression_info.get("compressed", False):
            ratio = compression_info.get("compression_ratio", 0)
            if ratio > 20:  # Показываем только если сжатие > 20%
                await self._show_compression_info(compression_info)
                return
        
        await self.update_display()
    
    async def _show_compression_info(self, compression_info: dict):
        """Показать упрощенную информацию о сжатии"""
        try:
            original_mb = compression_info.get("original_size_mb", 0)
            compressed_mb = compression_info.get("compressed_size_mb", 0)
            ratio = compression_info.get("compression_ratio", 0)
            
            compression_message = (
                f"🗜️ **Файл оптимизирован!**\n\n"
                f"📊 Размер уменьшен на {ratio:.0f}%\n"
                f"({original_mb:.1f}MB → {compressed_mb:.1f}MB)\n\n"
                f"🔄 Продолжаю обработку..."
            )
            
            await self.message.edit_text(compression_message, parse_mode="Markdown")
            
            # Через 2 секунды возвращаемся к обычному отображению
            await asyncio.sleep(2)
            await self.update_display()
            
        except Exception as e:
            logger.error(f"Ошибка отображения информации о сжатии: {e}")
            await self.update_display()
    
    async def update_stage_progress(self, stage_id: str, progress_percent: float = None, 
                                   progress_text: str = "", compression_info: dict = None):
        """Обновить прогресс конкретного этапа"""
        if stage_id not in self.stages or stage_id != self.current_stage:
            return
        
        # Обрабатываем специальный callback для завершения сжатия
        if progress_text == "compression_complete" and compression_info:
            logger.info(f"Получен callback сжатия: {compression_info}")
            await self._show_compression_info(compression_info)
        else:
            await self.update_display()
    
    async def complete_all(self):
        """Завершить все этапы"""
        if self.update_task:
            self.update_task.cancel()
            
        if self.current_stage:
            await self.complete_stage(self.current_stage)
        
        await self.update_display(final=True)
    
    async def update_display(self, final: bool = False):
        """Обновить отображение прогресса"""
        try:
            text = self._format_progress_text(final)
            await self.message.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка обновления прогресса: {e}")
    
    def _format_progress_text(self, final: bool = False) -> str:
        """Сформировать упрощенный текст с прогрессом"""
        if final:
            total_time = datetime.now() - self.start_time
            return (
                "✅ **Обработка завершена!**\n\n"
                f"⏱️ Время: {total_time.total_seconds():.0f}с\n"
                "📄 Протокол готов и будет отправлен ниже."
            )
        
        text = "🔄 **Обработка файла**\n\n"
        
        for stage_id, stage in self.stages.items():
            if stage.is_completed:
                text += f"✅ {stage.emoji} {stage.name}\n"
            elif stage.is_active:
                # Упрощенный прогресс-бар
                progress_bar = "▰▰▰▰▰▰▰▰▰▰"  # Статичный прогресс-бар
                text += f"🔄 {stage.emoji} {stage.name} {progress_bar}\n"
                text += f"   _{stage.description}_\n"
            else:
                text += f"⏳ {stage.emoji} {stage.name}\n"
        
        # Показываем общее время только если прошло больше 10 секунд
        total_elapsed = (datetime.now() - self.start_time).total_seconds()
        if total_elapsed > 10:
            text += f"\n⏱️ {total_elapsed:.0f}с"
        
        return text
    
    async def _auto_update(self):
        """Автоматическое обновление дисплея"""
        try:
            while self.current_stage:
                await asyncio.sleep(self.update_interval)
                if self.current_stage:  # Проверяем еще раз после сна
                    await self.update_display()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка в авто-обновлении прогресса: {e}")
    
    async def error(self, stage_id: str, error_message: str):
        """Отметить ошибку на этапе"""
        if self.update_task:
            self.update_task.cancel()
        
        stage = self.stages.get(stage_id)
        stage_name = stage.name if stage else stage_id
        
        text = (
            f"❌ **Ошибка при обработке**\n\n"
            f"Этап: {stage_name}\n"
            f"Ошибка: {error_message}\n\n"
            f"Попробуйте загрузить файл еще раз."
        )
        
        try:
            await self.message.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка отображения ошибки: {e}")


class ProgressFactory:
    """Фабрика для создания трекеров прогресса"""
    
    @staticmethod
    async def create_file_processing_tracker(bot: Bot, chat_id: int, 
                                           enable_diarization: bool = True) -> ProgressTracker:
        """Создать трекер для обработки файлов"""
        # Создаем начальное сообщение
        initial_message = await bot.send_message(
            chat_id, 
            "🔄 **Начинаю обработку файла...**\n\n⏳ Инициализация...",
            parse_mode="Markdown"
        )
        
        tracker = ProgressTracker(bot, chat_id, initial_message)
        tracker.setup_default_stages()
        
        return tracker
