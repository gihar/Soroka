"""
Система отслеживания прогресса обработки файлов (оптимизированная)
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional

from aiogram import Bot
from aiogram.types import Message
from loguru import logger

from src.reliability.telegram_rate_limiter import telegram_rate_limiter
from src.services import error_presentation
from src.utils.telegram_safe import safe_edit_text, safe_send_message


class ProgressStage:
    """Упрощенный этап обработки"""

    def __init__(self, name: str, description: str):
        self.name = name
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
        # Трекер уже погашен: повторное завершение — no-op. Хвост обработки и
        # finally воркера закрывают трекер оба, и без этого флага второй вызов
        # шлёт лишнюю правку сообщения; после error() он же не даёт хвосту
        # закрасить сообщение об ошибке ложным «Протокол готов».
        self._finished = False
        # Максимальное время жизни трекера (защита от "зависших" трекеров)
        self._max_lifetime_seconds = 1800  # 30 минут
        # Рубеж этапа: этап, не двигающийся дольше этого, глушит автообновление.
        # Гард на 1800с — слишком поздний: незакрытый трекер успевал сделать
        # ~350 лишних правок сообщения после доставки протокола. Порог выбран по
        # проду: самый длинный реальный этап («Анализ») шёл 374с, здесь запас ×1.6;
        # транскрипция укладывалась в 31с даже на файле 72.8 МБ.
        #
        # Это ВТОРОЙ рубеж, не основной: трекер гасит хвост обработки
        # (completion._finish_tracker). Отличить снаружи «этап встал» от «этап
        # честно долго идёт» нечем — живости этапы не сообщают
        # (update_stage_progress не вызывает никто). Поэтому у порога есть
        # осознанный минус: транскрипция, которая когда-нибудь пойдёт дольше
        # 10 минут, перестанет анимировать сообщение. Цена мягкая — протокол
        # всё равно дойдёт, а финальное состояние выставит хвост.
        self._max_stage_seconds = 600  # 10 минут
    
    def _get_adaptive_interval(self) -> float:
        """Получить адаптивный интервал обновления"""
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        
        # Увеличиваем интервал каждые 60 секунд
        steps = int(elapsed_seconds // self._adaptive_step_seconds)
        adaptive_interval = self._adaptive_interval_base + (steps * 0.5)
        
        # Ограничиваем максимальным значением
        return min(adaptive_interval, self._adaptive_interval_max)
        
    def add_stage(self, stage_id: str, name: str, description: str):
        """Добавить этап обработки"""
        self.stages[stage_id] = ProgressStage(name, description)

    def setup_default_stages(self):
        """Настройка упрощенных этапов обработки"""
        self.stages = {}

        # Объединили технические этапы в более понятные для пользователя
        self.add_stage(
            "preparation", "Подготовка",
            "Подготавливаю файл к обработке..."
        )
        self.add_stage(
            "transcription", "Транскрипция",
            "Преобразую аудио в текст..."
        )
        self.add_stage(
            "analysis", "Анализ",
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
        """Завершить все этапы (идемпотентно)"""
        if self._finished:
            return
        self._finished = True

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
                    text = self._format_progress_text(final)

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

                    await safe_edit_text(self.message, text, parse_mode="HTML")
                    self._last_text = text
                    self._last_edit_at = now
                    
                    # Постепенно снижаем интервал после flood control
                    if self._post_flood_interval > self._adaptive_interval_base:
                        self._post_flood_interval = max(self._adaptive_interval_base, self._post_flood_interval - 0.5)
            finally:
                async with ProgressTracker._updates_lock:
                    ProgressTracker._active_updates -= 1
                    
        except Exception as e:
            # Тихо игнорируем частый случай: сообщение не изменилось
            if "message is not modified" in str(e).lower():
                logger.debug(f"⏭️ Сообщение не изменилось (msg_id={message_id})")
                return
            logger.error(f"❌ Ошибка обновления прогресса (msg_id={message_id}): {e}")
    
    @staticmethod
    def _stage_duration_text(stage: ProgressStage) -> str:
        """Длительность завершённого этапа как тихий хвост « · 12с» (без эмодзи)."""
        if not (stage.started_at and stage.completed_at):
            return ""
        total_sec = int((stage.completed_at - stage.started_at).total_seconds())
        if total_sec < 60:
            return f" · {total_sec}с"
        minutes, seconds = divmod(total_sec, 60)
        if minutes < 60:
            return f" · {minutes}м" + (f" {seconds}с" if seconds else "")
        hours, rem_min = divmod(minutes, 60)
        return f" · {hours}ч" + (f" {rem_min}м" if rem_min else "")

    def _format_progress_text(self, final: bool = False) -> str:
        """Спокойный экран прогресса: один статусный глиф на строку.

        ✅ — завершённый этап, ⏳ — текущий, «·» — будущий. Пер-этапных эмодзи и
        ASCII-спиннера нет. Финальный кадр не кричит вторым штампом «готово»:
        сводку «Протокол готов» несёт отдельное сообщение доставки (ADR-0003),
        здесь остаётся лишь тихий тайминг — иначе два ✅-штампа подряд.
        """
        lines = ["<b>Обработка файла</b>", ""]

        for stage in self.stages.values():
            if stage.is_completed:
                lines.append(f"✅ {stage.name}{self._stage_duration_text(stage)}")
            elif stage.is_active and not final:
                lines.append(f"⏳ {stage.name}")
                lines.append(f"   <i>{stage.description}</i>")
            else:
                lines.append(f"· {stage.name}")

        total_elapsed = (datetime.now() - self.start_time).total_seconds()
        if final:
            lines.append("")
            lines.append(f"Время обработки: {total_elapsed:.0f}с")
        elif total_elapsed > 10:
            lines.append("")
            lines.append(f"Прошло: {total_elapsed:.0f}с")

        return "\n".join(lines)
    
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

                # Рубеж этапа — ближе, чем время жизни: если этап стоит на месте,
                # обработка либо кончилась (трекер забыли закрыть), либо встала.
                # В обоих случаях править сообщение дальше незачем.
                stage = self.stages.get(self.current_stage)
                if stage and stage.started_at:
                    stage_elapsed = (datetime.now() - stage.started_at).total_seconds()
                    if stage_elapsed > self._max_stage_seconds:
                        logger.warning(
                            f"⚠️ Этап не двигается дольше {self._max_stage_seconds}с "
                            f"({self._max_stage_seconds // 60}мин) — останавливаю "
                            f"автообновление. Этап: {stage.name}"
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
    
    async def error(self, stage_id: str, error_message: str, raw_error: str = ""):
        """Отметить ошибку на этапе.

        ``raw_error`` — исходный текст исключения; по нему подбирается шаг для
        пользователя. Наружу он не уходит, только в лог: см.
        ``error_presentation.processing_failure_message``.
        """
        # НЕМЕДЛЕННО устанавливаем флаг ошибки и останавливаем автообновление
        self._has_error = True
        # Трекер погашен сообщением об ошибке: последующий complete_all() из
        # finally хвоста не должен закрасить его ложным «Протокол готов».
        self._finished = True

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

        # Сырой текст исключения — только в лог, не пользователю (анти-референс
        # PRODUCT.md «сырой машинный вывод»). Пользователь видит простую фразу,
        # но шаг в ней подобран по причине сбоя: при перегрузке сервера совет
        # «отправьте ещё раз» замыкал круг (прод 30.07, 27 отказов подряд).
        logger.error(f"Обработка прервалась на этапе {stage_id}: {error_message}")

        text = error_presentation.processing_failure_message(
            stage_name, raw_error or error_message
        )

        try:
            if self.message is None:
                logger.warning("Попытка отобразить ошибку без сообщения")
                return
            await safe_edit_text(self.message, text, parse_mode="HTML")
            self._last_text = text
            self._last_edit_at = datetime.now()
        except Exception as e:
            logger.error(f"Ошибка отображения ошибки: {e}")


class ProgressFactory:
    """Фабрика для создания трекеров прогресса"""
    
    @staticmethod
    async def create_file_processing_tracker(bot: Bot, chat_id: int, 
                                           enable_diarization: bool = True) -> ProgressTracker:
        """Создать трекер для обработки файлов"""
        # Создаем начальное сообщение
        initial_message = await safe_send_message(
            bot, chat_id,
            "<b>Обработка файла</b>\n\n⏳ Инициализация...",
            parse_mode="HTML"
        )
        
        # Если сообщение не удалось создать, логируем ошибку, но продолжаем
        if initial_message is None:
            logger.error("Не удалось создать начальное сообщение для трекера прогресса")
        
        tracker = ProgressTracker(bot, chat_id, initial_message)
        tracker.setup_default_stages()
        
        return tracker
