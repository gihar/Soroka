"""ProcessingHistoryService: сохранение истории донесёт итоги ЭТАПА 1.

Тип встречи и сопоставление спикеров, выведенные на анализе, попадают в запись
истории — чтобы перегенерация из неё пропустила анализ и не разошлась в именах
участников с уже отправленным протоколом.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.processing.processing_history import ProcessingHistoryService


def _request() -> ProcessingRequest:
    return ProcessingRequest(
        file_name="m.mp3", template_id=5, llm_provider="openai", user_id=1
    )


def _result(**overrides) -> ProcessingResult:
    fields = dict(
        transcription_result=TranscriptionResult(transcription="полный текст"),
        protocol_text="# Протокол",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )
    fields.update(overrides)
    return ProcessingResult(**fields)


def _service(monkeypatch, save_mock):
    import src.services.processing.processing_history as module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(id=42)

    monkeypatch.setattr(module.history_repo, "save_processing_result", save_mock)
    return ProcessingHistoryService(user_service=FakeUserService())


@pytest.mark.asyncio
async def test_history_save_forwards_mapping_and_type(monkeypatch):
    save_mock = AsyncMock(return_value=100)
    service = _service(monkeypatch, save_mock)

    result = _result(
        meeting_type="daily",
        speaker_mapping={"SPEAKER_00": "Иван"},
    )
    await service.save_processing_history(_request(), result)

    kwargs = save_mock.await_args.kwargs
    assert kwargs["meeting_type"] == "daily"
    assert kwargs["speaker_mapping"] == {"SPEAKER_00": "Иван"}


@pytest.mark.asyncio
async def test_history_save_tolerates_legacy_result_without_fields(monkeypatch):
    """Старый закешированный результат без новых полей не роняет сохранение."""
    save_mock = AsyncMock(return_value=100)
    service = _service(monkeypatch, save_mock)

    # объект без атрибутов meeting_type/speaker_mapping — имитация старого pickle
    legacy = SimpleNamespace(
        transcription_result=SimpleNamespace(transcription="т"),
        protocol_text="# П",
        llm_provider_used="openai",
    )
    await service.save_processing_history(_request(), legacy)

    kwargs = save_mock.await_args.kwargs
    assert kwargs["meeting_type"] is None
    assert kwargs["speaker_mapping"] is None
