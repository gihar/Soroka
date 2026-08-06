"""Характеризация ProtocolGenerator: глубокий модуль генерации протокола (#36).

Эталон поведения — OpenAIProvider (двухэтапная генерация) + EnhancedLLMService
(надёжность). Мок — на границе OpenAI-клиента (chat.completions.create).
"""
import json
from unittest.mock import MagicMock

import pytest

from src.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.reliability.rate_limiter import RateLimitConfig, RateLimiter
from src.reliability.retry import RetryConfig, RetryManager


def _response(payload: dict):
    """Ответ OpenAI SDK: choices[0].message.content с JSON-строкой."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
    return resp

ANALYSIS_PAYLOAD = {
    "meeting_type": "status",
    "speaker_mappings": {"SPEAKER_0": "Анна", "SPEAKER_1": "Борис"},
    "analysis_confidence": 0.9,
}
GENERATION_PAYLOAD = {
    "protocol_data": {"decisions": "решения", "action_items": "задачи"},
    "quality_score": 0.8,
}


def _fast_generator(client=None, retry_attempts=3, failure_threshold=3):
    """ProtocolGenerator с быстрой надёжностью и мок-клиентом."""
    from src.llm.protocol_generator import ProtocolGenerator

    gen = ProtocolGenerator(
        retry_manager=RetryManager(RetryConfig(max_attempts=retry_attempts, base_delay=0.001, jitter=False)),
        circuit_breaker=CircuitBreaker(
            "test_llm", CircuitBreakerConfig(failure_threshold=failure_threshold, recovery_timeout=0.05, timeout=5.0)
        ),
        rate_limiter=RateLimiter(
            "test_api", RateLimitConfig(requests_per_window=1000, window_size=60.0, burst_limit=1000)
        ),
    )
    gen.default_client = client if client is not None else MagicMock()
    return gen


@pytest.fixture(autouse=True)
def _quiet_cache_metrics(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "log_cache_metrics", False)


async def test_generate_runs_two_stages_and_merges_result():
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    gen = _fast_generator(client)

    result = await gen.generate(
        preset=None,
        transcription="SPEAKER_0: привет. SPEAKER_1: начнём.",
        template_variables={"decisions": "", "action_items": ""},
    )

    assert client.chat.completions.create.call_count == 2
    assert result["decisions"] == "решения"
    assert result["action_items"] == "задачи"
    assert result["_meeting_type"] == "status"
    assert result["_speaker_mapping"] == {"SPEAKER_0": "Анна", "SPEAKER_1": "Борис"}
    assert result["_analysis_confidence"] == 0.9
    assert result["_quality_score"] == 0.8


async def test_stage1_skipped_when_type_and_mapping_provided():
    """Готовые тип встречи и сопоставление — ЭТАП 1 не выполняется."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [_response(GENERATION_PAYLOAD)]
    gen = _fast_generator(client)

    result = await gen.generate(
        preset=None,
        transcription="т",
        template_variables={},
        meeting_type="brainstorm",
        speaker_mapping={"SPEAKER_0": "Анна"},
    )

    assert client.chat.completions.create.call_count == 1  # только генерация
    assert result["_meeting_type"] == "brainstorm"
    assert result["_speaker_mapping"] == {"SPEAKER_0": "Анна"}
    assert result["_analysis_confidence"] == 0.0  # анализ не выполнялся


