"""Генерация протокола: глубокий модуль.

Двухэтапная генерация со строгими схемами (анализ → генерация), кеш
OpenAI-совместимых клиентов по пресетам модели и стек надёжности
(rate-limit → circuit-breaker → retry) — безусловно вокруг каждого вызова.
402 (кончились кредиты) классифицируется в LLMInsufficientCreditsError,
не ретраится и пролетает насквозь.
"""
import asyncio
from typing import Any, Dict, Optional

import httpx
import openai
from loguru import logger

from src.config import settings
from src.exceptions.processing import LLMInsufficientCreditsError
from src.llm.json_utils import safe_json_parse
from src.models.llm_schemas import MEETING_ANALYSIS_SCHEMA, PROTOCOL_DATA_SCHEMA
from src.prompts.prompts import (
    build_analysis_prompt,
    build_analysis_system_prompt,
    build_generation_prompt,
    build_generation_system_prompt,
)
from src.reliability import (
    DEFAULT_CIRCUIT_BREAKER_CONFIG,
    LLM_RETRY_CONFIG,
    OPENAI_API_LIMIT,
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryManager,
    global_rate_limiter,
)
from src.services.brief_compiler import brief_field_rules, brief_to_schema
from src.services.protocol_briefs import get_brief_for
from src.utils.token_cache_logger import log_cached_tokens_usage


def _is_insufficient_credits_error(exc: Exception) -> bool:
    """Detect an OpenAI/OpenRouter ``402 Payment Required`` (out of credits) error."""
    if getattr(exc, "status_code", None) == 402:
        return True
    text = str(exc).lower()
    return "error code: 402" in text or "more credits" in text


def _select_generation_contract(
    template_name: Optional[str], template_variables: Dict[str, str]
) -> tuple[Dict[str, Any], str]:
    """Единая точка выбора контракта ЭТАПА 2 (схема + системный промпт).

    Системный шаблон (есть бриф по имени) → строгая бриф-схема с фиксированными
    ключами + инструкции секций брифа. Кастомный шаблон (брифа нет) → legacy-путь:
    PROTOCOL_DATA_SCHEMA (Dict[str, str]) + правила, выведенные из переменных
    шаблона. Ничего в legacy-ветке не меняется.
    """
    brief = get_brief_for(template_name) if template_name else None
    if brief is not None:
        return (
            brief_to_schema(brief),
            build_generation_system_prompt(field_rules=brief_field_rules(brief)),
        )
    return (
        PROTOCOL_DATA_SCHEMA,
        build_generation_system_prompt(template_variables=template_variables),
    )


