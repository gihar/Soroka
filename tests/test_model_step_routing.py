"""Маршрут трёх вызовов модели: клиент, модель, тело и заголовки (#112, #114, #115).

Три вызова — сопоставление спикеров, ЭТАП 1 анализа, ЭТАП 2 генерации — решают,
каким клиентом и какой моделью идти, и отвечают одинаково: клиентом активного
пресета. Пресет — полный адрес провайдера, поэтому его смена переносит весь путь
целиком; дешёвым шагам он может назначить свои модели, а пустое поле означает его
основную модель.

Мок стоит на границе клиента модели (``chat.completions.create``), как в
характеризации генератора, и проверяет, что именно ушло в вызов. Внутренний кеш
клиентов тесты не трогают: клиент пресета подменяется на границе конструктора
``openai.OpenAI``.
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

# Пресет — полный адрес провайдера (ADR-0007): вместе с ключом несёт параметры,
# без которых провайдер не работает (у Qwen выключение режима рассуждения) и
# атрибуцию, которая касается только его (у OpenRouter).
PRESET_WITH_PARAMS = {
    **PRESET,
    "extra_body": {"enable_thinking": False},
    "extra_headers": {"HTTP-Referer": "https://example.test/soroka", "X-Title": "Сорока"},
}

# Дешёвым шагам внутри пресета можно назначить свои модели — провайдер у всех
# шагов остаётся один (ADR-0007).
PRESET_WITH_CHEAP_MODELS = {
    **PRESET,
    "analysis_model": "openai/gpt-5-mini",
    "mapping_model": "openai/gpt-5-nano",
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


async def test_speaker_mapping_goes_to_the_preset_with_its_mapping_model(monkeypatch):
    """Сопоставление спикеров идёт клиентом пресета его моделью сопоставления."""
    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, built = _generator_with_two_clients(monkeypatch)
    preset_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)
    monkeypatch.setattr(sms, "protocol_generator", gen)

    service = sms.SpeakerMappingService()
    mapping, meeting_type = await service.map_speakers_to_participants(
        diarization_data=_diarization(),
        participants=[{"name": "Анна Петрова", "role": "менеджер"}],
        transcription_text="Привет, начнём статус. Готов, докладываю.",
        preset=PRESET_WITH_CHEAP_MODELS,
    )

    assert meeting_type == "status"
    assert mapping == {"SPEAKER_0": "Анна Петрова"}
    preset_client.chat.completions.create.assert_called_once()
    global_client.chat.completions.create.assert_not_called()
    call = preset_client.chat.completions.create.call_args
    assert call.kwargs["model"] == PRESET_WITH_CHEAP_MODELS["mapping_model"]
    assert built[0]["base_url"] == PRESET["base_url"]
    assert built[0]["api_key"] == PRESET["api_key"]


async def test_pipeline_hands_the_active_preset_to_speaker_mapping(monkeypatch):
    """Конвейер отдаёт сопоставлению активный пресет: вызов не уходит мимо него."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import src.services.processing.llm_generation as llm_generation
    import src.services.speaker_mapping_service as sms
    from src.services.processing.processing_service import ProcessingService

    monkeypatch.setattr(
        llm_generation, "resolve_active_preset", AsyncMock(return_value=PRESET)
    )
    fake_mapping = AsyncMock(return_value=({"SPEAKER_0": "Анна Петрова"}, "status"))
    monkeypatch.setattr(
        sms.speaker_mapping_service, "map_speakers_to_participants", fake_mapping
    )

    service = ProcessingService.__new__(ProcessingService)  # метод не трогает self
    mapping, meeting_type = await service._run_speaker_mapping(
        SimpleNamespace(
            participants_list=[{"name": "Анна Петрова"}], llm_provider="openai"
        ),
        SimpleNamespace(diarization=_diarization(), transcription="Привет."),
    )

    assert (mapping, meeting_type) == ({"SPEAKER_0": "Анна Петрова"}, "status")
    assert fake_mapping.call_args.kwargs["preset"] == PRESET


# ------------------------------------------------------- вызовы 2 и 3: генерация


async def test_analysis_and_generation_both_go_to_the_preset(monkeypatch):
    """Оба этапа идут клиентом пресета: ЭТАП 1 — моделью анализа, ЭТАП 2 — основной."""
    gen, global_client, preset_client, built = _generator_with_two_clients(monkeypatch)
    preset_client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]

    result = await gen.generate(
        preset=PRESET_WITH_CHEAP_MODELS,
        transcription="SPEAKER_0: привет.",
        template_variables={"decisions": ""},
    )

    assert result["decisions"] == "решения"
    global_client.chat.completions.create.assert_not_called()

    models = [c.kwargs["model"] for c in preset_client.chat.completions.create.call_args_list]
    assert models == [PRESET_WITH_CHEAP_MODELS["analysis_model"], PRESET["model"]]

    assert len(built) == 1, "клиент пресета строится ровно один раз"
    assert built[0]["base_url"] == PRESET["base_url"]
    assert built[0]["api_key"] == PRESET["api_key"]


