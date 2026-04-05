"""
Оптимизированный сервис обработки с улучшенной производительностью.

This is the orchestrator that delegates to:
- ProtocolFormatter  (formatting)
- LLMGenerationService  (LLM interaction)
- ProcessingHistoryService  (persistence / file utilities)
"""

import asyncio
import json
import time
import os
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
from loguru import logger

from src.services.base_processing_service import BaseProcessingService
from src.models.processing import ProcessingRequest, ProcessingResult
from src.exceptions.processing import ProcessingError
from src.performance.cache_system import performance_cache, cache_transcription
from src.performance.metrics import metrics_collector, PerformanceTimer, performance_timer, ProcessingMetrics
from src.performance.async_optimization import (
    task_pool, thread_manager, optimized_file_processing,
    OptimizedHTTPClient
)
from src.performance.memory_management import memory_optimizer
from src.reliability.middleware import monitoring_middleware
from database import db
from src.utils.telegram_safe import safe_send_message

# Новые сервисы для улучшения качества
from src.services.transcription_preprocessor import get_preprocessor
from src.services.diarization_analyzer import diarization_analyzer
from src.services.protocol_validator import protocol_validator

from src.services.smart_template_selector import smart_selector
from llm_providers import llm_manager
from config import settings

# Extracted modules
from .protocol_formatter import ProtocolFormatter
from .llm_generation import LLMGenerationService
from .processing_history import ProcessingHistoryService


