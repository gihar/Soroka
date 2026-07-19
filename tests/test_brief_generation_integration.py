"""Интеграция бриф-схем в генерацию протокола (Фаза 1).

Системный шаблон (есть бриф по имени) → строгая бриф-схема с фиксированными
ключами + инструкции секций брифа в системном промпте ЭТАПА 2. Кастомный шаблон
(брифа нет) → legacy-путь: PROTOCOL_DATA_SCHEMA + правила из template_variables.

Мок — на границе OpenAI-клиента (chat.completions.create); перехватываем схему
(response_format) и системный промпт генерации.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.llm_schemas import PROTOCOL_DATA_SCHEMA
from src.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.reliability.rate_limiter import RateLimitConfig, RateLimiter
from src.reliability.retry import RetryConfig, RetryManager
from src.services.brief_compiler import brief_field_rules, brief_to_schema
from src.services.protocol_briefs import get_brief_for


def _response(payload: dict):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
    return resp


GENERATION_PAYLOAD = {"protocol_data": {"decisions": "решения"}, "quality_score": 0.8}


def _fast_generator(client):
    from src.llm.protocol_generator import ProtocolGenerator

    gen = ProtocolGenerator(
        retry_manager=RetryManager(RetryConfig(max_attempts=3, base_delay=0.001, jitter=False)),
        circuit_breaker=CircuitBreaker(
            "test_llm",
            CircuitBreakerConfig(failure_threshold=3, recovery_timeout=0.05, timeout=5.0),
        ),
        rate_limiter=RateLimiter(
            "test_api",
            RateLimitConfig(requests_per_window=1000, window_size=60.0, burst_limit=1000),
        ),
    )
    gen.default_client = client
    return gen


@pytest.fixture(autouse=True)
def _quiet_cache_metrics(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "log_cache_metrics", False)


async def _generate(gen, *, template_variables, template_name=None):
    """Один прогон генерации со скипом ЭТАПА 1 (готовые тип и сопоставление),
    поэтому вызов генерации — единственный (call_args_list[0])."""
    await gen.generate(
        preset=None,
        transcription="т",
        template_variables=template_variables,
        template_name=template_name,
        meeting_type="status",
        speaker_mapping={"SPEAKER_0": "Анна"},
    )


def _generation_kwargs(client):
    return client.chat.completions.create.call_args_list[0].kwargs


async def test_system_template_sends_brief_schema():
    """Дейли (системный шаблон с брифом) → в LLM уходит его строгая бриф-схема."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [_response(GENERATION_PAYLOAD)]
    gen = _fast_generator(client)

    await _generate(gen, template_variables={"decisions": "", "yesterday_progress": ""},
                    template_name="Дейли")

    schema = _generation_kwargs(client)["response_format"]["json_schema"]
    assert schema == brief_to_schema(get_brief_for("Дейли"))
    props = schema["schema"]["properties"]["protocol_data"]["properties"]
    assert {"yesterday_progress", "today_plans"} <= set(props)


async def test_custom_template_sends_legacy_schema():
    """Кастомный шаблон (брифа нет) → legacy PROTOCOL_DATA_SCHEMA без изменений."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [_response(GENERATION_PAYLOAD)]
    gen = _fast_generator(client)

    await _generate(gen, template_variables={"decisions": ""},
                    template_name="Мой кастомный шаблон")

    schema = _generation_kwargs(client)["response_format"]["json_schema"]
    assert schema == PROTOCOL_DATA_SCHEMA


async def test_missing_template_name_sends_legacy_schema():
    """Имя шаблона не передано → legacy-путь (обратная совместимость)."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [_response(GENERATION_PAYLOAD)]
    gen = _fast_generator(client)

    await _generate(gen, template_variables={"decisions": ""})

    schema = _generation_kwargs(client)["response_format"]["json_schema"]
    assert schema == PROTOCOL_DATA_SCHEMA


async def test_brief_prompt_carries_section_instructions():
    """Бриф-путь: системный промпт ЭТАПА 2 несёт инструкции секций брифа."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [_response(GENERATION_PAYLOAD)]
    gen = _fast_generator(client)

    await _generate(gen, template_variables={"decisions": ""}, template_name="Дейли")

    system_prompt = _generation_kwargs(client)["messages"][0]["content"]
    for instruction in brief_field_rules(get_brief_for("Дейли")).values():
        assert instruction and instruction in system_prompt


# ---------------------------------------------------------------------------
# Проброс имени шаблона из optimized_llm_generation в generate(): имя добывается
# устойчиво — template может быть dict или объектом.
# ---------------------------------------------------------------------------


@pytest.fixture
def gen_service(monkeypatch):
    import src.services.processing.llm_generation as lg
    from src.services.processing.llm_generation import LLMGenerationService

    monkeypatch.setattr(
        lg, "resolve_active_preset",
        AsyncMock(return_value={"key": "openai-gpt-5", "name": "GPT-5", "model": "openai/gpt-5"}),
    )
    monkeypatch.setattr(lg.settings, "enable_protocol_validation", False)
    monkeypatch.setattr(lg.settings, "log_cache_metrics", False)

    svc = LLMGenerationService(user_service=None, template_service=None)
    svc.get_template_variables_from_template = MagicMock(return_value={"decisions": ""})
    return svc


def _request():
    return SimpleNamespace(
        participants_list=None, speaker_mapping=None,
        meeting_topic=None, meeting_date=None, meeting_time=None,
        meeting_agenda=None, project_list=None, user_id=1, file_name="f.mp3",
        template_id=2, llm_provider="openai", language="ru",
    )


def _transcription():
    return SimpleNamespace(
        transcription="текст встречи", diarization=None, best_transcript="текст встречи",
    )


async def test_forwards_template_name_from_dict(gen_service, monkeypatch):
    from src.llm import protocol_generator

    fake = AsyncMock(return_value={"decisions": "р", "_meeting_type": "status"})
    monkeypatch.setattr(protocol_generator, "generate", fake)

    await gen_service.optimized_llm_generation(
        _transcription(), {"name": "Дейли", "content": "{{decisions}}"},
        _request(), MagicMock(),
    )

    assert fake.await_args.kwargs["template_name"] == "Дейли"


async def test_forwards_template_name_from_object(gen_service, monkeypatch):
    from src.llm import protocol_generator

    fake = AsyncMock(return_value={"decisions": "р", "_meeting_type": "status"})
    monkeypatch.setattr(protocol_generator, "generate", fake)

    template = SimpleNamespace(name="Техническое совещание", content="{{decisions}}")
    await gen_service.optimized_llm_generation(
        _transcription(), template, _request(), MagicMock(),
    )

    assert fake.await_args.kwargs["template_name"] == "Техническое совещание"
