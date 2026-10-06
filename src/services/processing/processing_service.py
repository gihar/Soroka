"""
Оптимизированный сервис обработки с улучшенной производительностью.

This is the orchestrator that delegates to:
- ProtocolFormatter  (formatting)
- LLMGenerationService  (LLM interaction)
- ProcessingHistoryService  (persistence / file utilities)
"""

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from loguru import logger

from src.config import settings
from src.database import history_repo
from src.exceptions.processing import ProcessingError
from src.models.processing import ProcessingRequest
from src.performance.async_optimization import OptimizedHTTPClient, task_pool, thread_manager
from src.performance.cache_system import performance_cache
from src.performance.memory_management import memory_optimizer
from src.performance.metrics import PerformanceTimer, metrics_collector, performance_timer
from src.reliability.middleware import monitoring_middleware
from src.services.base_processing_service import BaseProcessingService
from src.services.mapping_session import MappingSession
from src.services.smart_template_selector import smart_selector

# Новые сервисы для улучшения качества
from src.services.transcription_preprocessor import get_preprocessor
from src.utils.request_diagnostics import log_meeting_inputs

from .completion import CompletionDeps, complete_processing, deliver_cached
from .llm_generation import LLMGenerationService
from .mapping_pause import MappingPause
from .pause_channel import PauseChannel, TelegramPauseChannel
from .processing_history import ProcessingHistoryService

# Extracted modules
from .protocol_formatter import ProtocolFormatter
from .record_preparation import PreparedRecord, RecordFate, prepare_record
from .record_preparation import file_hash as record_file_hash
from .run_outcome import RunOutcome


def _should_show_mapping_card(diarization: Any) -> bool:
    """Показывать ли карточку сопоставления (ADR-0002).

    Карточка появляется, когда диаризация нашла хотя бы одного спикера —
    независимо от того, передан ли список участников и сопоставил ли кого-то
    LLM. Именование спикеров вручную доступно даже без исходного списка.
    """
    return bool(diarization and len(diarization.speakers) >= 1)


