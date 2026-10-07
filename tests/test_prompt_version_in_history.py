"""Версия промпта доезжает до истории обработки (#128).

Протоколы сравнивают по истории — там лежит и сам протокол. Отпечаток версии
промпта рядом с ним позволяет сгруппировать протоколы до и после правки правил.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, ProcessingResult, TranscriptionResult


def _result(**overrides) -> ProcessingResult:
    fields = dict(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Протокол",
        template_used={"name": "Стандартный"},
        llm_provider_used="openai",
        llm_model_used=None,
        prompt_version="abc123def456",
    )
    fields.update(overrides)
    return ProcessingResult(**fields)


@pytest.mark.asyncio
async def test_first_run_saves_prompt_version(monkeypatch):
    import src.services.processing.processing_history as module
    from src.services.processing.processing_history import ProcessingHistoryService

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(id=42)

    save = AsyncMock(return_value=1)
    monkeypatch.setattr(module.history_repo, "save_processing_result", save)
    await ProcessingHistoryService(user_service=FakeUserService()).save_processing_history(
        ProcessingRequest(file_name="m.mp3", template_id=1, llm_provider="openai", user_id=1),
        _result(),
    )

    assert save.await_args.kwargs["prompt_version"] == "abc123def456"


@pytest.mark.asyncio
async def test_completion_carries_prompt_version_from_generation():
    from src.services.processing.completion import CompletionDeps, complete_processing

    class FakeLLMGen:
        async def optimized_llm_generation(self, *args, **kwargs):
            return {"meeting_title": "Релиз", "_prompt_version": "v-from-generator"}

        async def resolve_model_display_name(self):
            return "GPT"

    saved = {}

    class FakeHistory:
        async def save_processing_history(self, request, result):
            saved["prompt_version"] = result.prompt_version
            return 5

    from src.services.processing.protocol_formatter import ProtocolFormatter

    outcome = await complete_processing(
        request=ProcessingRequest(file_name="m.mp3", llm_provider="openai", user_id=1),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(id=1, name="Краткое", content="# {{ meeting_title }}"),
        meeting_type=None,
        deps=CompletionDeps(
            llm_gen=FakeLLMGen(), formatter=ProtocolFormatter(), history=FakeHistory(),
        ),
        delivery=AsyncMock(return_value=True),
        cache_key=None, task_id=None, metrics=None,
    )

    assert outcome.delivered
    assert saved["prompt_version"] == "v-from-generator"


@pytest.mark.asyncio
async def test_prompt_version_lands_in_a_migrated_legacy_db(tmp_path):
    """На старой прод-БД колонки нет: миграция добавляет её, запись её заполняет."""
    import aiosqlite
    from test_processing_history_mapping_migration import _columns, _legacy_db

    from src.database.database import Database
    from src.database.history_repo import HistoryRepository

    db_path = await _legacy_db(tmp_path)
    db = Database(db_path=db_path)
    await db.init_db()
    assert "prompt_version" in await _columns(db_path)

    row_id = await HistoryRepository(db).save_processing_result(
        user_id=1, file_name="m.mp3", template_id=1, llm_provider="openai",
        transcription_text="т", result_text="# П", prompt_version="abc123def456",
    )
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT prompt_version FROM processing_history WHERE id = ?", (row_id,),
        )
        assert (await cursor.fetchone())[0] == "abc123def456"
