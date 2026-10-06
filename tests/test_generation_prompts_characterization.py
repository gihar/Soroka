"""Характеризация промптов генерации: что уходит модели от входных данных встречи.

Главный инвариант рефакторинга «один вход вместо 14 аргументов»: финальные
system/user промпты обоих этапов, уходящие в клиент модели, остаются байт-в-байт
теми же. Снимок `tests/fixtures/generation_prompts_snapshot.json` записан на коде
ДО рефакторинга (см. `regenerate_snapshot`) — он и есть независимый источник
истины, а не пересчёт тем же способом, что и код.

Шов — `LLMGenerationService.optimized_llm_generation`: его интерфейс (запрос на
обработку + тип встречи) рефакторинг не меняет, поэтому один и тот же тест
гоняется до и после. Мок — только на границе системы: SDK OpenAI (клиент, которого
генератор строит по пресету), ответы модели фиксированы.

Набор входов покрывает каждое поле встречи по отдельности и вместе: участники
(с ролями, без ролей, полное ФИО, пустой список), тема/дата/время, повестка,
проекты, сопоставление спикеров и тип встречи — во всех сочетаниях, решающих,
идёт ли ЭТАП 1 анализа.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import openai
import pytest

from src.models.llm_schemas import MEETING_ANALYSIS_SCHEMA
from src.models.processing import ProcessingRequest, TranscriptionResult
from src.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.reliability.rate_limiter import RateLimitConfig, RateLimiter
from src.reliability.retry import RetryConfig, RetryManager

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "generation_prompts_snapshot.json"

PRESET = {
    "key": "openai-gpt-5", "name": "GPT-5", "model": "openai/gpt-5",
    "base_url": "https://llm.example/v1", "api_key": "k",
}

TRANSCRIPT = "SPEAKER_1: Добрый день, начнём.\nSPEAKER_2: Да, по плану релиз в пятницу."

ANALYSIS_ANSWER = {
    "meeting_type": "status",
    "speaker_mappings": {"SPEAKER_1": "Алексей Тимченко"},
    "unmapped_speakers": ["SPEAKER_2"],
    "analysis_confidence": 0.9,
}
GENERATION_ANSWER = {"protocol_data": {"decisions": "Релиз в пятницу"}, "quality_score": 0.8}

PARTICIPANTS = [
    {"name": "Тимченко Алексей Александрович", "role": "Руководитель"},
    {"name": "Анна Смирнова", "role": ""},
    {"name": "Борис"},
]
DETAILS = {"meeting_topic": "Релиз 2.0", "meeting_date": "05.10.2026", "meeting_time": "11:00"}
AGENDA = "1. Статус релиза\n2. Риски"
PROJECTS = "Сорока, Детский мир"
MAPPING = {"SPEAKER_1": "Алексей Тимченко", "SPEAKER_2": "Анна Смирнова"}

CUSTOM_TEMPLATE = {"name": "Мой шаблон", "content": "{{ decisions }} {{ action_items }}"}
BRIEF_TEMPLATE = {"name": "Стандартный протокол встречи", "content": "{{ decisions }}"}

# id → (поля запроса, тип встречи от вызывающего, шаблон)
CASES = {
    "bare": ({}, None, CUSTOM_TEMPLATE),
    "participants": ({"participants_list": PARTICIPANTS}, None, CUSTOM_TEMPLATE),
    "participants_empty_list": ({"participants_list": []}, None, CUSTOM_TEMPLATE),
    "meeting_details": (DETAILS, None, CUSTOM_TEMPLATE),
    "participants_and_details": (
        {"participants_list": PARTICIPANTS, **DETAILS}, None, CUSTOM_TEMPLATE,
    ),
    "agenda_only": ({"meeting_agenda": AGENDA}, None, CUSTOM_TEMPLATE),
    "projects_only": ({"project_list": PROJECTS}, None, CUSTOM_TEMPLATE),
    "agenda_and_projects": (
        {"meeting_agenda": AGENDA, "project_list": PROJECTS}, None, CUSTOM_TEMPLATE,
    ),
    "mapping_without_type": ({"speaker_mapping": MAPPING}, None, CUSTOM_TEMPLATE),
    "type_without_mapping": ({}, "technical", CUSTOM_TEMPLATE),
    "type_and_mapping": ({"speaker_mapping": MAPPING}, "technical", CUSTOM_TEMPLATE),
    "everything_with_analysis": (
        {"participants_list": PARTICIPANTS, **DETAILS, "meeting_agenda": AGENDA,
         "project_list": PROJECTS, "speaker_mapping": MAPPING},
        None, CUSTOM_TEMPLATE,
    ),
    "everything_analysis_skipped": (
        {"participants_list": PARTICIPANTS, **DETAILS, "meeting_agenda": AGENDA,
         "project_list": PROJECTS, "speaker_mapping": MAPPING},
        "business", CUSTOM_TEMPLATE,
    ),
    "brief_template_with_participants": (
        {"participants_list": PARTICIPANTS, "meeting_agenda": AGENDA},
        None, BRIEF_TEMPLATE,
    ),
}


def _answer(**kwargs):
    """Ответ модели по имени схемы: анализ или генерация."""
    name = kwargs["response_format"]["json_schema"]["name"]
    payload = ANALYSIS_ANSWER if name == MEETING_ANALYSIS_SCHEMA["name"] else GENERATION_ANSWER
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
    return resp


def _generator():
    from src.llm.protocol_generator import ProtocolGenerator

    return ProtocolGenerator(
        retry_manager=RetryManager(RetryConfig(max_attempts=1, base_delay=0.001, jitter=False)),
        circuit_breaker=CircuitBreaker(
            "test_llm", CircuitBreakerConfig(failure_threshold=100, timeout=5.0),
        ),
        rate_limiter=RateLimiter(
            "test_api",
            RateLimitConfig(requests_per_window=1000, window_size=60.0, burst_limit=1000),
        ),
    )


def _protocol_keys(json_schema: dict):
    """Закрытые ключи протокола в схеме: бриф-контракт их фиксирует, legacy — нет."""
    protocol = json_schema["schema"]["properties"].get("protocol_data", {})
    keys = protocol.get("properties")
    return sorted(keys) if keys else None


async def capture(case_id: str, monkeypatch) -> dict:
    """Прогнать случай через шов и вернуть всё, что ушло модели, и итог генерации."""
    import src.llm as llm_package
    import src.services.processing.llm_generation as llm_gen

    fields, meeting_type, template = CASES[case_id]

    client = MagicMock()
    client.chat.completions.create.side_effect = _answer
    monkeypatch.setattr(openai, "OpenAI", lambda **_: client)
    monkeypatch.setattr(llm_package, "protocol_generator", _generator())
    monkeypatch.setattr(llm_gen.settings, "enable_protocol_validation", False)
    monkeypatch.setattr(llm_gen.settings, "log_cache_metrics", False)

    service = llm_gen.LLMGenerationService(
        user_service=None,
        template_service=SimpleNamespace(
            extract_template_variables=lambda content: ["decisions", "action_items"],
        ),
        preset=PRESET,
    )
    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1, **fields)
    result = await service.optimized_llm_generation(
        TranscriptionResult(transcription=TRANSCRIPT), template, request, None,
        meeting_type=meeting_type,
    )

    calls = [
        {
            "schema": c.kwargs["response_format"]["json_schema"]["name"],
            "protocol_keys": _protocol_keys(c.kwargs["response_format"]["json_schema"]),
            "model": c.kwargs["model"],
            "system": c.kwargs["messages"][0]["content"],
            "user": c.kwargs["messages"][1]["content"],
        }
        for c in client.chat.completions.create.call_args_list
    ]
    stage1 = {k: result[k] for k in ("_meeting_type", "_speaker_mapping", "_analysis_confidence")}
    return {"calls": calls, "result": stage1}


def _snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_id", sorted(CASES))
async def test_prompts_reaching_the_model_match_the_snapshot(case_id, monkeypatch):
    """Каждый вход встречи даёт ровно те промпты и итоги ЭТАПА 1, что и до рефакторинга."""
    assert await capture(case_id, monkeypatch) == _snapshot()[case_id]


def test_snapshot_covers_every_case():
    """Снимок и набор случаев не разъехались: нет ни лишних, ни потерянных."""
    assert set(_snapshot()) == set(CASES)


def _context_block(user_prompt: str) -> str:
    """Блок <context> промпта генерации (пусто, если блока нет)."""
    if "<context>" not in user_prompt:
        return ""
    return user_prompt.split("<context>", 1)[1].split("</context>", 1)[0]


async def test_meeting_topic_date_and_time_reach_the_generation_prompt(monkeypatch):
    """Тема, дата и время, которые ввёл пользователь, модель видит в контексте генерации.

    Правила полей ``date``/``time`` велят модели брать ``meeting_date`` и
    ``meeting_time``, если на записи их не назвали, — значит, они обязаны быть в
    промпте. Раньше ``meeting_metadata`` молча терялся по дороге к промпту.
    """
    captured = await capture("meeting_details", monkeypatch)
    generation = captured["calls"][-1]
    context = _context_block(generation["user"])

    assert "Релиз 2.0" in context
    assert "meeting_date" in context and "05.10.2026" in context
    assert "meeting_time" in context and "11:00" in context


async def test_meeting_topic_reaches_the_analysis_prompt(monkeypatch):
    """Тема встречи — подсказка для определения её типа: анализ её тоже видит."""
    captured = await capture("meeting_details", monkeypatch)
    analysis = captured["calls"][0]

    assert analysis["schema"] == "MeetingAnalysisSchema"
    assert "Релиз 2.0" in analysis["user"]


async def test_without_meeting_details_the_prompts_carry_no_context(monkeypatch):
    """Пустые тема, дата и время блока контекста не порождают — промпт как без них."""
    captured = await capture("bare", monkeypatch)

    assert _context_block(captured["calls"][-1]["user"]) == ""


async def test_request_mapping_without_meeting_type_does_not_skip_analysis(monkeypatch):
    """Сопоставление из запроса без типа встречи: ЭТАП 1 идёт, и побеждает его сопоставление."""
    captured = await capture("mapping_without_type", monkeypatch)

    assert [c["schema"] for c in captured["calls"]] == [
        "MeetingAnalysisSchema", "ProtocolDataSchema",
    ]
    assert captured["result"]["_speaker_mapping"] == {"SPEAKER_1": "Алексей Тимченко"}


async def regenerate_snapshot() -> None:
    """Переснять снимок. Вызывать ТОЛЬКО на коде, чьё поведение принято эталоном."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        snapshot = {case_id: await capture(case_id, monkeypatch) for case_id in sorted(CASES)}
    finally:
        monkeypatch.undo()
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
