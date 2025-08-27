"""
Система отслеживания прогресса обработки файлов
"""

import asyncio
from typing import Dict, Any, Callable, Optional
from aiogram import Bot
from aiogram.types import Message
from loguru import logger
from datetime import datetime, timedelta


class ProgressStage:
    """Этап обработки с индикацией прогресса"""
    
    def __init__(self, name: str, emoji: str, description: str, 
                 estimated_duration: int = 10):
        self.name = name
        self.emoji = emoji  
        self.description = description
        self.estimated_duration = estimated_duration  # секунды
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.is_active = False
        self.is_completed = False


class ProgressTracker:
    """Трекер прогресса с визуализацией"""
    
    def __init__(self, bot: Bot, chat_id: int, message: Message):
        self.bot = bot
        self.chat_id = chat_id
        self.message = message
        self.stages: Dict[str, ProgressStage] = {}
        self.current_stage: Optional[str] = None
        self.start_time = datetime.now()
        self.update_task: Optional[asyncio.Task] = None
        self.update_interval = 3  # секунды
        
    def add_stage(self, stage_id: str, name: str, emoji: str, 
                  description: str, estimated_duration: int = 10):
        """Добавить этап обработки"""
        self.stages[stage_id] = ProgressStage(
            name, emoji, description, estimated_duration
        )
    
    def setup_default_stages(self):
        """Настройка стандартных этапов обработки"""
        # Сохраняем порядок этапов
        self.stages = {}  # Сбрасываем, чтобы гарантировать порядок
        
        self.add_stage(
            "download", "Скачивание", "⬇️", 
            "Загружаю файл с серверов Telegram...", 5
        )
        self.add_stage(
            "validation", "Проверка", "🔍", 
            "Проверяю формат и размер файла...", 2
        )
        self.add_stage(
            "conversion", "Конвертация", "🔄", 
            "Подготавливаю файл для обработки...", 8
        )
        self.add_stage(
            "transcription", "Транскрипция", "🎯", 
            "Преобразую аудио в текст...", 30
        )
        self.add_stage(
            "diarization", "Диаризация", "👥", 
            "Определяю говорящих...", 20
        )
        self.add_stage(
            "llm_processing", "Генерация", "🤖", 
            "Создаю протокол с помощью ИИ...", 15
        )
        self.add_stage(
            "formatting", "Оформление", "📝", 
            "Форматирую итоговый документ...", 3
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
    
    async def complete_stage(self, stage_id: str):
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
        await self.update_display()
    
    async def update_stage_progress(self, stage_id: str, progress_percent: float = None):
        """Обновить прогресс конкретного этапа"""
        if stage_id not in self.stages or stage_id != self.current_stage:
            return
        
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
        """Сформировать текст с прогрессом"""
        if final:
            total_time = datetime.now() - self.start_time
            return (
                "✅ **Обработка завершена!**\n\n"
                f"⏱️ Общее время: {total_time.total_seconds():.1f} сек\n\n"
                "📄 Протокол готов и будет отправлен ниже."
            )
        
        text = "🔄 **Обработка файла**\n\n"
        
        for stage_id, stage in self.stages.items():
            if stage.is_completed:
                duration = (stage.completed_at - stage.started_at).total_seconds() if stage.started_at else 0
                text += f"✅ {stage.emoji} {stage.name} - {duration:.1f}с\n"
            elif stage.is_active:
                elapsed = (datetime.now() - stage.started_at).total_seconds() if stage.started_at else 0
                progress_bar = self._create_progress_bar(elapsed, stage.estimated_duration)
                text += f"🔄 {stage.emoji} {stage.name} {progress_bar}\n"
                text += f"   _{stage.description}_\n"
            else:
                text += f"⏳ {stage.emoji} {stage.name}\n"
        
        # Показываем общее время
        total_elapsed = (datetime.now() - self.start_time).total_seconds()
        text += f"\n⏱️ Общее время: {total_elapsed:.0f}с"
        
        return text
    
    def _create_progress_bar(self, elapsed: float, estimated: float) -> str:
        """Создать визуальный индикатор прогресса"""
        if estimated <= 0:
            return "..."
        
        progress = min(elapsed / estimated, 1.0)
        filled = int(progress * 10)
        bar = "█" * filled + "░" * (10 - filled)
        percentage = int(progress * 100)
        
        return f"[{bar}] {percentage}%"
    
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
        
        # Убираем диаризацию если отключена
        if not enable_diarization and "diarization" in tracker.stages:
            del tracker.stages["diarization"]
        
        return tracker
