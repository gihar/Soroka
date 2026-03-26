"""
LLM generation service.

Extracted from ProcessingService to isolate LLM interaction logic.
"""

import json
import time
from typing import Any, Dict, Optional

from loguru import logger

from config import settings
from src.performance.cache_system import performance_cache, cache_llm_response
from src.performance.metrics import metrics_collector, PerformanceTimer
from src.performance.async_optimization import task_pool
from src.exceptions.processing import ProcessingError
from src.services.protocol_validator import protocol_validator

from .protocol_formatter import ProtocolFormatter


class LLMGenerationService:
    """Handles LLM-based protocol generation, caching and post-processing."""

    def __init__(self, llm_service, user_service, template_service):
        self._llm_service = llm_service
        self._user_service = user_service
        self._template_service = template_service
        self._formatter = ProtocolFormatter()

    @cache_llm_response()
    async def optimized_llm_generation(
        self,
        transcription_result: Any,
        template: Dict,
        request: Any,
        processing_metrics,
        meeting_type: str = None,
    ) -> Any:
        """Оптимизированная генерация LLM с кэшированием, двухэтапным подходом и валидацией"""
        from src.models.processing import ProcessingRequest  # noqa: F811

        # Создаем ключ кэша на основе транскрипции и шаблона
        transcription_hash = hash(str(transcription_result.transcription))
        template_hash = hash(str(template))
        participants_hash = (
            hash(json.dumps(
                sorted(request.participants_list, key=lambda x: x.get('name', '')),
                sort_keys=True,
            )) if request.participants_list else "none"
        )
        cache_key = (
            f"llm:{request.llm_provider}:{transcription_hash}:{template_hash}:{participants_hash}"
        )

        # Проверяем кэш
        cached_llm_result = await performance_cache.get(cache_key)
        if cached_llm_result:
            logger.info("Использован кэшированный результат LLM")
            processing_metrics.llm_duration = 0.1
            return cached_llm_result

        # Выполняем генерацию LLM
        with PerformanceTimer("llm_generation", metrics_collector):
            start_time = time.time()

            # Подготавливаем данные для LLM
            template_variables = self.get_template_variables_from_template(template)

            # Определяем ключ пресета модели OpenAI
            openai_model_key = None
            try:
                user = await self._user_service.get_user_by_telegram_id(request.user_id)
                if user and request.llm_provider == 'openai':
                    openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            except Exception:
                openai_model_key = None

            # Определяем название используемой модели
            llm_model_name = self.get_model_display_name(request.llm_provider, openai_model_key)  # noqa: F841

            # Извлекаем анализ диаризации если есть
            diarization_analysis = None
            if hasattr(transcription_result, 'diarization_analysis'):
                analysis_obj = transcription_result.diarization_analysis
                if analysis_obj:
                    if isinstance(analysis_obj, dict):
                        diarization_analysis = analysis_obj
                    elif hasattr(analysis_obj, 'to_dict'):
                        diarization_analysis = analysis_obj.to_dict()

            # Стандартная консолидированная генерация протокола
            if settings.enable_consolidated_two_request:
                logger.info(
                    "Использование новой консолидированной генерации протокола "
                    "(2 запроса вместо 5-6)"
                )

                from llm_providers import generate_protocol, llm_manager

                # Подготавливаем список участников
                participants_list = None
                if request.participants_list:
                    participants_list = "\n".join([
                        f"{p.get('name', '')} ({p.get('role', '')})".strip()
                        for p in request.participants_list
                        if p.get('name')
                    ])

                # Формируем метаданные встречи
                meeting_metadata = {
                    'meeting_topic': request.meeting_topic or '',
                    'meeting_date': request.meeting_date or '',
                    'meeting_time': request.meeting_time or '',
                    'participants': participants_list or '',
                }

                # Используем форматированную транскрипцию если доступна диаризация
                transcription_text = transcription_result.transcription
                if (
                    hasattr(transcription_result, 'formatted_transcript')
                    and transcription_result.formatted_transcript
                ):
                    if transcription_result.diarization:
                        transcription_text = transcription_result.formatted_transcript
                        logger.info(
                            "Используется форматированная транскрипция "
                            "с метками SPEAKER_N для диаризации"
                        )
                    else:
                        logger.info(
                            "Используется обычная транскрипция (диаризация недоступна)"
                        )
                else:
                    logger.info(
                        "Используется обычная транскрипция (formatted_transcript недоступен)"
                    )

                llm_result_data = await generate_protocol(
                    manager=llm_manager,
                    provider_name=request.llm_provider,
                    transcription=transcription_text,
                    template_variables=template_variables,
                    diarization_data=transcription_result.diarization,
                    diarization_analysis=diarization_analysis,
                    participants_list=participants_list,
                    meeting_metadata=meeting_metadata,
                    openai_model_key=openai_model_key,
                    speaker_mapping=request.speaker_mapping,
                    meeting_type=meeting_type,
                    meeting_topic=request.meeting_topic,
                    meeting_date=request.meeting_date,
                    meeting_time=request.meeting_time,
                    participants=request.participants_list,
                    meeting_agenda=request.meeting_agenda,
                    project_list=request.project_list,
                )

            else:
                # Стандартная генерация
                llm_task_id = f"llm_{request.user_id}_{int(time.time())}"

                llm_result = await task_pool.submit_task(
                    llm_task_id,
                    self.generate_llm_response,
                    transcription_result,
                    template,
                    template_variables,
                    request.llm_provider,
                    openai_model_key,
                    request.speaker_mapping,
                    request.meeting_topic,
                    request.meeting_date,
                    request.meeting_time,
                    request.participants_list,
                    request.meeting_agenda,
                    request.project_list,
                )

                if not llm_result.success:
                    error_msg = getattr(llm_result, 'error', None)
                    if error_msg is None:
                        error_msg = "Неизвестная ошибка LLM"
                    elif isinstance(error_msg, Exception):
                        error_msg = str(error_msg)
                    raise ProcessingError(
                        f"Ошибка LLM: {error_msg}",
                        request.file_name,
                        "llm",
                    )

                llm_result_data = llm_result.result

            processing_metrics.llm_duration = time.time() - start_time

            # Валидация протокола
            if settings.enable_protocol_validation:
                logger.info("Запуск валидации протокола")

                validation_result = protocol_validator.calculate_quality_score(
                    protocol=llm_result_data,
                    transcription=transcription_result.transcription,
                    template_variables=template_variables,
                    diarization_data=getattr(transcription_result, 'diarization', None),
                )

                logger.info(
                    f"Валидация завершена: общая оценка {validation_result.overall_score}, "
                    f"полнота {validation_result.completeness_score}, "
                    f"структура {validation_result.structure_score}"
                )

                processing_metrics.protocol_quality_score = validation_result.overall_score

                if validation_result.overall_score < 0.7:
                    logger.warning(
                        f"Низкое качество протокола ({validation_result.overall_score}). "
                        f"Предупреждения: {validation_result.warnings}"
                    )

                llm_result_data['_validation'] = validation_result.to_dict()

            # Логирование сводки по кешированию токенов
            if (
                settings.log_cache_metrics
                and hasattr(processing_metrics, 'total_cached_tokens')
                and hasattr(processing_metrics, 'get_cache_summary')
                and processing_metrics.total_cached_tokens > 0
            ):
                cache_summary = processing_metrics.get_cache_summary()
                logger.info("=" * 60)
                logger.info("Итоговая сводка по кешированию токенов:")
                logger.info(f"   Prompt токенов: {cache_summary['total_prompt_tokens']:,}")
                logger.info(
                    f"   Кешировано: {cache_summary['total_cached_tokens']:,} "
                    f"({cache_summary['cache_hit_rate_percent']}%)"
                )
                if cache_summary['cost_saved'] > 0:
                    logger.info(
                        f"   Экономия: ${cache_summary['cost_saved']:.4f} "
                        f"({cache_summary['savings_percent']:.1f}%)"
                    )
                    logger.info(
                        f"   Стоимость: ${cache_summary['cost_with_cache']:.4f} "
                        f"(без кеша: ${cache_summary['cost_without_cache']:.4f})"
                    )
                logger.info("=" * 60)

        # Кэшируем результат
        await performance_cache.set(cache_key, llm_result_data, cache_type="llm_response")

        return llm_result_data

    def get_template_variables_from_template(self, template) -> Dict[str, str]:
        """Извлечь переменные из конкретного шаблона"""
        try:
            if hasattr(template, 'content'):
                template_content = template.content
            elif isinstance(template, dict):
                template_content = template.get('content', '')
            else:
                template_content = str(template)

            variables_list = self._template_service.extract_template_variables(template_content)

            template_variables = {}

            core_variables = {
                'meeting_title': '',
                'meeting_date': '',
                'meeting_time': '',
                'participants': '',
            }
            template_variables.update(core_variables)

            for var in variables_list:
                template_variables[var] = ""

            logger.info(f"Подготовлены переменные шаблона: {list(template_variables.keys())}")
            return template_variables

        except Exception as e:
            logger.error(f"Ошибка при извлечении переменных из шаблона: {e}")
            return {
                'meeting_title': '',
                'meeting_date': '',
                'meeting_time': '',
                'participants': '',
                'agenda': '',
                'discussion': '',
                'key_points': '',
                'decisions': '',
                'action_items': '',
                'tasks': '',
                'next_steps': '',
                'deadlines': '',
                'issues': '',
                'questions': '',
                'risks_and_blockers': '',
                'technical_issues': '',
                'architecture_decisions': '',
                'technical_tasks': '',
                'speaker_contributions': '',
                'dialogue_analysis': '',
                'speakers_summary': '',
                'next_meeting': '',
                'additional_notes': '',
                'date': '',
                'time': '',
                'managers': '',
                'platform': '',
                'learning_objectives': '',
                'key_concepts': '',
                'examples_and_cases': '',
                'practical_exercises': '',
                'homework': '',
                'materials': '',
                'next_sprint_plans': '',
            }

    def get_model_display_name(
        self, provider: str, openai_model_key: Optional[str] = None
    ) -> str:
        """Получить читаемое название модели"""
        if provider == "openai":
            if openai_model_key:
                try:
                    preset = next(
                        (p for p in settings.openai_models if p.key == openai_model_key),
                        None,
                    )
                    if preset:
                        return preset.name
                except Exception:
                    pass
            return settings.openai_model or "GPT-4o"

        return provider.capitalize()

    async def generate_llm_response(
        self,
        transcription_result,
        template,
        template_variables,
        llm_provider,
        openai_model_key=None,
        speaker_mapping=None,
        meeting_topic=None,
        meeting_date=None,
        meeting_time=None,
        participants=None,
        meeting_agenda=None,
        project_list=None,
    ):
        """Генерация ответа LLM с постобработкой"""
        llm_result = await self._llm_service.generate_protocol_with_fallback(
            llm_provider,
            transcription_result.transcription,
            template_variables,
            transcription_result.diarization
            if hasattr(transcription_result, 'diarization')
            else None,
            openai_model_key=openai_model_key,
            speaker_mapping=speaker_mapping,
            meeting_topic=meeting_topic,
            meeting_date=meeting_date,
            meeting_time=meeting_time,
            participants=participants,
            meeting_agenda=meeting_agenda,
            project_list=project_list,
        )

        return self.post_process_llm_result(llm_result)

    def post_process_llm_result(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """Постобработка результатов LLM для исправления JSON-структур в значениях"""
        if not isinstance(llm_result, dict):
            return llm_result

        processed_result = {}
        for key, value in llm_result.items():
            processed_value = self._formatter.convert_complex_to_markdown(value)
            processed_result[key] = processed_value

        return processed_result
