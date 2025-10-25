"""
Система отслеживания прогресса обработки файлов (оптимизированная)
"""

import asyncio
from typing import Dict, Optional
from aiogram import Bot
from aiogram.types import Message
from loguru import logger
from datetime import datetime

from src.utils.telegram_safe import safe_edit_text, safe_send_message


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
        self.progress: Optional[float] = None  # Прогресс в процентах (0-100)


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
        # Интервал автообновления (под спиннер и легкие изменения UI)
        # Поддерживаем частоту ~1.5–3 сек, чтобы анимация казалась живой,
        # но без излишней нагрузки на Telegram API
        self.update_interval = 1.5
        self._spinner_frames = ["|", "/", "-", "\\"]  # Кадры спиннера
        self._spinner_index = 0
        # Поля для дедупликации и троттлинга обновлений сообщения
        self._last_text: str = ""
        self._last_edit_at: datetime = datetime.min
        # Минимальный интервал между редактированиями сообщения
        self._min_edit_interval_seconds: float = 1.5
        # Адаптивный интервал - увеличивается при длительной работе
        self._adaptive_interval_base = 1.5
        self._adaptive_interval_max = 3.0
        self._adaptive_step_seconds = 60  # Увеличивать интервал каждые 60 секунд
        # Блокировка для последовательного редактирования сообщения
        self._edit_lock = asyncio.Lock()
    
    def _get_adaptive_interval(self) -> float:
        """Получить адаптивный интервал обновления"""
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        
        # Увеличиваем интервал каждые 60 секунд
        steps = int(elapsed_seconds // self._adaptive_step_seconds)
        adaptive_interval = self._adaptive_interval_base + (steps * 0.5)
        
        # Ограничиваем максимальным значением
        return min(adaptive_interval, self._adaptive_interval_max)
        
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
        
        await self.update_display(force=True)
    
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
        
        # Сохраняем процент прогресса, если передан
        if progress_percent is not None:
            try:
                p = float(progress_percent)
            except (TypeError, ValueError):
                p = None
            if p is not None:
                if p < 0:
                    p = 0.0
                elif p > 100:
                    p = 100.0
                self.stages[stage_id].progress = p

        await self.update_display()
    
    async def complete_all(self):
        """Завершить все этапы"""
        if self.update_task:
            task = self.update_task
            self.update_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Ошибка при отмене автообновления: {e}")
            
        if self.current_stage:
            await self.complete_stage(self.current_stage)
        
        await self.update_display(final=True)
    
    async def update_display(self, final: bool = False, force: bool = False):
        """Обновить отображение прогресса"""
        try:
            # Проверяем, что сообщение существует
            if self.message is None:
                logger.warning("Попытка обновить прогресс без сообщения")
                return
                
            # Исключаем гонки между параллельными вызовами
            async with self._edit_lock:
                # Планируем следующий кадр спиннера, но применяем его только при реальном редактировании
                planned_index = None
                if not final and any(s.is_active for s in self.stages.values()):
                    planned_index = (self._spinner_index + 1) % len(self._spinner_frames)

                text = self._format_progress_text(final, spinner_index=planned_index)

                # Дедупликация текста: пропускаем, если текст не изменился
                if text == self._last_text:
                    return

                # Троттлинг: не обновлять чаще, чем раз в _min_edit_interval (кроме финального сообщения)
                now = datetime.now()
                if not final and not force and (now - self._last_edit_at).total_seconds() < self._min_edit_interval_seconds:
                    return

                await safe_edit_text(self.message, text, parse_mode="Markdown")
                self._last_text = text
                self._last_edit_at = now
                # Фиксируем смену кадра спиннера только если действительно отредактировали сообщение
                if planned_index is not None:
                    self._spinner_index = planned_index
        except Exception as e:
            # Тихо игнорируем частый случай: сообщение не изменилось
            if "message is not modified" in str(e).lower():
                logger.debug("Пропущено обновление: текст не изменился")
                return
            logger.error(f"Ошибка обновления прогресса: {e}")
    
    def _format_progress_text(self, final: bool = False, spinner_index: Optional[int] = None) -> str:
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
                # Добавляем длительность выполнения, если доступна
                duration_text = ""
                if stage.started_at and stage.completed_at:
                    total_sec = int((stage.completed_at - stage.started_at).total_seconds())
                    if total_sec < 60:
                        duration_text = f" · {total_sec}с"
                    else:
                        minutes = total_sec // 60
                        seconds = total_sec % 60
                        if minutes < 60:
                            duration_text = f" · {minutes}м" + (f" {seconds}с" if seconds else "")
                        else:
                            hours = minutes // 60
                            rem_min = minutes % 60
                            duration_text = f" · {hours}ч" + (f" {rem_min}м" if rem_min else "")

                text += f"✅ {stage.emoji} {stage.name}{duration_text}\n"
            elif stage.is_active:
                idx = self._spinner_index if spinner_index is None else spinner_index
                spinner = self._spinner_frames[idx]
                # Заголовок активного этапа (без процентов)
                text += f"🔄 {stage.emoji} {stage.name} {spinner}\n"
                # Краткое описание этапа (без прогресс-бара)
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
                # Используем адаптивный интервал
                adaptive_interval = self._get_adaptive_interval()
                await asyncio.sleep(adaptive_interval)
                if self.current_stage:  # Проверяем еще раз после сна
                    # Сдвиг спиннера и редактирование производятся внутри update_display
                    # Форсируем редактирование, чтобы анимация крутилась даже при частых апдейтах прогресса
                    await self.update_display(force=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка в авто-обновлении прогресса: {e}")
    
    async def error(self, stage_id: str, error_message: str):
        """Отметить ошибку на этапе"""
        if self.update_task:
            task = self.update_task
            self.update_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Ошибка при отмене автообновления: {e}")
        
        stage = self.stages.get(stage_id)
        stage_name = stage.name if stage else stage_id
        
        # Экранируем специальные символы Markdown для безопасного отображения
        safe_error_message = self._escape_markdown(error_message)
        
        text = (
            f"❌ **Ошибка при обработке**\n\n"
            f"Этап: {stage_name}\n"
            f"Ошибка: {safe_error_message}\n\n"
            f"Попробуйте загрузить файл еще раз."
        )
        
        try:
            if self.message is None:
                logger.warning("Попытка отобразить ошибку без сообщения")
                return
            await safe_edit_text(self.message, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка отображения ошибки: {e}")
    
    def _escape_markdown(self, text: str) -> str:
        """Экранировать специальные символы Markdown"""
        # Экранируем символы, которые могут вызвать проблемы с парсингом
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text


class ProgressFactory:
    """Фабрика для создания трекеров прогресса"""
    
    @staticmethod
    async def create_file_processing_tracker(bot: Bot, chat_id: int, 
                                           enable_diarization: bool = True) -> ProgressTracker:
        """Создать трекер для обработки файлов"""
        # Создаем начальное сообщение
        initial_message = await safe_send_message(
            bot, chat_id, 
            "🔄 **Начинаю обработку файла...**\n\n⏳ Инициализация...",
            parse_mode="Markdown"
        )
        
        # Если сообщение не удалось создать, логируем ошибку, но продолжаем
        if initial_message is None:
            logger.error("Не удалось создать начальное сообщение для трекера прогресса")
        
        tracker = ProgressTracker(bot, chat_id, initial_message)
        tracker.setup_default_stages()
        
        return tracker
