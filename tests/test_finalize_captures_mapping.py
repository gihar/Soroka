"""Основной путь генерации доносит итоги ЭТАПА 1 в результат.

_finalize_protocol складывает в ProcessingResult тип встречи и сопоставление
спикеров, которые фактически использовал генератор (эффективные значения из
llm_result, с фолбэком на запрос). Дальше их подхватывает сохранение истории —
и перегенерация из этой истории уже не гоняет анализ заново.
"""

import types
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, TranscriptionResult


def _service(monkeypatch, llm_result):
    import src.services.processing.processing_service as pss

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    service.llm_gen = types.SimpleNamespace(
        optimized_llm_generation=AsyncMock(return_value=llm_result),
        resolve_model_display_name=AsyncMock(return_value="GPT"),
    )
    service.formatter = types.SimpleNamespace(
        format_protocol=lambda *a, **k: "# Протокол"
    )
    service.history = types.SimpleNamespace()
    return service


def _metrics():
    return types.SimpleNamespace(total_duration=1.0, formatting_duration=0.0)


@pytest.mark.asyncio
async def test_finalize_captures_effective_mapping_from_llm(monkeypatch):
    llm_result = {
        "meeting_title": "Планёрка",
        "_meeting_type": "daily",
        "_speaker_mapping": {"SPEAKER_00": "Иван"},
    }
    service = _service(monkeypatch, llm_result)

    request = ProcessingRequest(
        file_name="a.mp3", llm_provider="openai", user_id=1,
    )
    result = await service._finalize_protocol(
        request,
        TranscriptionResult(transcription="текст"),
        types.SimpleNamespace(name="Дейли"),
        _metrics(),
        meeting_type=None,
    )

    assert result.meeting_type == "daily"
    assert result.speaker_mapping == {"SPEAKER_00": "Иван"}


@pytest.mark.asyncio
async def test_finalize_falls_back_to_request_when_llm_silent(monkeypatch):
    """Генератор пропустил ЭТАП 1 (значения переданы) — берём их из запроса/аргумента."""
    llm_result = {"meeting_title": "Планёрка"}  # без _meeting_type/_speaker_mapping
    service = _service(monkeypatch, llm_result)

    request = ProcessingRequest(
        file_name="a.mp3", llm_provider="openai", user_id=1,
        speaker_mapping={"SPEAKER_01": "Анна"},
    )
    result = await service._finalize_protocol(
        request,
        TranscriptionResult(transcription="текст"),
        types.SimpleNamespace(name="Дейли"),
        _metrics(),
        meeting_type="planning",
    )

    assert result.meeting_type == "planning"
    assert result.speaker_mapping == {"SPEAKER_01": "Анна"}
