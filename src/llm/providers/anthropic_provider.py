"""Anthropic Claude provider."""
import asyncio
from typing import Dict, Any, Optional
from loguru import logger
from anthropic import Anthropic

from src.config import settings
from src.llm.base import LLMProvider
from src.llm.json_utils import safe_json_parse
from src.prompts.prompts import (
    build_analysis_prompt,
    build_analysis_system_prompt,
    build_generation_prompt,
    build_generation_system_prompt
)
from src.utils.context_extraction import build_anthropic_messages_with_caching
from src.utils.token_cache_logger import log_cached_tokens_usage


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude."""

    def __init__(self):
        self.client = None
        if settings.anthropic_api_key:
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = Anthropic(
                api_key=settings.anthropic_api_key,
                http_client=http_client
            )

    def is_available(self) -> bool:
        return self.client is not None and settings.anthropic_api_key is not None

    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str],
                                diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol using Anthropic Claude (Two-stage process)."""
        if not self.is_available():
            raise ValueError("Anthropic API не настроен")

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

        if provided_meeting_type and provided_speaker_mapping:
            logger.info(f"[Anthropic] ЭТАП 1 пропущен: тип встречи ({provided_meeting_type}) и сопоставление спикеров ({len(provided_speaker_mapping)} спикеров) уже определены")
            meeting_type = provided_meeting_type
            speaker_mapping = provided_speaker_mapping
            analysis_result = {}
        else:
            logger.info("[Anthropic] Запуск ЭТАПА 1: Анализ встречи")

            analysis_system_prompt = build_analysis_system_prompt()
            analysis_user_prompt = build_analysis_prompt(
                transcription=analysis_transcription,
                participants_list=participants_list_str,
                meeting_metadata=meeting_metadata,
                meeting_agenda=kwargs.get('meeting_agenda'),
                project_list=kwargs.get('project_list')
            )

            analysis_result = await self._call_anthropic(
                system_prompt=analysis_system_prompt,
                user_prompt=analysis_user_prompt,
                step_name="Analysis",
                use_caching=True,
                transcription_for_caching=analysis_transcription
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})

            logger.info(f"[Anthropic] ЭТАП 1 завершен. Тип: {meeting_type}")

        # Stage 2: Generation
        logger.info("[Anthropic] Запуск ЭТАПА 2: Генерация протокола")

        generation_system_prompt = build_generation_system_prompt()
        generation_user_prompt = build_generation_prompt(
            transcription=analysis_transcription,
            template_variables=template_variables,
            speaker_mapping=speaker_mapping,
            meeting_type=meeting_type,
            meeting_agenda=kwargs.get('meeting_agenda'),
            project_list=kwargs.get('project_list')
        )

        generation_result = await self._call_anthropic(
            system_prompt=generation_system_prompt,
            user_prompt=generation_user_prompt,
            step_name="Generation",
            use_caching=True,
            transcription_for_caching=analysis_transcription
        )

        protocol_data = generation_result.get('protocol_data', {})
        logger.info("[Anthropic] ЭТАП 2 завершен.")

        final_result = protocol_data.copy()
        final_result['_meeting_type'] = meeting_type
        final_result['_speaker_mapping'] = speaker_mapping
        final_result['_analysis_confidence'] = analysis_result.get('analysis_confidence', 0.0)
        final_result['_quality_score'] = generation_result.get('quality_score', 0.0)

        return final_result

    async def _call_anthropic(self, system_prompt: str, user_prompt: str, step_name: str,
                              use_caching: bool = False, transcription_for_caching: str = "") -> Dict[str, Any]:
        """Helper method for Anthropic API calls."""
        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title

        system_block = system_prompt
        messages = [{"role": "user", "content": user_prompt}]

        if use_caching and settings.enable_prompt_caching and len(transcription_for_caching) >= settings.min_transcription_length_for_cache:
            logger.debug(f"Используем Anthropic prompt caching для {step_name}")
            system_block, messages = build_anthropic_messages_with_caching(
                system_prompt, transcription_for_caching, user_prompt
            )

        async def _api_call():
            return await asyncio.to_thread(
                self.client.messages.create,
                model="claude-3-haiku-20240307",
                max_tokens=4000,
                temperature=0.1,
                system=system_block,
                messages=messages,
                extra_headers=extra_headers
            )

        try:
            response = await _api_call()
            content = response.content[0].text

            if settings.log_cache_metrics:
                log_cached_tokens_usage(
                    response=response,
                    context=f"Anthropic_{step_name}",
                    model_name="claude-3-haiku-20240307",
                    provider="anthropic"
                )

            return safe_json_parse(content, context=f"Anthropic {step_name} response")

        except Exception as e:
            logger.error(f"Ошибка при вызове Anthropic [{step_name}]: {e}")
            raise