class ProcessingService(BaseProcessingService):
    """Сервис обработки с оптимизацией производительности"""

    def __init__(
        self,
        *,
        mapping_pause: Optional[MappingPause] = None,
        channel_for: Optional[Callable[[Any], PauseChannel]] = None,
    ):
        """
        Args:
            mapping_pause: пауза на карточке сопоставления; по умолчанию —
                на общем хранилище сессий с зависимостями этого сервиса.
            channel_for: канал к пользователю по трекеру прогона; по умолчанию
                — Telegram-чат трекера.
        """
        super().__init__()

        # Мониторинг будет запущен при первом использовании
        self._monitoring_started = False

        # Composed services
        self.formatter = ProtocolFormatter()
        self.llm_gen = LLMGenerationService(
            user_service=self.user_service,
            template_service=self.template_service,
        )
        self.history = ProcessingHistoryService(user_service=self.user_service)

        self.mapping_pause = mapping_pause or MappingPause(deps=self._completion_deps())
        self._channel_for = channel_for or TelegramPauseChannel.from_tracker

    # ------------------------------------------------------------------
    # Единый хвост «Завершение обработки» (ADR-0003)
    # ------------------------------------------------------------------

    def _completion_deps(self) -> CompletionDeps:
        """Зависимости единого хвоста: генерация, форматирование, история."""
        return CompletionDeps(
            llm_gen=self.llm_gen,
            formatter=self.formatter,
            history=self.history,
        )

    def _channel(self, progress_tracker) -> Optional[PauseChannel]:
        """Канал к пользователю: чат трекера прогона. Без трекера — некуда."""
        if progress_tracker is None:
            return None
        return self._channel_for(progress_tracker)

    def _delivery_for(self, request, progress_tracker):
        """Колбэк доставки готового результата пользователю.

        Канал берётся из progress_tracker (bot/chat_id), адресат — из запроса.
        Без трекера доставлять некуда → False (в проде трекер всегда есть:
        обработку запускает воркер очереди).
        """
        channel = self._channel(progress_tracker)

        async def deliver(result) -> bool:
            if channel is None:
                logger.warning("Доставка невозможна: нет progress_tracker")
                return False
            return await channel.deliver(request, result, progress_tracker)

        return deliver

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    @performance_timer("file_processing")
    async def process_file(
        self, request: ProcessingRequest, progress_tracker=None, task_id=None
    ) -> RunOutcome:
        """Прогнать запись через конвейер и вернуть исход прогона.

        Исход — готов (протокол собран, доставлен и учтён единым хвостом) или
        приостановлен на карточке сопоставления (дальше обработку ведёт пауза).

        ``task_id`` (опционально) — id задачи очереди; пробрасывается в сессию
        паузы, чтобы закрытие паузы проставило исходной задаче финальный статус.
        """
        # Запускаем мониторинг при первом использовании
        await self._ensure_monitoring_started()

        # Создаем метрики для отслеживания
        processing_metrics = metrics_collector.start_processing_metrics(
            request.file_name, request.user_id
        )
        monitoring_start_time = time.time()

        def record_monitoring(success: bool) -> None:
            duration = (
                processing_metrics.total_duration
                if processing_metrics.total_duration
                else time.time() - monitoring_start_time
            )
            monitoring_middleware.record_protocol_request(
                user_id=request.user_id,
                duration=duration,
                success=success,
            )

        record = None

        try:
            # Подготовка записи: файл на диске, хеш, ключ и ответ кеша. Сбой
            # самой подготовки убирает за собой скачанный ею файл.
            record = await prepare_record(request, file_service=self.file_service)

            if record.cached_result:
                logger.info(
                    f"Найден кэшированный результат для {request.file_name} "
                    f"(file_hash: {record.file_hash})"
                )
                processing_metrics.end_time = processing_metrics.start_time
                metrics_collector.finish_processing_metrics(processing_metrics)
                record_monitoring(True)
                if progress_tracker:
                    await progress_tracker.complete_all()

                await record.release(RecordFate.DELIVERED_FROM_CACHE)

                # Кеш-хит доставляется и учитывается тем же хвостом: свежая запись
                # истории (её id даёт кнопки), доставка, статус задачи (ADR-0003).
                outcome = await deliver_cached(
                    record.cached_result,
                    request=request,
                    deps=self._completion_deps(),
                    delivery=self._delivery_for(request, progress_tracker),
                    task_id=task_id,
                    progress_tracker=progress_tracker,
                )
                return RunOutcome.ready(outcome.result)

            logger.info(
                f"Кеш не найден для {request.file_name} "
                f"(file_hash: {record.file_hash}), начинаем обработку"
            )

            # Прогон: транскрипция → сопоставление → пауза на карточке или
            # единый хвост «Завершение обработки» (кеш, история, доставка, статус).
            outcome = await self._run_record(
                request, record, processing_metrics, progress_tracker, task_id=task_id,
            )

            if outcome.paused:
                # Запись теперь держит пауза: файл нужен фрагментам, его судьбу
                # решит закрытие паузы.
                logger.info("Обработка приостановлена - ожидаю подтверждения от пользователя")
                return outcome

            await record.release(RecordFate.PROTOCOL_ASSEMBLED)
            metrics_collector.finish_processing_metrics(processing_metrics)
            record_monitoring(True)
            return outcome

        except Exception as e:
            logger.error(f"Ошибка в оптимизированной обработке {request.file_name}: {e}")
            metrics_collector.finish_processing_metrics(processing_metrics, e)
            record_monitoring(False)
            if record is not None:
                await record.release(RecordFate.FAILED)
            raise

    def _log_request_diagnostics(self, request: ProcessingRequest) -> None:
        """Залогировать реквизиты входящего ProcessingRequest одной строкой."""
        log_meeting_inputs(
            "обработка",
            participants_list=request.participants_list,
            meeting_topic=request.meeting_topic,
            meeting_date=request.meeting_date,
            meeting_time=request.meeting_time,
            meeting_agenda=request.meeting_agenda,
            project_list=request.project_list,
            speaker_mapping=request.speaker_mapping,
        )

    async def _run_record(
        self,
        request: ProcessingRequest,
        record: PreparedRecord,
        processing_metrics,
        progress_tracker=None,
        task_id=None,
    ) -> RunOutcome:
        """Прогон подготовленной записи до протокола или паузы на карточке."""

        # Логирование данных из ProcessingRequest для диагностики
        self._log_request_diagnostics(request)

        temp_file_path = record.path
        cache_key = record.cache_key

        # Этап 1: Загрузка данных пользователя
        with PerformanceTimer("data_loading", metrics_collector):
            user = await self.user_service.get_user_by_telegram_id(request.user_id)

            if not user:
                raise ProcessingError(
                    f"Пользователь {request.user_id} не найден",
                    request.file_name, "validation",
                )

        processing_metrics.validation_duration = 0.5

        # Этап 1: Подготовка файла — запись уже на диске (prepare_record)
        if progress_tracker:
            await progress_tracker.start_stage("preparation")

        processing_metrics.file_size_bytes = record.size_bytes
        processing_metrics.download_duration = 0.0
        processing_metrics.file_format = record.file_format

        # Этап 2: Транскрипция
        if progress_tracker:
            await progress_tracker.start_stage("transcription")

        transcription_result = await self._optimized_transcription(
            temp_file_path, request, processing_metrics, progress_tracker,
            file_hash=record.file_hash,
        )

        # Этап 2.3 + 2.5: Параллельное выполнение speaker mapping и выбора шаблона
        logger.info(
            f"Проверка условий для speaker mapping: "
            f"participants_list={request.participants_list is not None} "
            f"({len(request.participants_list) if request.participants_list else 0} чел.), "
            f"diarization={transcription_result.diarization is not None}"
        )

        mapping_result, template = await asyncio.gather(
            self._run_speaker_mapping(request, transcription_result),
            self._suggest_template_if_needed(request, transcription_result, progress_tracker),
        )

        # Фиксируем шаблон СРАЗУ, до возможной паузы на подтверждение —
        # тогда template_id попадёт в сохранённое состояние и путь
        # возобновления переиспользует тот же шаблон, а не выберет заново.
        if not template:
            raise ProcessingError(
                "Не удалось выбрать шаблон",
                request.file_name, "template_selection",
            )
        request.template_id = template.id

        # Обработка результатов speaker mapping. Карточка показывается при
        # диаризации с ≥ 1 спикером (ADR-0002) — даже с пустым авто-маппингом
        # и без списка участников (там имена вводятся вручную).
        speaker_mapping, request_meeting_type = mapping_result
        if _should_show_mapping_card(transcription_result.diarization):
            if await self._mapping_confirmation_enabled(request.user_id):
                # task_id кладём в сессию ДО показа кнопок подтверждения,
                # чтобы он был в ней к моменту, когда пользователь сможет
                # нажать «Подтвердить» (иначе — гонка с attach). Сессия
                # живыми объектами: без сериализации, дрейфовать нечему.
                session = MappingSession(
                    request=request,
                    transcription_result=transcription_result,
                    speaker_mapping=speaker_mapping,
                    meeting_type=request_meeting_type,
                    temp_file_path=temp_file_path,
                    cache_key=cache_key,
                    task_id=task_id,
                    metrics=processing_metrics,
                    template=template,
                    record=record,
                )
                if await self.mapping_pause.open(
                    session, channel=self._channel(progress_tracker)
                ):
                    return RunOutcome.paused_on_card()
            request.speaker_mapping = speaker_mapping or None
        else:
            request.speaker_mapping = None

        # Этап 3: анализ, генерация, сборка и единый хвост «Завершение
        # обработки» (страховка спикеров → кеш → история → доставка → статус).
        if progress_tracker:
            await progress_tracker.start_stage("analysis")

        outcome = await complete_processing(
            request=request,
            transcription_result=transcription_result,
            template=template,
            meeting_type=request_meeting_type,
            deps=self._completion_deps(),
            delivery=self._delivery_for(request, progress_tracker),
            cache_key=cache_key,
            task_id=task_id,
            metrics=processing_metrics,
            progress_tracker=progress_tracker,
        )
        return RunOutcome.ready(outcome.result)

    async def _mapping_confirmation_enabled(self, telegram_user_id: int) -> bool:
        """Спрашивать ли имена спикеров у этого пользователя.

        Настройка из /settings перекрывает глобальный флаг администратора: тот,
        кто жмёт «Пропустить» каждую неделю, говорит это один раз. Сбой чтения
        пользователя не должен менять поведение обработки — падаем в общий флаг.
        """
        from src.services.mapping_preference import should_confirm_mapping

        try:
            user = await self.user_service.get_user_by_telegram_id(telegram_user_id)
        except Exception as e:
            logger.warning(f"Не удалось прочитать настройку сопоставления: {e}")
            user = None
        return should_confirm_mapping(
            user, global_default=settings.enable_speaker_mapping_confirmation
        )

    # ------------------------------------------------------------------
    # Speaker mapping (extracted for parallel execution)
    # ------------------------------------------------------------------

    async def _run_speaker_mapping(
        self,
        request: ProcessingRequest,
        transcription_result: Any,
    ) -> tuple:
        """Run speaker mapping if conditions are met.

        Returns (speaker_mapping, meeting_type) or ({}, None).
        """
        if not (request.participants_list and transcription_result.diarization):
            if not request.participants_list:
                logger.info("Speaker mapping пропущен: список участников не предоставлен")
            elif not transcription_result.diarization:
                logger.warning("Speaker mapping пропущен: диаризация не выполнена")
            return ({}, None)

        try:
            from src.database import app_settings_repo, model_preset_repo
            from src.services.processing.llm_generation import resolve_active_preset
            from src.services.speaker_mapping_service import speaker_mapping_service

            # Сопоставление идёт тем же адресом провайдера, что анализ и
            # генерация: пресет переносит весь LLM-путь целиком (ADR-0007).
            active_preset = await resolve_active_preset(
                app_settings_repo, model_preset_repo
            )

            logger.info(
                f"НАЧАЛО СОПОСТАВЛЕНИЯ СПИКЕРОВ И ОПРЕДЕЛЕНИЯ ТИПА ВСТРЕЧИ: "
                f"{len(request.participants_list)} участников"
            )
            logger.info("Список участников для сопоставления:")
            for i, p in enumerate(request.participants_list[:5], 1):
                logger.info(f"  {i}. {p.get('name')} ({p.get('role', 'без роли')})")
            if len(request.participants_list) > 5:
                logger.info(
                    f"  ... и еще {len(request.participants_list) - 5} участников"
                )

            speaker_mapping, meeting_type = (
                await speaker_mapping_service.map_speakers_to_participants(
                    diarization_data=transcription_result.diarization,
                    participants=request.participants_list,
                    transcription_text=transcription_result.transcription,
                    llm_provider=request.llm_provider,
                    preset=active_preset,
                )
            )

            logger.info(
                f"СОПОСТАВЛЕНИЕ ЗАВЕРШЕНО: {len(speaker_mapping)} спикеров "
                f"сопоставлено, тип встречи: {meeting_type}"
            )
            if speaker_mapping:
                logger.info("Результаты сопоставления:")
                for speaker_id, name in speaker_mapping.items():
                    logger.info(f"  {speaker_id} -> {name}")
            else:
                logger.warning(
                    "Speaker mapping вернул пустой результат - "
                    "протокол будет генерироваться без сопоставления спикеров"
                )

            return (speaker_mapping, meeting_type)

        except Exception as e:
            logger.opt(exception=True).error(f"ОШИБКА ПРИ СОПОСТАВЛЕНИИ СПИКЕРОВ: {e}")
            return ({}, None)

    # ------------------------------------------------------------------
    # Template suggestion
    # ------------------------------------------------------------------

    async def _suggest_template_if_needed(
        self,
        request: ProcessingRequest,
        transcription_result: Any,
        progress_tracker=None,
    ) -> Optional[Any]:
        """
        Предложить умный выбор шаблона если template_id не задан

        Returns:
            Template или None если уже выбран
        """
        if request.template_id:
            return await self.template_service.get_template_by_id(request.template_id)

        templates = await self.template_service.get_user_templates(request.user_id)

        if not templates:
            all_templates = await self.template_service.get_all_templates()
            return all_templates[0] if all_templates else None

        user_stats = await history_repo.get_user_stats(request.user_id)
        template_history = []
        if user_stats and user_stats.get('favorite_templates'):
            template_history = [
                t['id'] for t in user_stats['favorite_templates']
                if isinstance(t, dict) and 'id' in t
            ]

        suggestions = await smart_selector.suggest_templates(
            transcription=transcription_result.transcription,
            templates=templates,
            top_k=3,
            user_history=template_history,
            meeting_topic=request.meeting_topic,
        )

        if suggestions:
            best_template, confidence = suggestions[0]
            logger.info(
                f"Рекомендован шаблон '{best_template.name}' "
                f"(уверенность: {confidence:.2%})"
            )
            return best_template

        return templates[0]

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    async def _optimized_transcription(
        self, file_path: str, request: ProcessingRequest,
        processing_metrics, progress_tracker=None, file_hash: Optional[str] = None,
    ) -> Any:
        """Оптимизированная транскрипция с кэшированием и предобработкой.

        ``file_hash`` — хеш записи, уже посчитанный подготовкой записи; без него
        хеш считается здесь.
        """
        if file_hash is None:
            file_hash = await record_file_hash(file_path)
        cache_key = f"transcription:{file_hash}:{request.language}"

        cached_transcription = await performance_cache.get(cache_key)
        if cached_transcription:
            logger.info("Использован кэшированный результат транскрипции")
            processing_metrics.transcription_duration = 0.1
            return cached_transcription

        with PerformanceTimer("transcription", metrics_collector):
            start_time = time.time()

            logger.info(f"Запускаем транскрипцию файла: {file_path}")
            transcription_result = await self._run_transcription_async(
                file_path, request.language
            )
            logger.info(
                f"Транскрипция завершена. Результат получен: "
                f"{hasattr(transcription_result, 'transcription')}"
            )

            processing_metrics.transcription_duration = time.time() - start_time

            if hasattr(transcription_result, 'transcription'):
                processing_metrics.transcription_length = len(
                    transcription_result.transcription
                )

            if (
                hasattr(transcription_result, 'diarization')
                and transcription_result.diarization
            ):
                processing_metrics.speakers_count = len(
                    transcription_result.diarization.speakers
                )
                processing_metrics.diarization_duration = 5.0

        # Этап предобработки текста транскрипции
        if (
            settings.enable_text_preprocessing
            and hasattr(transcription_result, 'transcription')
        ):
            logger.info("Применение предобработки текста")
            preprocessor = get_preprocessor(request.language)

            # Предобрабатываем сырую транскрипцию. Форматированный текст —
            # производное диаризации (выводится из сегментов), отдельно его не
            # чистим: он и раньше не доходил до LLM (двухэтапная генерация брала
            # формат из самой диаризации).
            preprocessed = preprocessor.preprocess(
                text=transcription_result.transcription,
            )

            transcription_result.transcription = preprocessed['cleaned_text']

            logger.info(
                f"Предобработка завершена: сокращение на "
                f"{preprocessed['statistics']['reduction_percent']}%"
            )

        await performance_cache.set(
            cache_key, transcription_result, cache_type="transcription"
        )

        return transcription_result

    async def _run_transcription_async(self, file_path: str, language: str):
        """Асинхронная транскрипция"""
        return await self.transcription_service.transcribe_with_diarization(
            file_path, language
        )

    # ------------------------------------------------------------------
    # Performance / monitoring
    # ------------------------------------------------------------------

    async def get_performance_stats(self) -> Dict[str, Any]:
        """Получить статистику производительности"""
        cache_stats = performance_cache.get_stats()
        metrics_stats = metrics_collector.get_current_stats()
        task_pool_stats = task_pool.get_stats()

        return {
            "cache": cache_stats,
            "metrics": metrics_stats,
            "task_pool": task_pool_stats,
            "optimizations": {
                "transcription_cache_enabled": True,
                "llm_cache_enabled": True,
                "parallel_processing": True,
                "async_file_operations": True,
                "connection_pooling": True,
            },
        }

    async def optimize_cache(self):
        """Оптимизация кэша"""
        await performance_cache.cleanup_expired()

        stats = performance_cache.get_stats()
        logger.info(
            f"Статистика кэша: hit_rate={stats['hit_rate_percent']}%, "
            f"memory={stats['memory_usage_mb']}MB, "
            f"entries={stats['memory_entries']+stats['disk_entries']}"
        )

    async def _ensure_monitoring_started(self):
        """Безопасный запуск мониторинга"""
        if not self._monitoring_started:
            try:
                if not metrics_collector.is_monitoring:
                    metrics_collector.start_monitoring()

                if not memory_optimizer.is_optimizing:
                    memory_optimizer.start_optimization()

                self._monitoring_started = True
                logger.info("Мониторинг производительности запущен")

            except Exception as e:
                logger.warning(f"Не удалось запустить мониторинг: {e}")

    def get_reliability_stats(self) -> Dict[str, Any]:
        """Получить статистику надежности"""
        try:
            stats = {
                "performance_cache": {
                    "stats": (
                        performance_cache.get_stats()
                        if hasattr(performance_cache, 'get_stats')
                        else {}
                    ),
                },
                "metrics": {
                    "collected": True if hasattr(metrics_collector, 'get_stats') else False,
                },
                "thread_manager": {
                    "active": True if thread_manager else False,
                },
                "optimizations": {
                    "async_enabled": True,
                    "cache_enabled": True,
                    "thread_pool_enabled": True,
                },
            }

            return stats
        except Exception as e:
            logger.error(f"Ошибка при получении статистики надежности: {e}")
            return {"error": str(e), "status": "error"}


# Фабрика для создания оптимизированного сервиса
class ServiceFactory:
    """Фабрика для создания оптимизированных сервисов"""

    @staticmethod
    def create_processing_service() -> ProcessingService:
        """Создать оптимизированный сервис обработки"""
        return ProcessingService()

    @staticmethod
    async def create_with_prewarming() -> ProcessingService:
        """Создать сервис с предварительным прогревом"""
        service = ProcessingService()
        await service._prewarm_systems()
        return service

    async def _prewarm_systems(self):
        """Предварительный прогрев систем"""
        logger.info("Прогрев оптимизированных систем...")

        async with OptimizedHTTPClient():
            pass

        await thread_manager.run_in_thread(lambda: True)

        logger.info("Системы прогреты и готовы к работе")