class ProcessingService(BaseProcessingService):
    """Сервис обработки с оптимизацией производительности"""

    def __init__(self):
        super().__init__()

        # Мониторинг будет запущен при первом использовании
        self._monitoring_started = False

        # Composed services
        self.formatter = ProtocolFormatter()
        self.llm_gen = LLMGenerationService(
            llm_service=self.llm_service,
            user_service=self.user_service,
            template_service=self.template_service,
        )
        self.history = ProcessingHistoryService(user_service=self.user_service)

    # ------------------------------------------------------------------
    # Backward-compatible private method aliases
    # ------------------------------------------------------------------

    def _format_speaker_mapping_message(
        self, speaker_mapping: Dict[str, str], total_participants: int
    ) -> str:
        return self.formatter.format_speaker_mapping_message(speaker_mapping, total_participants)

    def _format_protocol(self, template, llm_result, transcription_result) -> str:
        return self.formatter.format_protocol(template, llm_result, transcription_result)

    def _convert_complex_to_markdown(self, value):
        return self.formatter.convert_complex_to_markdown(value)

    def _format_dict_to_text(self, data):
        return self.formatter.format_dict_to_text(data)

    def _format_list_to_text(self, data):
        return self.formatter.format_list_to_text(data)

    def _fix_json_in_text(self, text):
        return self.formatter.fix_json_in_text(text)

    async def _save_processing_history(self, request, result):
        return await self.history.save_processing_history(request, result)

    async def _calculate_file_hash(self, file_path):
        return await self.history.calculate_file_hash(file_path)

    async def _cleanup_temp_file(self, file_path):
        return await self.history.cleanup_temp_file(file_path)

    def _generate_result_cache_key(self, request, file_hash):
        return self.history.generate_result_cache_key(request, file_hash)

    async def _optimized_llm_generation(self, transcription_result, template,
                                        request, processing_metrics, meeting_type=None):
        return await self.llm_gen.optimized_llm_generation(
            transcription_result, template, request, processing_metrics, meeting_type
        )

    def _get_template_variables_from_template(self, template):
        return self.llm_gen.get_template_variables_from_template(template)

    async def _get_model_display_name(self, provider, openai_model_key=None):
        return await self.llm_gen.get_model_display_name(provider, openai_model_key)

    async def _generate_llm_response(self, *args, **kwargs):
        return await self.llm_gen.generate_llm_response(*args, **kwargs)

    def _post_process_llm_result(self, llm_result):
        return self.llm_gen.post_process_llm_result(llm_result)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    @performance_timer("file_processing")
    async def process_file(self, request: ProcessingRequest, progress_tracker=None) -> ProcessingResult:
        """Оптимизированная обработка файла"""
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

        temp_file_path = None
        cache_check_only = False

        try:
            # Шаг 1: Получаем путь к файлу
            if request.is_external_file:
                temp_file_path = request.file_path
                if not os.path.exists(temp_file_path):
                    raise ProcessingError(
                        f"Файл не найден: {temp_file_path}",
                        request.file_name,
                        "file_preparation",
                    )
            else:
                temp_file_path = await self._download_telegram_file(request)
                cache_check_only = True

            # Шаг 2: Вычисляем хеш файла
            file_hash = await self._calculate_file_hash(temp_file_path)
            logger.debug(f"Вычислен хеш файла: {file_hash}")

            # Шаг 3: Генерируем ключ кеша с хешем
            cache_key = self._generate_result_cache_key(request, file_hash)

            # Шаг 4: Проверяем кэш полного результата
            cached_result = await performance_cache.get(cache_key)

            if cached_result:
                logger.info(
                    f"Найден кэшированный результат для {request.file_name} "
                    f"(file_hash: {file_hash})"
                )
                processing_metrics.end_time = processing_metrics.start_time
                metrics_collector.finish_processing_metrics(processing_metrics)
                record_monitoring(True)
                await self._save_processing_history(request, cached_result)
                if progress_tracker:
                    await progress_tracker.complete_all()

                if cache_check_only and temp_file_path and os.path.exists(temp_file_path):
                    await self._cleanup_temp_file(temp_file_path)

                return cached_result

            logger.info(
                f"Кеш не найден для {request.file_name} (file_hash: {file_hash}), "
                "начинаем обработку"
            )
            cache_check_only = False

            # Шаг 5: Оптимизированная обработка
            result = await self._process_file_optimized(
                request, processing_metrics, progress_tracker, temp_file_path
            )

            if result is None:
                logger.info("Обработка приостановлена - ожидаю подтверждения от пользователя")
                return None

            # Шаг 6: Кэшируем результат
            await performance_cache.set(
                cache_key, result,
                cache_type="processing_result",
            )
            logger.info(
                f"Результат закеширован для {request.file_name} (file_hash: {file_hash})"
            )

            metrics_collector.finish_processing_metrics(processing_metrics)
            record_monitoring(True)
            await self._save_processing_history(request, result)
            return result

        except Exception as e:
            logger.error(f"Ошибка в оптимизированной обработке {request.file_name}: {e}")
            metrics_collector.finish_processing_metrics(processing_metrics, e)
            record_monitoring(False)
            if cache_check_only and temp_file_path and os.path.exists(temp_file_path):
                await self._cleanup_temp_file(temp_file_path)
            raise

    async def _process_file_optimized(
        self,
        request: ProcessingRequest,
        processing_metrics,
        progress_tracker=None,
        temp_file_path: str = None,
    ) -> ProcessingResult:
        """Внутренняя оптимизированная обработка

        Args:
            request: Запрос на обработку
            processing_metrics: Метрики производительности
            progress_tracker: Трекер прогресса
            temp_file_path: Путь к уже скачанному файлу (если None, файл будет скачан)
        """

        # Логирование данных из ProcessingRequest для диагностики
        logger.info("Данные из ProcessingRequest при начале обработки:")
        if request.participants_list:
            logger.info(f"  participants_list: {len(request.participants_list)} чел.")
            for i, p in enumerate(request.participants_list[:3], 1):
                logger.info(f"    {i}. {p.get('name')} ({p.get('role', 'без роли')})")
            if len(request.participants_list) > 3:
                logger.info(f"    ... и еще {len(request.participants_list) - 3} участников")
        else:
            logger.warning("  participants_list: None (НЕ ПЕРЕДАН В REQUEST!)")
        logger.info(f"  meeting_topic: {request.meeting_topic}")
        logger.info(f"  meeting_date: {request.meeting_date}")
        logger.info(f"  meeting_time: {request.meeting_time}")
        logger.info(f"  speaker_mapping: {request.speaker_mapping}")

        async with optimized_file_processing() as resources:
            http_client = resources["http_client"]

            # Этап 1: Загрузка данных пользователя
            with PerformanceTimer("data_loading", metrics_collector):
                user = await self.user_service.get_user_by_telegram_id(request.user_id)

                if not user:
                    raise ProcessingError(
                        f"Пользователь {request.user_id} не найден",
                        request.file_name, "validation",
                    )

            processing_metrics.validation_duration = 0.5

            # Этап 1: Подготовка файла
            if progress_tracker:
                await progress_tracker.start_stage("preparation")

            with PerformanceTimer("file_download", metrics_collector):
                if temp_file_path is None:
                    if request.is_external_file:
                        temp_file_path = request.file_path

                        if os.path.exists(temp_file_path):
                            file_size = os.path.getsize(temp_file_path)
                            processing_metrics.file_size_bytes = file_size
                            processing_metrics.download_duration = 0.1
                        else:
                            raise ProcessingError(
                                f"Файл не найден: {temp_file_path}",
                                request.file_name, "file_preparation",
                            )
                    else:
                        file_url = await self.file_service.get_telegram_file_url(request.file_id)
                        temp_file_path = f"temp/{request.file_name}"

                        download_result = await http_client.download_file(
                            file_url, temp_file_path
                        )

                        if not download_result["success"]:
                            error_msg = download_result.get('error', 'Неизвестная ошибка скачивания')
                            raise ProcessingError(
                                f"Ошибка скачивания: {error_msg}",
                                request.file_name, "download",
                            )

                        processing_metrics.download_duration = download_result["duration"]
                        processing_metrics.file_size_bytes = download_result["bytes_downloaded"]
                else:
                    if os.path.exists(temp_file_path):
                        file_size = os.path.getsize(temp_file_path)
                        processing_metrics.file_size_bytes = file_size
                        processing_metrics.download_duration = 0.0
                        logger.debug(
                            f"Используем уже скачанный файл: {temp_file_path} ({file_size} байт)"
                        )
                    else:
                        raise ProcessingError(
                            f"Файл не найден: {temp_file_path}",
                            request.file_name, "file_preparation",
                        )

                processing_metrics.file_format = os.path.splitext(request.file_name)[1]

            # Этап 2: Транскрипция
            if progress_tracker:
                await progress_tracker.start_stage("transcription")

            transcription_result = await self._optimized_transcription(
                temp_file_path, request, processing_metrics, progress_tracker
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

            # Обработка результатов speaker mapping
            speaker_mapping, request_meeting_type = mapping_result
            if speaker_mapping:
                if settings.enable_speaker_mapping_confirmation:
                    pause_result = await self._handle_speaker_mapping_confirmation(
                        request, transcription_result, speaker_mapping,
                        request_meeting_type, temp_file_path, processing_metrics,
                        progress_tracker,
                    )
                    if pause_result is None:
                        return None
                request.speaker_mapping = speaker_mapping
            else:
                request.speaker_mapping = None

            if not template:
                raise ProcessingError(
                    "Не удалось выбрать шаблон",
                    request.file_name, "template_selection",
                )

            request.template_id = template.id

            # Этап 3: Анализ и генерация
            if progress_tracker:
                await progress_tracker.start_stage("analysis")

            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics,
                meeting_type=request_meeting_type,
            )

            # Форматирование
            if progress_tracker:
                pass

            with PerformanceTimer("formatting", metrics_collector):
                processing_metrics.formatting_duration = 0.1

                protocol_text = self._format_protocol(
                    template, llm_result, transcription_result
                )

                if request.speaker_mapping:
                    from src.utils.text_processing import replace_speakers_in_text
                    protocol_text = replace_speakers_in_text(
                        protocol_text, request.speaker_mapping
                    )
                    logger.info("Применена замена спикеров на имена участников")

            # Очистка временного файла в фоне (только для внешних файлов)
            if request.is_external_file:
                asyncio.create_task(self._cleanup_temp_file(temp_file_path))

            # Определяем название модели для результата
            openai_model_key = None
            if request.llm_provider == 'openai':
                openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            llm_model_display_name = await self._get_model_display_name(
                request.llm_provider, openai_model_key
            )

            return ProcessingResult(
                transcription_result=transcription_result,
                protocol_text=protocol_text,
                template_used=(
                    template.model_dump()
                    if hasattr(template, 'model_dump')
                    else template.__dict__
                ),
                llm_provider_used=request.llm_provider,
                llm_model_used=llm_model_display_name,
                processing_duration=processing_metrics.total_duration,
            )

    async def _handle_speaker_mapping_confirmation(
        self, request, transcription_result, speaker_mapping,
        meeting_type, temp_file_path, processing_metrics, progress_tracker,
    ):
        """Handle speaker mapping confirmation UI.

        Returns a sentinel (None) when the processing should be paused,
        or a truthy value when processing should continue without pause.
        """
        logger.info(
            "UI подтверждения сопоставления включен - "
            "сохраняю состояние и показываю интерфейс"
        )

        from src.services.mapping_state_cache import mapping_state_cache

        await mapping_state_cache.save_state(request.user_id, {
            'speaker_mapping': speaker_mapping,
            'meeting_type': meeting_type,
            'diarization_data': transcription_result.diarization,
            'participants_list': request.participants_list,
            'request_data': (
                request.model_dump()
                if hasattr(request, 'model_dump')
                else request.dict()
            ),
            'transcription_result': {
                'transcription': transcription_result.transcription,
                'formatted_transcript': transcription_result.formatted_transcript,
                'speakers_text': transcription_result.speakers_text,
                'speakers_summary': transcription_result.speakers_summary,
            },
            'temp_file_path': temp_file_path,
            'processing_metrics': {
                'start_time': (
                    processing_metrics.start_time.isoformat()
                    if hasattr(processing_metrics, 'start_time')
                    else datetime.now().isoformat()
                ),
                'total_duration': (
                    processing_metrics.total_duration
                    if hasattr(processing_metrics, 'total_duration') else 0
                ),
                'download_duration': (
                    processing_metrics.download_duration
                    if hasattr(processing_metrics, 'download_duration') else 0
                ),
                'validation_duration': (
                    processing_metrics.validation_duration
                    if hasattr(processing_metrics, 'validation_duration') else 0
                ),
                'conversion_duration': (
                    processing_metrics.conversion_duration
                    if hasattr(processing_metrics, 'conversion_duration') else 0
                ),
                'transcription_duration': (
                    processing_metrics.transcription_duration
                    if hasattr(processing_metrics, 'transcription_duration') else 0
                ),
                'diarization_duration': (
                    processing_metrics.diarization_duration
                    if hasattr(processing_metrics, 'diarization_duration') else 0
                ),
            },
        })

        if progress_tracker:
            from src.ux.speaker_mapping_ui import show_mapping_confirmation

            # Останавливаем автообновления progress_tracker
            if progress_tracker.update_task:
                task = progress_tracker.update_task
                progress_tracker.update_task = None
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.debug(
                    "Автообновления progress_tracker остановлены "
                    "перед показом UI подтверждения"
                )

            # Обновляем сообщение progress_tracker
            try:
                from src.utils.telegram_safe import safe_edit_text
                await safe_edit_text(
                    progress_tracker.message,
                    "**Транскрипция завершена**\n\n"
                    "Проверьте сопоставление спикеров с участниками в сообщении ниже.",
                    parse_mode="Markdown",
                )
                logger.debug("Сообщение progress_tracker обновлено на информационное")
            except Exception as e:
                logger.warning(
                    f"Не удалось обновить сообщение progress_tracker: {e}"
                )

            # Получаем список несопоставленных спикеров
            all_speakers = transcription_result.diarization.get('speakers', [])
            if not all_speakers:
                segments = transcription_result.diarization.get('segments', [])
                all_speakers = sorted(
                    set(s.get('speaker') for s in segments if s.get('speaker'))
                )
            mapped_speakers = set(speaker_mapping.keys())
            unmapped_speakers = [s for s in all_speakers if s not in mapped_speakers]

            speakers_text = transcription_result.speakers_text

            confirmation_message = await show_mapping_confirmation(
                bot=progress_tracker.bot,
                chat_id=progress_tracker.chat_id,
                user_id=request.user_id,
                speaker_mapping=speaker_mapping,
                diarization_data=transcription_result.diarization,
                participants=request.participants_list,
                unmapped_speakers=unmapped_speakers if unmapped_speakers else None,
                speakers_text=speakers_text,
            )

            if confirmation_message is None:
                # UI не был отправлен - продолжаем обработку без паузы
                logger.warning(
                    f"Не удалось отправить UI подтверждения сопоставления "
                    f"для пользователя {request.user_id}. "
                    "Продолжаю обработку без паузы на подтверждение."
                )

                try:
                    from src.utils.telegram_safe import safe_send_message as _safe_send
                    await _safe_send(
                        bot=progress_tracker.bot,
                        chat_id=progress_tracker.chat_id,
                        text=(
                            "Не удалось отправить интерфейс подтверждения сопоставления.\n\n"
                            "Продолжаю генерацию протокола с автоматическим "
                            "сопоставлением спикеров."
                        ),
                        parse_mode=None,
                    )
                except Exception as notify_error:
                    logger.error(
                        f"Не удалось отправить уведомление об ошибке UI: {notify_error}"
                    )

                await mapping_state_cache.clear_state(request.user_id)
                request.speaker_mapping = speaker_mapping
                return True  # continue processing
            else:
                logger.info(
                    "Обработка приостановлена - ожидаю подтверждения от пользователя"
                )
                return None  # pause processing

        logger.warning(
            "UI подтверждения включен, но progress_tracker отсутствует "
            "- продолжаю без паузы"
        )
        return True

    async def continue_processing_after_mapping_confirmation(
        self,
        user_id: int,
        confirmed_mapping: Dict[str, str],
        bot: Any,
        chat_id: int,
    ) -> ProcessingResult:
        """
        Продолжить обработку после подтверждения сопоставления спикеров

        Args:
            user_id: ID пользователя
            confirmed_mapping: Подтвержденное сопоставление спикеров
            bot: Экземпляр бота для отправки сообщений
            chat_id: ID чата

        Returns:
            ProcessingResult с готовым протоколом
        """
        from src.services.mapping_state_cache import mapping_state_cache
        from src.models.processing import ProcessingRequest, TranscriptionResult
        from src.ux.progress_tracker import ProgressFactory

        try:
            logger.info(
                f"Продолжение обработки для пользователя {user_id} "
                "после подтверждения сопоставления"
            )

            state_data = await mapping_state_cache.load_state(user_id)

            if not state_data:
                raise ProcessingError(
                    "Состояние обработки не найдено или истекло",
                    "unknown",
                    "state_expired",
                )

            request_data = state_data.get('request_data', {})
            transcription_data = state_data.get('transcription_result', {})
            diarization_data = state_data.get('diarization_data', {})
            temp_file_path = state_data.get('temp_file_path')
            meeting_type = state_data.get('meeting_type', 'general')

            logger.info(f"Восстановлено из кеша: тип встречи = {meeting_type}")

            request = ProcessingRequest(**request_data)
            request.speaker_mapping = confirmed_mapping

            transcription_result = TranscriptionResult(
                transcription=transcription_data.get('transcription', ''),
                diarization=diarization_data,
                speakers_text=transcription_data.get('speakers_text', {}),
                formatted_transcript=transcription_data.get('formatted_transcript', ''),
                speakers_summary=transcription_data.get('speakers_summary', ''),
            )

            progress_tracker = await ProgressFactory.create_file_processing_tracker(
                bot=bot,
                chat_id=chat_id,
            )

            saved_metrics = state_data.get('processing_metrics', {})
            processing_metrics = ProcessingMetrics(
                file_name=request.file_name,
                user_id=user_id,
                start_time=(
                    datetime.fromisoformat(saved_metrics['start_time'])
                    if saved_metrics.get('start_time')
                    else datetime.now()
                ),
            )
            if 'download_duration' in saved_metrics:
                processing_metrics.download_duration = saved_metrics['download_duration']
            if 'validation_duration' in saved_metrics:
                processing_metrics.validation_duration = saved_metrics['validation_duration']
            if 'conversion_duration' in saved_metrics:
                processing_metrics.conversion_duration = saved_metrics['conversion_duration']
            if 'transcription_duration' in saved_metrics:
                processing_metrics.transcription_duration = saved_metrics['transcription_duration']
            if 'diarization_duration' in saved_metrics:
                processing_metrics.diarization_duration = saved_metrics['diarization_duration']

            if not request.template_id:
                template = await self._suggest_template_if_needed(
                    request, transcription_result, progress_tracker
                )
                if not template:
                    raise ProcessingError(
                        "Не удалось выбрать шаблон",
                        request.file_name,
                        "template_selection",
                    )
                request.template_id = template.id
            else:
                template = await self.template_service.get_template_by_id(request.template_id)
                if not template:
                    raise ProcessingError(
                        f"Шаблон с ID {request.template_id} не найден",
                        request.file_name,
                        "template_not_found",
                    )

            # Этап 3: Анализ и генерация
            if progress_tracker:
                await progress_tracker.start_stage("analysis")

            logger.info(f"Начинаем генерацию протокола для пользователя {user_id}")

            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics,
                meeting_type=meeting_type,
            )

            logger.info(f"LLM генерация завершена. Тип результата: {type(llm_result)}")
            if llm_result is None:
                raise ProcessingError(
                    "LLM вернул пустой результат",
                    request.file_name,
                    "llm_empty_result",
                )

            # Форматирование
            with PerformanceTimer("formatting", metrics_collector):
                processing_metrics.formatting_duration = 0.1

                logger.info("Форматирование протокола...")
                try:
                    protocol_text = self._format_protocol(
                        template, llm_result, transcription_result
                    )
                    logger.info(
                        f"Протокол отформатирован. Длина: {len(protocol_text)} символов"
                    )
                except Exception as format_error:
                    logger.error(f"Ошибка форматирования протокола: {format_error}")
                    logger.error(f"Тип llm_result: {type(llm_result)}")
                    logger.error(
                        f"Содержимое llm_result (первые 500 символов): "
                        f"{str(llm_result)[:500]}"
                    )
                    raise ProcessingError(
                        f"Ошибка форматирования протокола: {str(format_error)}",
                        request.file_name,
                        "protocol_formatting_error",
                    )

                if confirmed_mapping:
                    from src.utils.text_processing import replace_speakers_in_text
                    protocol_text = replace_speakers_in_text(protocol_text, confirmed_mapping)
                    logger.info(
                        "Применена замена спикеров на имена участников "
                        "(подтвержденное сопоставление)"
                    )

            # Очистка временного файла
            if request.is_external_file and temp_file_path:
                asyncio.create_task(self._cleanup_temp_file(temp_file_path))

            # Определяем название модели
            user = await self.user_service.get_user_by_telegram_id(user_id)
            openai_model_key = None
            if request.llm_provider == 'openai' and user:
                openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            llm_model_display_name = await self._get_model_display_name(
                request.llm_provider, openai_model_key
            )

            result = ProcessingResult(
                transcription_result=transcription_result,
                protocol_text=protocol_text,
                template_used=(
                    template.model_dump()
                    if hasattr(template, 'model_dump')
                    else template.__dict__
                ),
                llm_provider_used=request.llm_provider,
                llm_model_used=llm_model_display_name,
                processing_duration=processing_metrics.total_duration,
            )

            # Отправляем результат пользователю
            from src.services.task_queue_manager import TaskQueueManager
            from src.models.task_queue import QueuedTask, TaskPriority

            task_queue_manager = TaskQueueManager()

            fake_task = QueuedTask(
                task_id=uuid4(),
                request=request,
                user_id=user_id,
                chat_id=chat_id,
                priority=TaskPriority.NORMAL,
                created_at=datetime.now(),
            )

            await task_queue_manager._send_result_to_user(
                bot=bot,
                task=fake_task,
                result=result,
                progress_tracker=progress_tracker,
            )

            await self._save_processing_history(request, result)

            logger.info(f"Обработка успешно завершена для пользователя {user_id}")

            return result

        except ProcessingError as e:
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(
                f"Критичная ошибка обработки для пользователя {user_id}: "
                f"{error_msg_safe}",
                exc_info=True,
            )

            await mapping_state_cache.clear_state(user_id)

            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=(
                    f"Произошла критичная ошибка:\n\n{str(e)}\n\n"
                    f"Пожалуйста, начните обработку заново."
                ),
            )

            raise

        except json.JSONDecodeError as e:
            error_msg = f"Ошибка парсинга JSON: {str(e)}"

            logger.error(f"Некритичная ошибка парсинга JSON для пользователя {user_id}")
            logger.error(f"Детали ошибки: {error_msg}")

            try:
                state_data = await mapping_state_cache.load_state(user_id)
                if state_data:
                    request_data = state_data.get('request_data', {})
                    logger.error("Контекст обработки:")
                    logger.error(
                        f"  - LLM провайдер: {request_data.get('llm_provider', 'unknown')}"
                    )
                    logger.error(
                        f"  - Шаблон ID: {request_data.get('template_id', 'unknown')}"
                    )
                    logger.error(
                        f"  - Файл: {request_data.get('file_name', 'unknown')}"
                    )
                    logger.error(
                        f"  - Участники: "
                        f"{len(request_data.get('participants_list', []))} чел."
                    )
            except Exception as log_error:
                logger.warning(
                    f"Не удалось получить контекст из состояния: {log_error}"
                )

            logger.error("Полный traceback:", exc_info=True)

            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=(
                    f"Произошла временная ошибка при обработке:\n\n{error_msg}\n\n"
                    f"Это может быть связано с проблемами API. "
                    f"Ваше состояние сохранено - вы можете повторить попытку "
                    f"через кнопку подтверждения."
                ),
            )

            raise ProcessingError(
                f"Ошибка парсинга ответа: {str(e)}",
                "unknown",
                "json_parse_error",
            )

        except (TimeoutError, asyncio.TimeoutError) as e:
            error_msg = "Превышено время ожидания ответа от сервиса"
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(
                f"Timeout для пользователя {user_id}: {error_msg_safe}",
                exc_info=True,
            )

            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=(
                    f"{error_msg}\n\n"
                    f"Ваше состояние сохранено - попробуйте повторить через минуту."
                ),
            )

            raise ProcessingError(
                error_msg,
                "unknown",
                "timeout_error",
            )

        except Exception as e:
            import traceback

            error_type = type(e).__name__
            error_msg = str(e).lower() if e else "unknown error"

            logger.error(
                "Неожиданное исключение в "
                "continue_processing_after_mapping_confirmation"
            )
            logger.error(f"Тип ошибки: {error_type}")
            logger.error(f"Сообщение ошибки: {str(e)}")
            logger.error("Полный traceback:")
            for line in traceback.format_exception(type(e), e, e.__traceback__):
                logger.error(line.rstrip())

            is_api_error = any(
                pattern in error_msg for pattern in [
                    'rate limit', 'quota', 'service unavailable',
                    'connection', 'timeout', 'network',
                ]
            )

            if is_api_error:
                error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
                logger.error(
                    f"API ошибка для пользователя {user_id} "
                    f"({error_type}): {error_msg_safe}"
                )

                await safe_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=(
                        f"Временная проблема с API:\n\n{str(e)}\n\n"
                        f"Ваше состояние сохранено - попробуйте повторить "
                        f"через несколько минут."
                    ),
                )

                raise ProcessingError(
                    f"API ошибка: {str(e)}",
                    "unknown",
                    "api_error",
                )
            else:
                error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
                logger.error(
                    f"Неожиданная ошибка для пользователя {user_id} "
                    f"({error_type}): {error_msg_safe}",
                    exc_info=True,
                )

                await mapping_state_cache.clear_state(user_id)

                await safe_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=(
                        f"Произошла непредвиденная ошибка:\n\n"
                        f"{error_type}: {str(e)}\n\n"
                        f"Пожалуйста, начните обработку заново."
                    ),
                )

                raise ProcessingError(
                    f"Неожиданная ошибка: {str(e)}",
                    "unknown",
                    "unexpected_error",
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
            from src.services.speaker_mapping_service import speaker_mapping_service

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
            logger.error(
                f"ОШИБКА ПРИ СОПОСТАВЛЕНИИ СПИКЕРОВ: {e}", exc_info=True
            )
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

        from src.services.meeting_classifier import meeting_classifier
        meeting_type, type_scores = meeting_classifier.classify(
            transcription_result.transcription,
            diarization_analysis=None,
        )
        logger.info(
            f"Тип встречи для рекомендации шаблона: {meeting_type} "
            f"(оценки: {', '.join(f'{k}={v:.2f}' for k, v in list(type_scores.items())[:3])})"
        )

        user_stats = await db.get_user_stats(request.user_id)
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
            meeting_type=meeting_type,
            type_scores=type_scores,
            meeting_topic=request.meeting_topic,
        )

        if suggestions:
            best_template, confidence = suggestions[0]
            logger.info(
                f"Рекомендован шаблон '{best_template.name}' "
                f"(уверенность: {confidence:.2%}, тип встречи: {meeting_type})"
            )
            return best_template

        return templates[0]

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    @cache_transcription()
    async def _optimized_transcription(
        self, file_path: str, request: ProcessingRequest,
        processing_metrics, progress_tracker=None,
    ) -> Any:
        """Оптимизированная транскрипция с кэшированием и предобработкой"""

        file_hash = await self._calculate_file_hash(file_path)
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
                diarization_data = transcription_result.diarization
                if isinstance(diarization_data, dict):
                    processing_metrics.speakers_count = diarization_data.get(
                        'total_speakers', 0
                    )
                    processing_metrics.diarization_duration = 5.0

        # Этап предобработки текста транскрипции
        if (
            settings.enable_text_preprocessing
            and hasattr(transcription_result, 'transcription')
        ):
            logger.info("Применение предобработки текста")
            preprocessor = get_preprocessor(request.language)

            preprocessed = preprocessor.preprocess(
                text=transcription_result.transcription,
                formatted_transcript=getattr(
                    transcription_result, 'formatted_transcript', None
                ),
            )

            transcription_result.transcription = preprocessed['cleaned_text']
            if preprocessed['cleaned_formatted']:
                transcription_result.formatted_transcript = preprocessed['cleaned_formatted']

            logger.info(
                f"Предобработка завершена: сокращение на "
                f"{preprocessed['statistics']['reduction_percent']}%"
            )

        # Этап расширенного анализа диаризации
        if (
            settings.enable_diarization_analysis
            and hasattr(transcription_result, 'diarization')
        ):
            if transcription_result.diarization:
                logger.info("Применение расширенного анализа диаризации")

                analysis_result = diarization_analyzer.enrich_diarization_data(
                    transcription_result.diarization,
                    transcription_result.transcription,
                )

                transcription_result.diarization_analysis = analysis_result

                logger.info(
                    f"Анализ диаризации завершен: "
                    f"{analysis_result.total_speakers} спикеров, "
                    f"тип встречи: {analysis_result.meeting_type}"
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
    # File download
    # ------------------------------------------------------------------

    async def _download_telegram_file(self, request: ProcessingRequest) -> str:
        """Скачать Telegram файл и вернуть путь"""
        file_url = await self.file_service.get_telegram_file_url(request.file_id)
        temp_file_path = f"temp/{request.file_name}"

        async with OptimizedHTTPClient() as http_client:
            result = await http_client.download_file(file_url, temp_file_path)

            if not result["success"]:
                error_msg = result.get('error', 'Неизвестная ошибка скачивания')
                raise ProcessingError(
                    f"Ошибка скачивания: {error_msg}",
                    request.file_name,
                    "download",
                )

        logger.info(
            f"Файл скачан: {temp_file_path} ({result['bytes_downloaded']} байт)"
        )
        return temp_file_path

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

        async with OptimizedHTTPClient() as client:
            pass

        await thread_manager.run_in_thread(lambda: True)

        logger.info("Системы прогреты и готовы к работе")
