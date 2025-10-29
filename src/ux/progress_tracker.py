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
from src.reliability.telegram_rate_limiter import telegram_rate_limiter


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
    
    # Глобальный счётчик активных обновлений для ограничения параллельных запросов
    _active_updates = 0
    _max_parallel_updates = 3
    _updates_lock = asyncio.Lock()
    
    def __init__(self, bot: Bot, chat_id: int, message: Message):
        self.bot = bot
        self.chat_id = chat_id
        self.message = message
        self.stages: Dict[str, ProgressStage] = {}
        self.current_stage: Optional[str] = None
        self.start_time = datetime.now()
        self.update_task: Optional[asyncio.Task] = None
        # Интервал автообновления (увеличен для снижения нагрузки на API)
        self.update_interval = 2.5
        self._spinner_frames = ["|", "/", "-", "\\"]  # Кадры спиннера
        self._spinner_index = 0
        # Поля для дедупликации и троттлинга обновлений сообщения
        self._last_text: str = ""
        self._last_edit_at: datetime = datetime.min
        # Минимальный интервал между редактированиями сообщения (увеличен)
        self._min_edit_interval_seconds: float = 2.5
        # Адаптивный интервал - увеличивается при длительной работе
        self._adaptive_interval_base = 2.5
        self._adaptive_interval_max = 5.0
        self._adaptive_step_seconds = 60  # Увеличивать интервал каждые 60 секунд
        # Блокировка для последовательного редактирования сообщения
        self._edit_lock = asyncio.Lock()
        # Счётчики для диагностики
        self._total_updates_attempted = 0
        self._updates_skipped_flood_control = 0
        self._updates_skipped_throttle = 0
        self._updates_skipped_dedup = 0
        # Экспоненциальная задержка после flood control
        self._post_flood_interval = 2.5  # Начальное значение
        self._is_recovering_from_flood = False
        # Флаг аварийного завершения, чтобы остановить обновления
        self._has_error = False
        # Максимальное время жизни трекера (защита от "зависших" трекеров)
        self._max_lifetime_seconds = 1800  # 30 минут
    
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

        # Сбрасываем флаг ошибки при переходе на новый этап
        self._has_error = False
        
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
            self._total_updates_attempted += 1
            message_id = self.message.message_id if self.message else "unknown"
            
            # Проверяем, что сообщение существует
            if self.message is None:
                logger.warning("Попытка обновить прогресс без сообщения")
                return

            # При ошибке блокируем дальнейшие обновления, пока не потребуется финальное сообщение
            if self._has_error and not final:
                logger.debug(f"⏭️ Обновление пропущено: трекер в состоянии ошибки (msg_id={message_id})")
                return
            
            # Проверяем flood control ПЕРЕД любыми попытками обновления
            is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked(self.chat_id)
            if is_blocked:
                self._updates_skipped_flood_control += 1
                if self._updates_skipped_flood_control % 5 == 1:  # Логируем каждое 5-е пропущенное обновление
                    logger.warning(
                        f"⏸️ Обновление прогресса приостановлено из-за flood control "
                        f"(msg_id={message_id}, осталось {remaining:.0f}с, пропущено {self._updates_skipped_flood_control})"
                    )
                self._is_recovering_from_flood = True
                return
            
            # Если только что сняли блокировку - начинаем с увеличенного интервала
            if self._is_recovering_from_flood:
                logger.info(f"✅ Flood control снят, возобновляем обновления с увеличенным интервалом (msg_id={message_id})")
                self._post_flood_interval = 5.0
                self._is_recovering_from_flood = False
            
            # Проверяем глобальный лимит параллельных обновлений
            async with ProgressTracker._updates_lock:
                if ProgressTracker._active_updates >= ProgressTracker._max_parallel_updates and not final:
                    logger.debug(
                        f"⏭️ Обновление пропущено: достигнут лимит параллельных обновлений "
                        f"({ProgressTracker._active_updates}/{ProgressTracker._max_parallel_updates})"
                    )
                    return
                ProgressTracker._active_updates += 1
            
            try:
                # Исключаем гонки между параллельными вызовами
                async with self._edit_lock:
                    # Планируем следующий кадр спиннера, но применяем его только при реальном редактировании
                    planned_index = None
                    if not final and any(s.is_active for s in self.stages.values()):
                        planned_index = (self._spinner_index + 1) % len(self._spinner_frames)

                    text = self._format_progress_text(final, spinner_index=planned_index)

                    # Дедупликация текста: пропускаем, если текст не изменился
                    if text == self._last_text:
                        self._updates_skipped_dedup += 1
                        logger.debug(f"⏭️ Дедупликация: текст не изменился (msg_id={message_id})")
                        return

                    # Троттлинг: не обновлять чаще, чем раз в _min_edit_interval (кроме финального сообщения)
                    now = datetime.now()
                    if not final and not force and (now - self._last_edit_at).total_seconds() < self._min_edit_interval_seconds:
                        self._updates_skipped_throttle += 1
                        logger.debug(f"⏭️ Троттлинг: слишком частое обновление (msg_id={message_id})")
                        return

                    await safe_edit_text(self.message, text, parse_mode="Markdown")
                    self._last_text = text
                    self._last_edit_at = now
                    
                    # Постепенно снижаем интервал после flood control
                    if self._post_flood_interval > self._adaptive_interval_base:
                        self._post_flood_interval = max(self._adaptive_interval_base, self._post_flood_interval - 0.5)
                    
                    # Фиксируем смену кадра спиннера только если действительно отредактировали сообщение
                    if planned_index is not None:
                        self._spinner_index = planned_index
            finally:
                async with ProgressTracker._updates_lock:
                    ProgressTracker._active_updates -= 1
                    
        except Exception as e:
            # Тихо игнорируем частый случай: сообщение не изменилось
            if "message is not modified" in str(e).lower():
                logger.debug(f"⏭️ Сообщение не изменилось (msg_id={message_id})")
                return
            logger.error(f"❌ Ошибка обновления прогресса (msg_id={message_id}): {e}")
    
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
        """Автоматическое обновление дисплея с учётом flood control"""
        try:
            while self.current_stage and not self._has_error:
                # Проверяем таймаут времени жизни трекера
                elapsed = (datetime.now() - self.start_time).total_seconds()
                if elapsed > self._max_lifetime_seconds:
                    logger.warning(
                        f"⚠️ Трекер превысил максимальное время жизни "
                        f"({self._max_lifetime_seconds}с / {self._max_lifetime_seconds // 60}мин). "
                        f"Принудительное завершение."
                    )
                    break
                
                # Проверяем flood control перед каждым циклом
                is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked(self.chat_id)
                
                if is_blocked:
                    # Ждём полного снятия блокировки + небольшой запас
                    wait_time = remaining + 1.0
                    logger.info(
                        f"⏸️ Автообновление прогресса приостановлено на {wait_time:.0f}с из-за flood control"
                    )
                    await asyncio.sleep(wait_time)
                    # После снятия блокировки помечаем состояние восстановления
                    self._is_recovering_from_flood = True
                    continue
                
                # Используем адаптивный интервал или post-flood интервал
                if self._is_recovering_from_flood and self._post_flood_interval > self._adaptive_interval_base:
                    interval = self._post_flood_interval
                    logger.debug(f"Используем увеличенный интервал после flood control: {interval}с")
                else:
                    interval = self._get_adaptive_interval()
                
                await asyncio.sleep(interval)
                
                if self.current_stage:  # Проверяем еще раз после сна
                    # Сдвиг спиннера и редактирование производятся внутри update_display
                    # НЕ форсируем редактирование - соблюдаем троттлинг для избежания flood control
                    await self.update_display()
        except asyncio.CancelledError:
            logger.debug("Автообновление прогресса отменено")
        except Exception as e:
            logger.error(f"❌ Ошибка в авто-обновлении прогресса: {e}")
    
    async def error(self, stage_id: str, error_message: str):
        """Отметить ошибку на этапе"""
        # НЕМЕДЛЕННО устанавливаем флаг ошибки и останавливаем автообновление
        self._has_error = True
        
        # КРИТИЧЕСКИ ВАЖНО: отменяем автообновление в первую очередь
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

        # Снимаем активность с текущего этапа
        stage = self.stages.get(stage_id)
        if stage:
            stage.is_active = False

        # Устанавливаем корректный текущий этап для отображения
        if self.current_stage:
            self.current_stage = None

        # Сбрасываем последний текст, чтобы обеспечить обновление сообщения
        self._last_text = ""
        
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
            self._last_text = text
            self._last_edit_at = datetime.now()
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