class ProtocolGenerator:
    """Глубокий модуль генерации протокола (интерфейс — тестовая поверхность)."""

    def __init__(self, retry_manager: Optional[RetryManager] = None,
                 circuit_breaker: Optional[CircuitBreaker] = None,
                 rate_limiter=None):
        self.default_client = None
        self._client_cache = {}
        self._http_clients = []  # track for cleanup
        if settings.openai_api_key:
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self._http_clients.append(http_client)
            self.default_client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=http_client,
            )

        self._retry = retry_manager or RetryManager(LLM_RETRY_CONFIG)
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            "openai_llm",
            CircuitBreakerConfig(
                failure_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.failure_threshold,
                recovery_timeout=DEFAULT_CIRCUIT_BREAKER_CONFIG.recovery_timeout,
                success_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.success_threshold,
                timeout=settings.llm_timeout_seconds,
            ),
        )
        self._rate_limiter = rate_limiter or global_rate_limiter.get_or_create(
            "openai_api", OPENAI_API_LIMIT
        )

    # ------------------------------------------------------------------ клиенты

    def _get_client(self, preset: dict = None):
        """Get or create an OpenAI client for the given preset."""
        if not preset:
            return self.default_client

        base_url = preset.get('base_url') or settings.openai_base_url
        api_key = preset.get('api_key') or settings.openai_api_key

        cache_key = (base_url, hash(api_key) if api_key else None)

        if cache_key not in self._client_cache:
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self._http_clients.append(http_client)
            self._client_cache[cache_key] = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
            )
            logger.info(f"Создан клиент для {base_url}")

        return self._client_cache[cache_key]

    def close(self):
        """Close all cached HTTP clients."""
        for client in self._http_clients:
            try:
                client.close()
            except Exception:
                pass
        self._http_clients.clear()
        self._client_cache.clear()

    def invalidate_cache_for(self, base_url: str, api_key_hash: Optional[int]) -> None:
        """Remove the cached client for the given (base_url, api_key_hash) tuple."""
        client = self._client_cache.pop((base_url, api_key_hash), None)
        if client is not None:
            logger.info(f"Invalidated OpenAI client cache for {base_url}")

    def invalidate_cache_for_base_url(self, base_url: str) -> None:
        """Remove all cached clients for the given base_url, regardless of api_key."""
        keys_to_remove = [k for k in self._client_cache if k[0] == base_url]
        for k in keys_to_remove:
            self._client_cache.pop(k)
        if keys_to_remove:
            logger.info(f"Invalidated {len(keys_to_remove)} OpenAI client(s) for {base_url}")

    def is_available(self) -> bool:
        """Клиент сконфигурирован и модуль готов принимать вызовы."""
        return self.default_client is not None

    # ------------------------------------------------------------- надёжность

    async def _protected(self, fn, *args, **kwargs):
        """rate-limit → circuit-breaker → retry вокруг любого вызова модели."""
        await self._rate_limiter.acquire()

        async def attempt():
            return await self._retry.execute_with_retry(fn, *args, **kwargs)

        return await self._circuit_breaker.call(attempt)

    def get_reliability_stats(self) -> Dict[str, Any]:
        return {
            "circuit_breaker": self._circuit_breaker.get_stats(),
            "rate_limiter": self._rate_limiter.get_stats(),
        }

    async def reset(self):
        """Сбросить компоненты надёжности (админская операция)."""
        await self._circuit_breaker.reset()
        logger.info("Сброшены компоненты надежности LLM")

    # -------------------------------------------------------------- интерфейс

    async def generate(self, *, preset: Optional[Dict[str, Any]],
                       transcription: str, template_variables: Dict[str, str],
                       **context) -> Dict[str, Any]:
        """Сгенерировать протокол по транскрипции (двухэтапно, с надёжностью).

        ``transcription`` — уже готовый текст: вызывающий передаёт
        ``best_transcript`` (формат из диаризации либо сырой), генератору знать о
        диаризации не нужно.
        """
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")
        return await self._protected(
            self._generate_two_stage,
            preset=preset,
            transcription=transcription,
            template_variables=template_variables,
            **context,
        )

    async def structured_call(self, *, system_prompt: str, user_prompt: str,
                              schema: Dict[str, Any], model: str = None,
                              preset: Optional[Dict[str, Any]] = None,
                              step_name: str = "StructuredCall") -> Dict[str, Any]:
        """Один вызов модели со строгой схемой ответа (с надёжностью)."""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")
        client = self._get_client(preset)
        return await self._protected(
            self._call_openai,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            step_name=step_name,
            model=model,
            client=client,
        )

    # ----------------------------------------------------------- реализация

    async def _generate_two_stage(self, *, preset: Optional[Dict[str, Any]],
                                  transcription: str, template_variables: Dict[str, str],
                                  **kwargs) -> Dict[str, Any]:
        """Two-stage generation: analysis (тип встречи + спикеры) → protocol."""
        participants = kwargs.get('participants')
        meeting_metadata = {
            'meeting_topic': kwargs.get('meeting_topic', ''),
            'meeting_date': kwargs.get('meeting_date', ''),
            'meeting_time': kwargs.get('meeting_time', '')
        }

        # transcription — уже готовый текст (best_transcript вызывающего): анализ и
        # генерация идут по нему, отдельного выбора «формат или сырой» здесь нет.
        analysis_transcription = transcription

        participants_list_str = "Не предоставлен"
        if participants:
            try:
                from src.services.participants_service import participants_service
                participants_list_str = participants_service.format_participants_for_llm(participants)
            except ImportError:
                participants_list_str = "\\n".join([f"- {p.get('name', 'Unknown')}" for p in participants])

        provided_meeting_type = kwargs.get('meeting_type')
        provided_speaker_mapping = kwargs.get('speaker_mapping')

        if preset and preset.get('model'):
            selected_model = preset['model']
            logger.info(
                f"Используется модель: {selected_model} "
                f"(ключ: {preset.get('key')})"
            )
        else:
            selected_model = settings.openai_model

        if provided_meeting_type and provided_speaker_mapping:
            logger.info(
                f"ЭТАП 1 пропущен: тип встречи ({provided_meeting_type}) и сопоставление "
                f"спикеров ({len(provided_speaker_mapping)} спикеров) уже определены"
            )
            meeting_type = provided_meeting_type
            speaker_mapping = provided_speaker_mapping
            analysis_result = {}
        else:
            logger.info("Запуск ЭТАПА 1: Анализ встречи и сопоставление спикеров")

            analysis_result = await self._call_openai(
                system_prompt=build_analysis_system_prompt(),
                user_prompt=build_analysis_prompt(
                    transcription=analysis_transcription,
                    participants_list=participants_list_str,
                    meeting_metadata=meeting_metadata,
                    meeting_agenda=kwargs.get('meeting_agenda'),
                    project_list=kwargs.get('project_list')
                ),
                schema=MEETING_ANALYSIS_SCHEMA,
                step_name="Analysis",
                model=settings.analysis_stage_model
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})

            logger.info(f"ЭТАП 1 завершен. Тип: {meeting_type}, Спикеров сопоставлено: {len(speaker_mapping)}")

        logger.info("Запуск ЭТАПА 2: Генерация протокола")

        client = self._get_client(preset)

        # Единая точка: бриф-контракт для системного шаблона, legacy — для кастомного.
        generation_schema, generation_system_prompt = _select_generation_contract(
            kwargs.get('template_name'), template_variables
        )

        generation_result = await self._call_openai(
            system_prompt=generation_system_prompt,
            user_prompt=build_generation_prompt(
                transcription=analysis_transcription,
                template_variables=template_variables,
                speaker_mapping=speaker_mapping,
                meeting_type=meeting_type,
                meeting_agenda=kwargs.get('meeting_agenda'),
                project_list=kwargs.get('project_list')
            ),
            schema=generation_schema,
            step_name="Generation",
            model=selected_model,
            client=client
        )

        protocol_data = generation_result.get('protocol_data', {})
        logger.info(f"ЭТАП 2 завершен. Извлечено полей: {len(protocol_data)}")

        final_result = protocol_data.copy()
        final_result['_meeting_type'] = meeting_type
        final_result['_speaker_mapping'] = speaker_mapping
        final_result['_analysis_confidence'] = (
            0.0 if provided_meeting_type else analysis_result.get('analysis_confidence', 0.0)
        )
        final_result['_quality_score'] = generation_result.get('quality_score', 0.0)

        return final_result

    async def _call_openai(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any],
                           step_name: str, model: str = None, client=None) -> Dict[str, Any]:
        """Helper method for OpenAI API calls."""
        selected_model = model or settings.openai_model
        active_client = client or self.default_client

        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title

        logger.info(f"Отправляем запрос в OpenAI [{step_name}] с моделью {selected_model}")

        try:
            response = await asyncio.to_thread(
                active_client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_schema", "json_schema": schema},
                extra_headers=extra_headers
            )
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
            if _is_insufficient_credits_error(e):
                raise LLMInsufficientCreditsError(
                    str(e), provider="openai", model=selected_model
                ) from e
            raise


# Глобальный экземпляр (один circuit-breaker/rate-limiter на процесс)
protocol_generator = ProtocolGenerator()