async def test_preset_models_used_for_both_stages():
    """Оба этапа берут модель из пресета: ЭТАП 1 — модель анализа, ЭТАП 2 — основную."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    gen = _fast_generator(client)
    gen._client_cache[("https://or.example/v1", hash("k"))] = client

    await gen.generate(
        preset={"key": "openai-gpt-5", "model": "openai/gpt-5",
                "base_url": "https://or.example/v1", "api_key": "k",
                "analysis_model": "openai/gpt-5-mini"},
        transcription="т",
        template_variables={},
    )

    stage1_model = client.chat.completions.create.call_args_list[0].kwargs["model"]
    stage2_model = client.chat.completions.create.call_args_list[1].kwargs["model"]
    assert stage1_model == "openai/gpt-5-mini"
    assert stage2_model == "openai/gpt-5"


async def test_transient_error_is_retried_then_succeeds():
    """Сетевая ошибка ретраится; второй заход двухэтапного вызова успешен."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        ConnectionError("temporary network"),
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    gen = _fast_generator(client)

    result = await gen.generate(preset=None, transcription="т", template_variables={})

    assert result["_meeting_type"] == "status"
    assert client.chat.completions.create.call_count == 3  # 1 сбой + 2 этапа


async def test_402_is_not_retried_and_propagates():
    """402 (кончились кредиты) — ровно один вызов, типизированная ошибка наверх."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    err = Exception("Error code: 402 - This request requires more credits")
    client = MagicMock()
    client.chat.completions.create.side_effect = err
    gen = _fast_generator(client)

    with pytest.raises(LLMInsufficientCreditsError):
        await gen.generate(preset=None, transcription="т", template_variables={})

    assert client.chat.completions.create.call_count == 1  # без ретраев


async def test_circuit_breaker_opens_and_blocks_calls():
    """После порога отказов CB открывается и блокирует вызовы без похода в API."""
    from src.reliability.circuit_breaker import CircuitBreakerError

    client = MagicMock()
    client.chat.completions.create.side_effect = ConnectionError("down")
    gen = _fast_generator(client, retry_attempts=1, failure_threshold=2)

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await gen.generate(preset=None, transcription="т", template_variables={})
    calls_before = client.chat.completions.create.call_count

    with pytest.raises(CircuitBreakerError):
        await gen.generate(preset=None, transcription="т", template_variables={})

    assert client.chat.completions.create.call_count == calls_before  # API не тронут


async def test_structured_call_contract():
    """structured_call: строгая схема, модель шага, распарсенный dict."""
    from src.llm.model_step import ModelStep

    client = MagicMock()
    client.chat.completions.create.return_value = _response(
        {"speaker_mappings": {"SPEAKER_0": "Анна"}, "unmapped_speakers": []}
    )
    gen = _fast_generator(client)

    result = await gen.structured_call(
        system_prompt="s", user_prompt="u",
        schema={"name": "mapping"}, step=ModelStep.SPEAKER_MAPPING,
    )

    from src.config import settings
    assert result["speaker_mappings"] == {"SPEAKER_0": "Анна"}
    call = client.chat.completions.create.call_args
    assert call.kwargs["model"] == settings.speaker_mapping_model
    assert call.kwargs["response_format"] == {"type": "json_schema", "json_schema": {"name": "mapping"}}


async def test_reset_closes_open_circuit_breaker():
    """Админский reset закрывает открытый CB; статистика доступна."""
    from src.reliability.circuit_breaker import CircuitBreakerError

    client = MagicMock()
    client.chat.completions.create.side_effect = ConnectionError("down")
    gen = _fast_generator(client, retry_attempts=1, failure_threshold=1)

    with pytest.raises(ConnectionError):
        await gen.generate(preset=None, transcription="т", template_variables={})
    with pytest.raises(CircuitBreakerError):
        await gen.generate(preset=None, transcription="т", template_variables={})

    stats = gen.get_reliability_stats()
    assert "circuit_breaker" in stats and "rate_limiter" in stats

    await gen.reset()
    client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD), _response(GENERATION_PAYLOAD),
    ]
    result = await gen.generate(preset=None, transcription="т", template_variables={})
    assert result["_meeting_type"] == "status"


def test_singleton_exported_from_package():
    """Синглтон protocol_generator доступен из src.llm."""
    from src.llm import protocol_generator
    from src.llm.protocol_generator import ProtocolGenerator

    assert isinstance(protocol_generator, ProtocolGenerator)


def test_invalidate_cache_for_base_url_clears_all_matching():
    gen = _fast_generator()
    gen._client_cache = {
        ("https://a.com/v1", 1): "x",
        ("https://a.com/v1", 2): "y",
        ("https://b.com/v1", 3): "z",
    }

    gen.invalidate_cache_for_base_url("https://a.com/v1")

    assert list(gen._client_cache) == [("https://b.com/v1", 3)]


def test_invalidate_cache_for_exact_entry_and_noop():
    gen = _fast_generator()
    gen._client_cache = {("https://a.com/v1", 1): "x"}

    gen.invalidate_cache_for(base_url="https://a.com/v1", api_key_hash=1)
    gen.invalidate_cache_for(base_url="nope", api_key_hash=None)  # no-op, не падает

    assert gen._client_cache == {}


async def test_missing_provider_key_is_a_configuration_error_before_the_call(monkeypatch):
    """Ключа нет ни у пресета, ни в окружении — ошибка настройки, а не поход в API."""
    from src.config import settings
    from src.exceptions.configuration import AdminConfigurationError
    from src.llm.model_step import ModelStep

    client = MagicMock()
    gen = _fast_generator(client)
    gen.default_client = None
    monkeypatch.setattr(settings, "openai_api_key", None)
    keyless_preset = {
        "key": "shared", "name": "OpenRouter: gpt-5", "model": "openai/gpt-5",
        "base_url": "https://openrouter.ai/api/v1",
    }

    with pytest.raises(AdminConfigurationError):
        await gen.generate(
            preset=keyless_preset, transcription="т", template_variables={},
        )
    with pytest.raises(AdminConfigurationError):
        await gen.structured_call(
            system_prompt="s", user_prompt="u", schema={"name": "mapping"},
            step=ModelStep.SPEAKER_MAPPING, preset=keyless_preset,
        )

    client.chat.completions.create.assert_not_called()


async def test_preset_with_its_own_key_works_without_the_global_one(monkeypatch):
    """Пресет несёт свой ключ — протокол делается без OPENAI_API_KEY в окружении."""
    from src.config import settings

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    gen = _fast_generator(client)
    gen.default_client = None  # глобального клиента без ключа не существует
    monkeypatch.setattr(settings, "openai_api_key", None)
    gen._client_cache[("https://token-plan.example/compatible-mode/v1", hash("sk-sp-qwen"))] = client

    result = await gen.generate(
        preset={"key": "qwen_plus", "model": "qwen3.7-plus",
                "base_url": "https://token-plan.example/compatible-mode/v1",
                "api_key": "sk-sp-qwen"},
        transcription="т",
        template_variables={"decisions": ""},
    )

    assert result["decisions"] == "решения"
    models = [c.kwargs["model"] for c in client.chat.completions.create.call_args_list]
    assert models == ["qwen3.7-plus", "qwen3.7-plus"]


def test_is_available_counts_usable_presets_not_the_global_key(monkeypatch):
    """Готовность — по наличию пригодного пресета: со своим ключом или под общим."""
    from src.config import OpenAIModelPreset, settings

    gen = _fast_generator()
    gen.default_client = None  # чисто-пресетный деплой: глобального клиента нет
    monkeypatch.setattr(settings, "openai_api_key", None)

    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="qwen_plus", name="Qwen: plus", model="qwen3.7-plus",
            base_url="https://token-plan.example/compatible-mode/v1",
            api_key="sk-sp-qwen",
        )
    ])
    assert gen.is_available() is True, "пресет несёт свой ключ — модуль готов"

    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="shared", name="OpenRouter: gpt-5", model="openai/gpt-5",
            base_url="https://openrouter.ai/api/v1",
        )
    ])
    assert gen.is_available() is False, "ключа нет ни у пресета, ни в окружении"

    monkeypatch.setattr(settings, "openai_api_key", "sk-общий")
    assert gen.is_available() is True, "общий ключ покрывает пресет без своего"
