"""Критика v6, harden: протокол не выходит без даты (базовый реквизит).

Живые протоколы прода 5/5 уходили «наверх» без даты — LLM почти никогда не
извлекает её из аудио, а шапка честно прячет пустое поле (`{% if date %}`).
Фолбэк детерминированный (не промптовый): явная ``meeting_date`` из запроса,
иначе дата обработки в русском формате. Шов — единый хвост (ADR-0003), через
который проходят ВСЕ пути генерации, включая перегенерацию.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, TranscriptionResult
from src.services.processing.completion import CompletionDeps, complete_processing
from src.services.processing.llm_generation import (
    with_protocol_date_fallback,
    with_protocol_title_fallback,
)
from src.utils.date_format import format_russian_date, format_russian_day_month

# ---------------------------------------------------------------------------
# Русский формат даты обработки: «22 июля 2026»
# ---------------------------------------------------------------------------


def test_format_russian_date_genitive_month_no_leading_zero():
    assert format_russian_date(datetime(2026, 7, 22)) == "22 июля 2026"
    assert format_russian_date(datetime(2024, 1, 5)) == "5 января 2024"
    assert format_russian_date(datetime(2025, 12, 31)) == "31 декабря 2025"


# ---------------------------------------------------------------------------
# Пост-обработка protocol_data: непустое поле date гарантировано
# ---------------------------------------------------------------------------

_MOMENT = datetime(2026, 7, 22)


def test_empty_date_falls_back_to_meeting_date():
    out = with_protocol_date_fallback(
        {"date": "", "participants": "Иван"},
        meeting_date="15 июля 2026",
        processing_moment=_MOMENT,
    )
    assert out["date"] == "15 июля 2026"


def test_empty_date_without_meeting_date_falls_back_to_processing_date():
    out = with_protocol_date_fallback(
        {"date": ""},
        meeting_date=None,
        processing_moment=_MOMENT,
    )
    assert out["date"] == "22 июля 2026"


def test_explicit_llm_date_is_not_overwritten():
    out = with_protocol_date_fallback(
        {"date": "20 октября 2024"},
        meeting_date="15 июля 2026",
        processing_moment=_MOMENT,
    )
    assert out["date"] == "20 октября 2024"


def test_missing_date_key_is_filled():
    out = with_protocol_date_fallback(
        {"participants": "Иван"},
        meeting_date=None,
        processing_moment=_MOMENT,
    )
    assert out["date"] == "22 июля 2026"


def test_whitespace_only_date_is_treated_as_empty():
    out = with_protocol_date_fallback(
        {"date": "   "},
        meeting_date="15 июля 2026",
        processing_moment=_MOMENT,
    )
    assert out["date"] == "15 июля 2026"


def test_fallback_does_not_mutate_input():
    original = {"date": ""}
    with_protocol_date_fallback(
        original, meeting_date="15 июля 2026", processing_moment=_MOMENT
    )
    assert original == {"date": ""}  # исходный словарь не тронут


# ---------------------------------------------------------------------------
# Шов: единый хвост подставляет дату ДО рендера (проходят все пути генерации)
# ---------------------------------------------------------------------------


def _request(**over) -> ProcessingRequest:
    base = dict(file_name="a.mp3", llm_provider="openai", user_id=1)
    base.update(over)
    return ProcessingRequest(**base)


def _recording_deps(llm_result):
    seen = {}

    def format_protocol(template, result, transcription_result, warnings=None):
        seen["protocol_data"] = result
        return "# Протокол"

    deps = CompletionDeps(
        llm_gen=SimpleNamespace(
            optimized_llm_generation=AsyncMock(return_value=llm_result),
            resolve_model_display_name=AsyncMock(return_value="GPT"),
        ),
        formatter=SimpleNamespace(format_protocol=format_protocol),
        history=SimpleNamespace(
            save_processing_history=AsyncMock(return_value=1),
            cleanup_temp_file=AsyncMock(),
        ),
    )
    return deps, seen


async def _ok_delivery(result):
    return True


@pytest.mark.asyncio
async def test_tail_injects_meeting_date_before_render():
    deps, seen = _recording_deps({"meeting_title": "Планёрка", "date": ""})

    await complete_processing(
        request=_request(meeting_date="15 июля 2026"),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    # Рендер получил непустую дату из запроса.
    assert seen["protocol_data"]["date"] == "15 июля 2026"


@pytest.mark.asyncio
async def test_tail_keeps_llm_date_when_present():
    deps, seen = _recording_deps({"meeting_title": "Планёрка", "date": "20 октября 2024"})

    await complete_processing(
        request=_request(meeting_date="15 июля 2026"),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    # LLM-дата приоритетнее фолбэка запроса.
    assert seen["protocol_data"]["date"] == "20 октября 2024"


@pytest.mark.asyncio
async def test_tail_fills_date_even_without_any_source():
    deps, seen = _recording_deps({"meeting_title": "Планёрка", "date": ""})

    await complete_processing(
        request=_request(meeting_date=None),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    # Ни LLM, ни запрос не дали дату — но поле всё равно непустое (дата обработки).
    assert seen["protocol_data"]["date"].strip()


# ---------------------------------------------------------------------------
# Умный фолбэк-титул: пустой meeting_title → «Встреча DD месяца», не «Резюме встречи»
# ---------------------------------------------------------------------------


def test_format_russian_day_month_no_year():
    assert format_russian_day_month(datetime(2026, 7, 22)) == "22 июля"
    assert format_russian_day_month(datetime(2024, 1, 5)) == "5 января"


def test_empty_title_without_meeting_date_uses_processing_day_month():
    out = with_protocol_title_fallback(
        {"meeting_title": ""},
        meeting_date=None,
        processing_moment=_MOMENT,
    )
    assert out["meeting_title"] == "Встреча 22 июля"


def test_empty_title_prefers_meeting_date_source():
    out = with_protocol_title_fallback(
        {"meeting_title": ""},
        meeting_date="15 июля 2026",
        processing_moment=_MOMENT,
    )
    assert out["meeting_title"] == "Встреча 15 июля 2026"


def test_explicit_llm_title_is_not_overwritten():
    out = with_protocol_title_fallback(
        {"meeting_title": "Согласование бюджета Q3"},
        meeting_date="15 июля 2026",
        processing_moment=_MOMENT,
    )
    assert out["meeting_title"] == "Согласование бюджета Q3"


def test_missing_title_key_is_filled():
    out = with_protocol_title_fallback(
        {"date": "22 июля 2026"},
        meeting_date=None,
        processing_moment=_MOMENT,
    )
    assert out["meeting_title"] == "Встреча 22 июля"


def test_whitespace_only_title_is_treated_as_empty():
    out = with_protocol_title_fallback(
        {"meeting_title": "   "},
        meeting_date=None,
        processing_moment=_MOMENT,
    )
    assert out["meeting_title"] == "Встреча 22 июля"


def test_title_fallback_does_not_mutate_input():
    original = {"meeting_title": ""}
    with_protocol_title_fallback(
        original, meeting_date=None, processing_moment=_MOMENT
    )
    assert original == {"meeting_title": ""}


@pytest.mark.asyncio
async def test_tail_injects_title_fallback_before_render():
    deps, seen = _recording_deps({"meeting_title": "", "date": ""})

    await complete_processing(
        request=_request(meeting_date="15 июля 2026"),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    assert seen["protocol_data"]["meeting_title"] == "Встреча 15 июля 2026"


@pytest.mark.asyncio
async def test_tail_keeps_llm_title_when_present():
    deps, seen = _recording_deps({"meeting_title": "Планёрка команды", "date": ""})

    await complete_processing(
        request=_request(meeting_date="15 июля 2026"),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    assert seen["protocol_data"]["meeting_title"] == "Планёрка команды"


@pytest.mark.asyncio
async def test_tail_fills_title_even_without_any_source():
    deps, seen = _recording_deps({"meeting_title": "", "date": ""})

    await complete_processing(
        request=_request(meeting_date=None),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    # Титул непустой и осмысленный (дата обработки), а не безликое «Резюме встречи».
    title = seen["protocol_data"]["meeting_title"]
    assert title.startswith("Встреча ")
    assert len(title) > len("Встреча ")
