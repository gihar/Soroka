"""
LLM generation service.

Extracted from ProcessingService to isolate LLM interaction logic.
"""

import time
from typing import Any, Dict, Optional

from loguru import logger

from src.config import settings
from src.exceptions.configuration import AdminConfigurationError
from src.performance.metrics import PerformanceTimer, metrics_collector
from src.services.protocol_validator import protocol_validator
from src.utils.template_sort import template_name_of


async def resolve_active_preset(app_settings_repo, preset_repo) -> Dict[str, Any]:
    """Return the currently active model preset.

    Raises `AdminConfigurationError` when no key is set or the referenced preset
    is missing/disabled.
    """
    active_key = await app_settings_repo.get_active_model_key()
    if not active_key:
        raise AdminConfigurationError(
            "Активная модель не настроена администратором"
        )
    preset = await preset_repo.get_by_key(active_key)
    if not preset or not preset.get("is_enabled"):
        raise AdminConfigurationError(
            f"Активная модель '{active_key}' недоступна"
        )
    return preset


class LLMGenerationService:
    """Handles LLM-based protocol generation, caching and post-processing."""

    def __init__(self, user_service, template_service):
        self._user_service = user_service
        self._template_service = template_service

    async def optimized_llm_generation(
        self,
        transcription_result: Any,
        template: Dict,
        request: Any,
        processing_metrics,
        meeting_type: str = None,
    ) -> Any:
        """Оптимизированная генерация LLM с кэшированием, двухэтапным подходом и валидацией"""
        # Резолвим активную модель (глобальная админ-настройка) до построения cache key
        from src.database import app_settings_repo, model_preset_repo

        preset_repo = model_preset_repo
        active_preset = await resolve_active_preset(app_settings_repo, preset_repo)
        llm_model_name = active_preset["name"]  # noqa: F841

        # Выполняем генерацию LLM
        with PerformanceTimer("llm_generation", metrics_collector):
            start_time = time.time()

            # Подготавливаем данные для LLM
            template_variables = self.get_template_variables_from_template(template)

            # Консолидированная двухэтапная генерация — единственный путь;
            # надёжность (rate-limit → circuit-breaker → retry) внутри модуля
            from src.llm import protocol_generator

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

            # Единый фолбэк: форматированная транскрипция из диаризации либо сырая
            transcription_text = transcription_result.best_transcript
            if transcription_result.diarization:
                logger.info("Используется форматированная транскрипция с метками спикеров")
            else:
                logger.info("Используется обычная транскрипция (диаризация недоступна)")

            llm_result_data = await protocol_generator.generate(
                preset=active_preset,
                transcription=transcription_text,
                template_variables=template_variables,
                template_name=template_name_of(template),
                participants_list=participants_list,
                meeting_metadata=meeting_metadata,
                speaker_mapping=request.speaker_mapping,
                meeting_type=meeting_type,
                meeting_topic=request.meeting_topic,
                meeting_date=request.meeting_date,
                meeting_time=request.meeting_time,
                participants=request.participants_list,
                meeting_agenda=request.meeting_agenda,
                project_list=request.project_list,
            )

            processing_metrics.llm_duration = time.time() - start_time

            # Валидация протокола
            if settings.enable_protocol_validation:
                logger.info("Запуск валидации протокола")

                # Итоговое сопоставление, использованное генератором (включая
                # выведенное на этапе анализа при пропуске подтверждения);
                # при его отсутствии — сопоставление из запроса.
                effective_speaker_mapping = (
                    llm_result_data.get('_speaker_mapping') or request.speaker_mapping
                )

                validation_result = protocol_validator.calculate_quality_score(
                    protocol=llm_result_data,
                    transcription=transcription_result.transcription,
                    template_variables=template_variables,
                    diarization_data=transcription_result.diarization,
                    speaker_mapping=effective_speaker_mapping,
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

    async def get_model_display_name(self, preset: Optional[Dict[str, Any]] = None) -> str:
        """Return a human-readable name for the active model preset."""
        if preset:
            return preset.get("name") or preset.get("model") or "GPT"
        return settings.openai_model or "GPT-4o"

    async def resolve_model_display_name(self) -> str:
        """Resolve the currently active model preset's display name.

        Single source of truth for the "name shown next to the result" logic
        that used to be inlined (and duplicated) in ProcessingService. Falls
        back to ``"?"`` when no active preset is configured/available.
        """
        from src.database import app_settings_repo, model_preset_repo

        try:
            active_preset = await resolve_active_preset(
                app_settings_repo,
                model_preset_repo,
            )
            return active_preset.get("name") or active_preset.get("model") or "?"
        except Exception:
            return "?"

