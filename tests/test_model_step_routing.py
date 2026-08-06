"""Характеризация маршрута трёх вызовов модели (#112).

Три вызова — сопоставление спикеров, ЭТАП 1 анализа, ЭТАП 2 генерации — сегодня
решают по-своему, каким клиентом и какой моделью идти. Тесты фиксируют это
решение ДО префактора: мок стоит на границе клиента модели
(``chat.completions.create``), как в характеризации генератора, и проверяет, что
именно ушло в вызов. Внутренний кеш клиентов тесты не трогают: клиент пресета
подменяется на границе конструктора ``openai.OpenAI``.
"""
import json
from unittest.mock import MagicMock

from src.config import settings
from src.models.diarization import Diarization, Segment
from src.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.reliability.rate_limiter import RateLimitConfig, RateLimiter
from src.reliability.retry import RetryConfig, RetryManager

PRESET = {
    "key": "openrouter-gpt-5",
    "name": "OpenRouter: gpt-5",
    "model": "openai/gpt-5",
    "base_url": "https://preset.example/v1",
    "api_key": "preset-key",
}

ANALYSIS_PAYLOAD = {
    "meeting_type": "status",
    "speaker_mappings": {"SPEAKER_0": "Анна"},
    "analysis_confidence": 0.9,
}
GENERATION_PAYLOAD = {
    "protocol_data": {"decisions": "решения"},
    "quality_score": 0.8,
}
MAPPING_PAYLOAD = {
    "meeting_type": "status",
    "speaker_mappings": {"SPEAKER_0": "Анна Петрова"},
    "confidence_scores": {"SPEAKER_0": 0.95},
    "unmapped_speakers": [],
}


