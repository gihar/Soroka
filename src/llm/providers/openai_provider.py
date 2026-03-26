"""OpenAI GPT provider."""
import asyncio
import httpx
import openai
from typing import Dict, Any, Optional
from loguru import logger

from src.config import settings
from src.llm.base import LLMProvider
from src.llm.json_utils import safe_json_parse
from src.prompts.prompts import (
    build_analysis_prompt,
    build_analysis_system_prompt,
    build_generation_prompt,
    build_generation_system_prompt
)
from src.models.llm_schemas import MEETING_ANALYSIS_SCHEMA, PROTOCOL_DATA_SCHEMA
from src.utils.token_cache_logger import log_cached_tokens_usage


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI GPT."""

    def __init__(self):
        self.client = None
        self.http_client = None
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            self.http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=self.http_client
            )

    def is_available(self) -> bool:
        return self.client is not None and settings.openai_api_key is not None

    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str],
                                diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol using OpenAI GPT (Two-stage process)."""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")

        participants = kwargs.get('participants')
        meeting_metadata = {
            'meeting_topic': kwargs.get('meeting_topic', ''),
            'meeting_date': kwargs.get('meeting_date', ''),
            'meeting_time': kwargs.get('meeting_time', '')
        }

        analysis_transcription = transcription
        if diarization_data and diarization_data.get("formatted_transcript"):
            analysis_transcription = diarization_data["formatted_transcript"]

        participants_list_str = "Не предоставлен"
        if participants:
            try:
                from src.services.participants_service import participants_service
                participants_list_str = participants_service.format_participants_for_llm(participants)
            except ImportError:
                participants_list_str = "\\n".join([f"- {p.get('name', 'Unknown')}" for p in participants])

        provided_meeting_type = kwargs.get('meeting_type')
        provided_speaker_mapping = kwargs.get('speaker_mapping')

        selected_model = settings.openai_model
        openai_model_key = kwargs.get('openai_model_key')

        if openai_model_key:
            try:
                preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                if preset:
                    selected_model = preset.model
                    logger.info(f"Используется пользовательская модель: {selected_model} (ключ: {openai_model_key})")
            except Exception as e:
                logger.warning(f"Не удалось определить модель по ключу {openai_model_key}: {e}")

        if provided_meeting_type and provided_speaker_mapping:
            logger.info(f"ЭТАП 1 пропущен: тип встречи ({provided_meeting_type}) и сопоставление спикеров ({len(provided_speaker_mapping)} спикеров) уже определены")
            meeting_type = provided_meeting_type
            speaker_mapping = provided_speaker_mapping
            analysis_result = {}
        else:
            logger.info("Запуск ЭТАПА 1: Анализ встречи и сопоставление спикеров")

            analysis_system_prompt = build_analysis_system_prompt()
            analysis_user_prompt = build_analysis_prompt(
                transcription=analysis_transcription,
                participants_list=participants_list_str,
                meeting_metadata=meeting_metadata,
                meeting_agenda=kwargs.get('meeting_agenda'),
                project_list=kwargs.get('project_list')
            )

            analysis_result = await self._call_openai(
                system_prompt=analysis_system_prompt,
                user_prompt=analysis_user_prompt,
                schema=MEETING_ANALYSIS_SCHEMA,
                step_name="Analysis",
                model=selected_model
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})

            logger.info(f"ЭТАП 1 завершен. Тип: {meeting_type}, Спикеров сопоставлено: {len(speaker_mapping)}")

        # Stage 2: Generation
        logger.info("Запуск ЭТАПА 2: Генерация протокола")

        generation_system_prompt = build_generation_system_prompt()
        generation_user_prompt = build_generation_prompt(
            transcription=analysis_transcription,
            template_variables=template_variables,
            speaker_mapping=speaker_mapping,
            meeting_type=meeting_type,
            meeting_agenda=kwargs.get('meeting_agenda'),
            project_list=kwargs.get('project_list')
        )

        generation_result = await self._call_openai(
            system_prompt=generation_system_prompt,
            user_prompt=generation_user_prompt,
            schema=PROTOCOL_DATA_SCHEMA,
            step_name="Generation",
            model=selected_model
        )

        protocol_data = generation_result.get('protocol_data', {})
        logger.info(f"ЭТАП 2 завершен. Извлечено полей: {len(protocol_data)}")

        final_result = protocol_data.copy()
        final_result['_meeting_type'] = meeting_type
        final_result['_speaker_mapping'] = speaker_mapping
        final_result['_analysis_confidence'] = 0.0 if provided_meeting_type else analysis_result.get('analysis_confidence', 0.0)
        final_result['_quality_score'] = generation_result.get('quality_score', 0.0)

        return final_result

    async def _call_openai(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any],
                           step_name: str, model: str = None) -> Dict[str, Any]:
        """Helper method for OpenAI API calls."""
        selected_model = model or settings.openai_model

        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title

        logger.info(f"Отправляем запрос в OpenAI [{step_name}] с моделью {selected_model}")

        async def _api_call():
            return await asyncio.to_thread(
                self.client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_schema", "json_schema": schema},
                extra_headers=extra_headers
            )

        try:
            response = await _api_call()
            content = response.choices[0].message.content

            if settings.log_cache_metrics:
                log_cached_tokens_usage(
                    response=response,
                    context=f"generate_protocol_{step_name}",
                    model_name=selected_model,
                    provider="openai"
                )

            return safe_json_parse(content, context=f"OpenAI {step_name} response")

        except Exception as e:
            logger.error(f"Ошибка при вызове OpenAI [{step_name}]: {e}")
            raise
