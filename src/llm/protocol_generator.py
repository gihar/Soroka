"""Генерация протокола: глубокий модуль.

Двухэтапная генерация со строгими схемами (анализ → генерация), кеш
OpenAI-совместимых клиентов по пресетам модели и стек надёжности
(rate-limit → circuit-breaker → retry) — безусловно вокруг каждого вызова.
Исчерпание ресурса провайдера классифицируется здесь и наверх идёт
типизированным: 402 — LLMInsufficientCreditsError, 429/400 с квотным признаком —
LLMQuotaExhaustedError. Ни то, ни другое не ретраится и пролетает насквозь.

Каким клиентом и какой моделью идёт шаг, модуль не решает: вызов называет шаг и
пресет, а маршрут разрешает `src.llm.model_step` — единственная такая точка.

Ключ провайдера несёт пресет, а общий из окружения только подставляется, когда
своего нет: поэтому готовность модуля считается по наличию пригодных пресетов, а
отсутствие ключа опознаётся как ошибка настройки до похода в API, а не по
невнятному отказу SDK (ADR-0007).

Здесь же живёт зонд строгих схем (`probe_schema_support`): применяет ли модель
пресета затребованную схему — свойство модели, а не провайдера, и по коду
ответа неразличимое, поэтому вердикт даёт только сравнение ключей.
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx
import openai
from loguru import logger

from src.config import settings
from src.exceptions.configuration import AdminConfigurationError
from src.exceptions.processing import (
    LLMInsufficientCreditsError,
    LLMQuotaExhaustedError,
)
from src.llm.json_utils import safe_json_parse
from src.llm.model_step import ModelStep, resolve_step
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


# Коды, которыми провайдеры сообщают об исчерпании квоты подписки: 429 у Qwen
# (Throttling.AllocationQuota), 400 у OpenAI-совместимых (insufficient_quota).
_QUOTA_STATUS_CODES = (400, 429)

# Признак именно исчерпания, а не обычного троттлинга: голое 429 — это
# rate limit, он лечится повтором, и путать его с концом квоты нельзя.
_QUOTA_EXHAUSTION_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "allocationquota",
    "allocated quota",
    "quota exceeded",
    "exceeded your current quota",
    "quota_exhausted",
    "out of quota",
)


def _has_status(exc: Exception, code: int, text: str) -> bool:
    """Ответ провайдера пришёл с этим HTTP-кодом (атрибут SDK или текст ошибки)."""
    return getattr(exc, "status_code", None) == code or f"error code: {code}" in text


def _is_quota_exhausted_error(exc: Exception) -> bool:
    """Признак «квота подписки исчерпана»: код 429 или 400 с квотным признаком.

    Кредиты провайдера (402) сюда не относятся: их лечит пополнение, квоту —
    нет (CONTEXT.md), поэтому классы ошибок и алерты разные.
    """
    text = str(exc).lower()
    if not any(_has_status(exc, code, text) for code in _QUOTA_STATUS_CODES):
        return False
    return any(marker in text for marker in _QUOTA_EXHAUSTION_MARKERS)


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


# Схема зонда: два ключа, которых нет ни в промпте, ни в здравом смысле.
# Модель, применяющая строгую схему, вернёт ровно их; модель, схему выбросившая,
# ответит своими — и то и другое приходит успешным ответом, поэтому вердикт
# считается по ключам, а не по коду ответа (ADR-0007).
SCHEMA_PROBE_SCHEMA: Dict[str, Any] = {
    "name": "schema_probe",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "zqx_marker": {"type": "string"},
            "unlikely_count": {"type": "integer"},
        },
        "required": ["zqx_marker", "unlikely_count"],
        "additionalProperties": False,
    },
}

# Промпт зонда — содержательный вопрос, ни словом не упоминающий ключи схемы:
# иначе модель могла бы вернуть их из промпта, не читая схему, и вердикт
# «применяется» ничего бы не значил.
SCHEMA_PROBE_SYSTEM_PROMPT = "Ты помощник. Отвечай кратко и по существу."
SCHEMA_PROBE_USER_PROMPT = (
    "Одним предложением объясни, чем протокол встречи отличается от её транскрипции."
)


@dataclass(frozen=True)
class SchemaProbeVerdict:
    """Ответ зонда: применил ли пресет строгую схему — и что именно проверено.

    ``model`` и ``base_url`` — не украшение ответа, а его половина: вердикт
    принадлежит конкретной модели по конкретному адресу, и без них два пресета
    не различить.
    """

    schema_honored: bool
    model: str
    base_url: Optional[str]
    requested_keys: Tuple[str, ...]
    returned_keys: Tuple[str, ...]


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

    def _provider_key_for(self, preset: Optional[Dict[str, Any]]) -> Optional[str]:
        """Ключ, которым идёт вызов: свой ключ пресета либо общий из окружения."""
        return (preset or {}).get("api_key") or settings.openai_api_key

    def _require_provider_key(self, preset: Optional[Dict[str, Any]]) -> None:
        """Проверить адрес до вызова: без ключа идти некуда.

        Отсутствие ключа — настройка, а не сбой провайдера, поэтому оно
        опознаётся здесь, а не по невнятной ошибке SDK на первом же вызове.
        """
        if self._provider_key_for(preset):
            return
        preset_name = (preset or {}).get("name") or (preset or {}).get("key")
        whose = f"Пресет «{preset_name}»" if preset_name else "Активный пресет"
        raise AdminConfigurationError(
            f"{whose} не несёт ключа провайдера, и общий OPENAI_API_KEY не задан. "
            "Задайте ключ пресету через /add_model или укажите OPENAI_API_KEY в окружении."
        )

    def _get_client(self, preset: dict = None):
        """Get or create an OpenAI client for the given preset."""
        if not preset:
            return self.default_client

        base_url = preset.get('base_url') or settings.openai_base_url
        api_key = self._provider_key_for(preset)

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
        """Есть ли пригодный пресет — тот, к которому есть чем пойти.

        Готовность считается по пресетам, а не по глобальному ключу (ADR-0007):
        иначе деплой целиком на подписке, где ключ несёт сам пресет, выглядел бы
        ненастроенным. Общий ключ покрывает любой пресет без своего, поэтому
        конфигурация на одном ключе остаётся готовой как была.
        """
        if settings.openai_api_key:
            return True
        return any(preset.api_key for preset in settings.openai_models)

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
        self._require_provider_key(preset)
        return await self._protected(
            self._generate_two_stage,
            preset=preset,
            transcription=transcription,
            template_variables=template_variables,
            **context,
        )

    async def structured_call(self, *, system_prompt: str, user_prompt: str,
                              schema: Dict[str, Any], step: ModelStep,
                              preset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Один вызов модели со строгой схемой ответа (с надёжностью).

        Клиента и модель выбирает маршрут шага: вызывающий называет шаг, а не
        модель.
        """
        self._require_provider_key(preset)
        return await self._protected(
            self._call_openai,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            step=step,
            preset=preset,
        )

    async def probe_schema_support(
        self, *, preset: Optional[Dict[str, Any]] = None
    ) -> SchemaProbeVerdict:
        """Применяет ли модель пресета строгую схему ответа (ADR-0007).

        Зонд посылает схему с невозможными ключами и содержательный вопрос, в
        котором этих ключей нет, а вердикт выносит сравнением набора ключей
        ответа с затребованным. По коду ответа отказ неотличим от успеха:
        модель, выбросившая схему, отвечает успехом и валидным JSON — просто со
        своими ключами.

        Недоступность провайдера, неверный ключ и отсутствие ключа сюда не
        попадают: они выходят наружу ошибкой, а не вердиктом.
        """
        self._require_provider_key(preset)
        route = resolve_step(ModelStep.GENERATION, preset, self._get_client)

        answer = await self.structured_call(
            system_prompt=SCHEMA_PROBE_SYSTEM_PROMPT,
            user_prompt=SCHEMA_PROBE_USER_PROMPT,
            schema=SCHEMA_PROBE_SCHEMA,
            step=ModelStep.GENERATION,
            preset=preset,
        )

        requested = tuple(SCHEMA_PROBE_SCHEMA["schema"]["properties"])
        returned = tuple(answer)
        honored = set(returned) == set(requested)
        logger.info(
            f"Зонд схем: модель {route.model}, адрес {route.base_url}, "
            f"схема {'применяется' if honored else 'принята и выброшена'} "
            f"(ключи ответа: {', '.join(returned) or '—'})"
        )
        return SchemaProbeVerdict(
            schema_honored=honored,
            model=route.model,
            base_url=route.base_url,
            requested_keys=requested,
            returned_keys=returned,
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
                step=ModelStep.ANALYSIS,
                preset=preset,
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})

            logger.info(f"ЭТАП 1 завершен. Тип: {meeting_type}, Спикеров сопоставлено: {len(speaker_mapping)}")

        logger.info("Запуск ЭТАПА 2: Генерация протокола")

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
            step=ModelStep.GENERATION,
            preset=preset,
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

    async def _call_openai(self, *, system_prompt: str, user_prompt: str,
                           schema: Dict[str, Any], step: ModelStep,
                           preset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Единственный исполнитель вызова: маршрут шага → запрос → разбор ответа."""
        route = resolve_step(step, preset, self._get_client)
        step_name = step.value

        logger.info(route.describe())

        try:
            response = await asyncio.to_thread(
                route.client.chat.completions.create,
                model=route.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_schema", "json_schema": schema},
                extra_headers=route.extra_headers,
                **({"extra_body": route.extra_body} if route.extra_body else {}),
            )
            content = response.choices[0].message.content

            if settings.log_cache_metrics:
                log_cached_tokens_usage(
                    response=response,
                    context=f"generate_protocol_{step_name}",
                    model_name=route.model,
                    provider="openai"
                )

            return safe_json_parse(content, context=f"OpenAI {step_name} response")

        except Exception as e:
            logger.error(f"Ошибка при вызове OpenAI [{step_name}]: {e}")
            if _is_insufficient_credits_error(e):
                raise LLMInsufficientCreditsError(
                    str(e), provider="openai", model=route.model
                ) from e
            if _is_quota_exhausted_error(e):
                raise LLMQuotaExhaustedError(
                    str(e), provider="openai", model=route.model
                ) from e
            raise


# Глобальный экземпляр (один circuit-breaker/rate-limiter на процесс)
protocol_generator = ProtocolGenerator()