def _response(payload: dict):
    """Ответ OpenAI SDK: choices[0].message.content с JSON-строкой."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
    return resp


def _generator_with_two_clients(monkeypatch):
    """Генератор, у которого глобальный клиент и клиент пресета различимы.

    Возвращает (генератор, глобальный клиент, клиент пресета, конструкторы) —
    последнее фиксирует, с каким адресом и ключом строился клиент пресета.
    """
    from src.llm.protocol_generator import ProtocolGenerator

    gen = ProtocolGenerator(
        retry_manager=RetryManager(RetryConfig(max_attempts=1, base_delay=0.001, jitter=False)),
        circuit_breaker=CircuitBreaker(
            "test_routing", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=0.05, timeout=5.0)
        ),
        rate_limiter=RateLimiter(
            "test_routing_api", RateLimitConfig(requests_per_window=1000, window_size=60.0, burst_limit=1000)
        ),
    )
    global_client = MagicMock(name="global_client")
    gen.default_client = global_client

    preset_client = MagicMock(name="preset_client")
    built = []

    def _fake_openai(**kwargs):
        built.append(kwargs)
        return preset_client

    import openai

    monkeypatch.setattr(openai, "OpenAI", _fake_openai)
    monkeypatch.setattr(settings, "log_cache_metrics", False)
    return gen, global_client, preset_client, built


def _diarization() -> Diarization:
    return Diarization(
        segments=[
            Segment(speaker="SPEAKER_0", text="Привет, начнём статус.", start=0.0, end=2.0),
            Segment(speaker="SPEAKER_1", text="Готов, докладываю.", start=2.0, end=4.0),
        ]
    )


# ------------------------------------------------- вызов 1: сопоставление спикеров


async def test_speaker_mapping_goes_to_global_client(monkeypatch):
    """Сопоставление спикеров идёт глобальным клиентом с моделью сопоставления."""
    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    global_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)
    monkeypatch.setattr(sms, "protocol_generator", gen)

    service = sms.SpeakerMappingService()
    mapping, meeting_type = await service.map_speakers_to_participants(
        diarization_data=_diarization(),
        participants=[{"name": "Анна Петрова", "role": "менеджер"}],
        transcription_text="Привет, начнём статус. Готов, докладываю.",
    )

    assert meeting_type == "status"
    assert mapping == {"SPEAKER_0": "Анна Петрова"}
    global_client.chat.completions.create.assert_called_once()
    preset_client.chat.completions.create.assert_not_called()
    call = global_client.chat.completions.create.call_args
    assert call.kwargs["model"] == settings.speaker_mapping_model


# ------------------------------------------------------- вызовы 2 и 3: генерация


async def test_analysis_stage_goes_to_global_client_while_generation_goes_to_preset(monkeypatch):
    """ЭТАП 1 — глобальный клиент и модель анализа, ЭТАП 2 — клиент и модель пресета."""
    gen, global_client, preset_client, built = _generator_with_two_clients(monkeypatch)
    global_client.chat.completions.create.return_value = _response(ANALYSIS_PAYLOAD)
    preset_client.chat.completions.create.return_value = _response(GENERATION_PAYLOAD)

    result = await gen.generate(
        preset=PRESET,
        transcription="SPEAKER_0: привет.",
        template_variables={"decisions": ""},
    )

    assert result["decisions"] == "решения"

    analysis_call = global_client.chat.completions.create.call_args
    assert global_client.chat.completions.create.call_count == 1
    assert analysis_call.kwargs["model"] == settings.analysis_stage_model

    generation_call = preset_client.chat.completions.create.call_args
    assert preset_client.chat.completions.create.call_count == 1
    assert generation_call.kwargs["model"] == PRESET["model"]

    assert len(built) == 1, "клиент пресета строится ровно один раз"
    assert built[0]["base_url"] == PRESET["base_url"]
    assert built[0]["api_key"] == PRESET["api_key"]


async def test_generation_without_preset_goes_to_global_client(monkeypatch):
    """Без пресета оба этапа идут глобальным клиентом, ЭТАП 2 — глобальной моделью."""
    gen, global_client, preset_client, built = _generator_with_two_clients(monkeypatch)
    global_client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]

    await gen.generate(preset=None, transcription="т", template_variables={"decisions": ""})

    models = [c.kwargs["model"] for c in global_client.chat.completions.create.call_args_list]
    assert models == [settings.analysis_stage_model, settings.openai_model]
    preset_client.chat.completions.create.assert_not_called()
    assert built == []


# ------------------------------------------------ заголовки и тело: одни на всех


async def test_every_step_carries_attribution_headers_and_no_extra_body(monkeypatch):
    """Все три вызова несут одни и те же заголовки атрибуции; тела запроса нет."""
    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(settings, "http_referer", "https://example.test/soroka")
    monkeypatch.setattr(settings, "x_title", "Сорока")
    monkeypatch.setattr(sms, "protocol_generator", gen)

    global_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)
    await sms.SpeakerMappingService().map_speakers_to_participants(
        diarization_data=_diarization(),
        participants=[{"name": "Анна Петрова"}],
        transcription_text="Привет.",
    )
    mapping_call = global_client.chat.completions.create.call_args

    global_client.chat.completions.create.reset_mock()
    global_client.chat.completions.create.return_value = _response(ANALYSIS_PAYLOAD)
    preset_client.chat.completions.create.return_value = _response(GENERATION_PAYLOAD)
    await gen.generate(preset=PRESET, transcription="т", template_variables={"decisions": ""})

    expected_headers = {
        "HTTP-Referer": "https://example.test/soroka",
        "X-Title": "Сорока",
    }
    calls = [
        mapping_call,
        *global_client.chat.completions.create.call_args_list,
        *preset_client.chat.completions.create.call_args_list,
    ]
    assert len(calls) == 3
    for call in calls:
        assert call.kwargs["extra_headers"] == expected_headers
        assert "extra_body" not in call.kwargs
        assert call.kwargs["temperature"] == 0.1


# ------------------------------------------------------------------------- лог


async def test_each_step_logs_its_preset_model_and_address(monkeypatch):
    """По каждому шагу в лог уходит пресет, модель и адрес, которые его обслужили."""
    from loguru import logger

    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(settings, "openai_base_url", "https://global.example/v1")
    monkeypatch.setattr(sms, "protocol_generator", gen)
    global_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)
    preset_client.chat.completions.create.return_value = _response(GENERATION_PAYLOAD)

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO")
    try:
        await sms.SpeakerMappingService().map_speakers_to_participants(
            diarization_data=_diarization(),
            participants=[{"name": "Анна Петрова"}],
            transcription_text="Привет.",
        )
        global_client.chat.completions.create.return_value = _response(ANALYSIS_PAYLOAD)
        await gen.generate(preset=PRESET, transcription="т", template_variables={"decisions": ""})
    finally:
        logger.remove(sink_id)

    lines = [str(record) for record in records]

    mapping_lines = [line for line in lines if "SpeakerMapping" in line]
    assert any(
        settings.speaker_mapping_model in line and "https://global.example/v1" in line
        for line in mapping_lines
    ), mapping_lines

    analysis_lines = [line for line in lines if "Analysis" in line]
    assert any(
        settings.analysis_stage_model in line and "https://global.example/v1" in line
        for line in analysis_lines
    ), analysis_lines

    generation_lines = [line for line in lines if "Generation" in line]
    assert any(
        PRESET["key"] in line and PRESET["model"] in line and PRESET["base_url"] in line
        for line in generation_lines
    ), generation_lines
