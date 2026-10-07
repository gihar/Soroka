"""«Другой шаблон» на размеченной транскрипции (#130).

История хранила сырой текст бэкенда — без меток спикеров и после очистки, — а
перегенерация подавала модели сохранённое сопоставление «SPEAKER_1 = Имя».
Привязать реплики к именам модели было нечем (на проде 0 из 86 сохранённых
текстов с метками). Теперь история хранит ровно тот текст, что первая обработка
отдала модели, и перегенерация работает на нём же.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.diarization import Diarization, Segment
from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)


def _diarized_result() -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(
            transcription="сырой текст без меток",
            diarization=Diarization(segments=[
                Segment(speaker="SPEAKER_1", text="Запускаем релиз в пятницу."),
                Segment(speaker="SPEAKER_2", text="Я возьму проверку."),
            ]),
        ),
        protocol_text="# Протокол",
        template_used={"name": "Стандартный"},
        llm_provider_used="openai",
        llm_model_used=None,
        speaker_mapping={"SPEAKER_1": "Иван Петров", "SPEAKER_2": "Мария Ким"},
        meeting_type="business",
    )


async def _save_first_run(monkeypatch) -> dict:
    """Первая обработка пишет историю — возвращает аргументы записи."""
    import src.services.processing.processing_history as module
    from src.services.processing.processing_history import ProcessingHistoryService

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(id=42)

    save = AsyncMock(return_value=100)
    monkeypatch.setattr(module.history_repo, "save_processing_result", save)
    await ProcessingHistoryService(user_service=FakeUserService()).save_processing_history(
        ProcessingRequest(file_name="m.mp3", template_id=1, llm_provider="openai", user_id=1),
        _diarized_result(),
    )
    return save.await_args.kwargs


@pytest.mark.asyncio
async def test_history_keeps_the_text_the_model_saw(monkeypatch):
    saved = await _save_first_run(monkeypatch)

    assert saved["transcription_text"] == _diarized_result().transcription_result.best_transcript
    assert "SPEAKER_1" in saved["transcription_text"]


@pytest.mark.asyncio
async def test_other_template_hands_the_model_labeled_text(monkeypatch):
    saved = await _save_first_run(monkeypatch)

    import src.database as db_module
    import src.services.processing.llm_generation as llm_gen_module
    from src.services import protocol_actions

    row = {
        "id": 7, "user_id": 42, "file_name": "m.mp3",
        "transcription_text": saved["transcription_text"],
        "result_text": "# Протокол",
        "speaker_mapping": json.dumps(saved["speaker_mapping"], ensure_ascii=False),
        "meeting_type": saved["meeting_type"],
    }
    regen_save = AsyncMock(return_value=101)
    monkeypatch.setattr(db_module.history_repo, "get_result_for_user", AsyncMock(return_value=row))
    monkeypatch.setattr(db_module.history_repo, "save_processing_result", regen_save)

    seen = {}

    class FakeLLMGen:
        def __init__(self, *args, **kwargs):
            pass

        async def optimized_llm_generation(self, transcription_result, template, request, metrics, meeting_type=None):
            seen["text"] = transcription_result.best_transcript
            return {"meeting_title": "Релиз"}

        async def resolve_model_display_name(self):
            return "GPT"

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(id=5, name="Краткое", content="# {{ meeting_title }}")

    monkeypatch.setattr(llm_gen_module, "LLMGenerationService", FakeLLMGen)
    monkeypatch.setattr(protocol_actions, "send_result_to_user", AsyncMock(return_value=True))

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1, history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True
    assert "SPEAKER_1" in seen["text"] and "SPEAKER_2" in seen["text"]
    # Новая запись истории — тот же размеченный текст: цепочка перегенераций не деградирует.
    assert regen_save.await_args.kwargs["transcription_text"] == saved["transcription_text"]