async def test_empty_cheap_models_send_every_step_to_the_main_model(monkeypatch):
    """Пресет без моделей дешёвых шагов гонит все три шага на свою основную.

    Так заводится Qwen-пресет: все три вызова идут со строгими схемами, а
    единственная дешёвая модель эндпоинта их выбрасывает (ADR-0007).
    """
    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(sms, "protocol_generator", gen)
    preset_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)

    await sms.SpeakerMappingService().map_speakers_to_participants(
        diarization_data=_diarization(),
        participants=[{"name": "Анна Петрова"}],
        transcription_text="Привет.",
        preset=PRESET,
    )
    preset_client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    await gen.generate(preset=PRESET, transcription="т", template_variables={"decisions": ""})

    models = [c.kwargs["model"] for c in preset_client.chat.completions.create.call_args_list]
    assert models == [PRESET["model"]] * 3
    global_client.chat.completions.create.assert_not_called()


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


# --------------------------------------- заголовки и тело: из пресета, не общие


async def test_provider_params_reach_every_step_of_the_preset(monkeypatch):
    """Оба словаря пресета доходят как есть до каждого шага, который он обслуживает."""
    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    preset_client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]

    await gen.generate(
        preset=PRESET_WITH_PARAMS, transcription="т", template_variables={"decisions": ""}
    )

    calls = preset_client.chat.completions.create.call_args_list
    assert len(calls) == 2
    for call in calls:
        assert call.kwargs["extra_body"] == PRESET_WITH_PARAMS["extra_body"]
        assert call.kwargs["extra_headers"] == PRESET_WITH_PARAMS["extra_headers"]
        assert call.kwargs["temperature"] == 0.1


async def test_attribution_is_not_sent_to_a_preset_that_did_not_ask_for_it(monkeypatch):
    """Пресет без атрибуции её не получает: посторонние заголовки в чужой эндпоинт не летят."""
    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(sms, "protocol_generator", gen)

    preset_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)
    await sms.SpeakerMappingService().map_speakers_to_participants(
        diarization_data=_diarization(),
        participants=[{"name": "Анна Петрова"}],
        transcription_text="Привет.",
        preset=PRESET,
    )

    preset_client.chat.completions.create.side_effect = [
        _response(ANALYSIS_PAYLOAD),
        _response(GENERATION_PAYLOAD),
    ]
    await gen.generate(preset=PRESET, transcription="т", template_variables={"decisions": ""})

    global_client.chat.completions.create.assert_not_called()
    calls = preset_client.chat.completions.create.call_args_list
    assert len(calls) == 3, "все три шага обслужил один пресет"
    for call in calls:
        assert call.kwargs["extra_headers"] == {}
        assert "extra_body" not in call.kwargs


async def test_preset_without_key_inherits_the_shared_one(monkeypatch):
    """Пресет без своего ключа наследует общий: старая конфигурация работает как была."""
    gen, global_client, preset_client, built = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(settings, "openai_api_key", "sk-общий")
    global_client.chat.completions.create.return_value = _response(ANALYSIS_PAYLOAD)
    preset_client.chat.completions.create.return_value = _response(GENERATION_PAYLOAD)

    shared_key_preset = {k: v for k, v in PRESET.items() if k != "api_key"}
    await gen.generate(
        preset=shared_key_preset, transcription="т", template_variables={"decisions": ""}
    )

    assert len(built) == 1
    assert built[0]["api_key"] == "sk-общий"
    assert built[0]["base_url"] == PRESET["base_url"]


# ------------------------------------------------------------------------- лог


async def test_each_step_logs_its_preset_model_and_address(monkeypatch):
    """По каждому шагу в лог уходит пресет, модель и адрес, которые его обслужили."""
    from loguru import logger

    import src.services.speaker_mapping_service as sms

    gen, global_client, preset_client, _ = _generator_with_two_clients(monkeypatch)
    monkeypatch.setattr(settings, "openai_base_url", "https://global.example/v1")
    monkeypatch.setattr(sms, "protocol_generator", gen)
    preset_client.chat.completions.create.return_value = _response(MAPPING_PAYLOAD)

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO")
    try:
        await sms.SpeakerMappingService().map_speakers_to_participants(
            diarization_data=_diarization(),
            participants=[{"name": "Анна Петрова"}],
            transcription_text="Привет.",
            preset=PRESET_WITH_CHEAP_MODELS,
        )
        preset_client.chat.completions.create.side_effect = [
            _response(ANALYSIS_PAYLOAD),
            _response(GENERATION_PAYLOAD),
        ]
        await gen.generate(
            preset=PRESET_WITH_CHEAP_MODELS,
            transcription="т",
            template_variables={"decisions": ""},
        )
    finally:
        logger.remove(sink_id)

    lines = [str(record) for record in records]

    def _served_by(step: str, model: str) -> bool:
        return any(
            step in line
            and PRESET["key"] in line
            and model in line
            and PRESET["base_url"] in line
            for line in lines
        )

    assert _served_by("SpeakerMapping", PRESET_WITH_CHEAP_MODELS["mapping_model"]), lines
    assert _served_by("Analysis", PRESET_WITH_CHEAP_MODELS["analysis_model"]), lines
    assert _served_by("Generation", PRESET["model"]), lines
    assert "https://global.example/v1" not in "".join(lines), "глобальный адрес не обслуживал"
