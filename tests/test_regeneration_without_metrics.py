"""Перегенерация не ведёт метрик: ``processing_metrics=None`` — легальный вход.

Прод, 21–24.07.2026: каждое нажатие «Другой шаблон» падало с
``'NoneType' object has no attribute 'llm_duration'``. Перегенерация осознанно
идёт без метрик (``protocol_actions`` → ``complete_processing(metrics=None)``),
а ``optimized_llm_generation`` писала в них безусловно.

Существующие regen-тесты подменяли ``LLMGenerationService`` фейком — ровно тот
шов, который и ломался, поэтому баг проехал в прод. Здесь вызывается настоящая
генерация: сначала напрямую, затем через полный путь перегенерации.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _request():
    return SimpleNamespace(
        participants_list=None, speaker_mapping=None,
        meeting_topic=None, meeting_date=None, meeting_time=None,
        meeting_agenda=None, project_list=None, user_id=1, file_name="f.mp3",
        template_id=2, llm_provider="openai", language="ru",
    )


def _transcription():
    return SimpleNamespace(
        transcription="текст встречи", diarization=None,
        best_transcript="текст встречи",
    )


@pytest.fixture
def gen_service(monkeypatch):
    import src.services.processing.llm_generation as lg
    from src.services.processing.llm_generation import LLMGenerationService

    monkeypatch.setattr(
        lg, "resolve_active_preset",
        AsyncMock(return_value={"key": "openai-gpt-5", "name": "GPT-5",
                                "model": "openai/gpt-5"}),
    )
    # Валидация включена — иначе не дойдём до записи protocol_quality_score.
    monkeypatch.setattr(lg.settings, "enable_protocol_validation", True)
    monkeypatch.setattr(lg.settings, "log_cache_metrics", True)
    monkeypatch.setattr(
        lg.protocol_validator, "calculate_quality_score",
        MagicMock(return_value=SimpleNamespace(
            overall_score=0.9, completeness_score=0.9, structure_score=0.9,
            warnings=[], to_dict=lambda: {"overall_score": 0.9},
        )),
    )

    svc = LLMGenerationService(user_service=None, template_service=None)
    svc.get_template_variables_from_template = MagicMock(return_value={"decisions": ""})
    return svc


async def test_generation_survives_metrics_none(gen_service, monkeypatch):
    """Без метрик генерация доходит до результата, а не падает на записи замера."""
    from src.llm import protocol_generator

    monkeypatch.setattr(
        protocol_generator, "generate",
        AsyncMock(return_value={"decisions": "решения"}),
    )

    result = await gen_service.optimized_llm_generation(
        _transcription(), {"content": "{{decisions}}"}, _request(), None,
    )

    assert result["decisions"] == "решения"
    # Валидация всё равно отработала — её итог кладётся в протокол.
    assert result["_validation"] == {"overall_score": 0.9}


async def test_generation_still_records_metrics_when_given(gen_service, monkeypatch):
    """Основной путь не деградировал: переданные метрики по-прежнему заполняются."""
    from src.llm import protocol_generator

    monkeypatch.setattr(
        protocol_generator, "generate",
        AsyncMock(return_value={"decisions": "решения"}),
    )

    metrics = SimpleNamespace(llm_duration=0.0, protocol_quality_score=0.0)
    await gen_service.optimized_llm_generation(
        _transcription(), {"content": "{{decisions}}"}, _request(), metrics,
    )

    assert metrics.llm_duration > 0
    assert metrics.protocol_quality_score == 0.9


async def test_regenerate_end_to_end_without_stubbing_llm_service(monkeypatch):
    """Полный путь «Другой шаблон» с настоящим LLMGenerationService.

    Регрессия прода: здесь ломался стык ``metrics=None``. Фейк сервиса его
    скрывал, поэтому шов остаётся настоящим — подменяется только сам LLM-вызов.
    """
    import src.database as db_module
    import src.services.processing.llm_generation as lg
    from src.llm import protocol_generator
    from src.services import protocol_actions

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value={
            "id": 7, "user_id": 42, "file_name": "meeting.mp3",
            "transcription_text": "полная расшифровка встречи",
            "result_text": "# Старый протокол",
            "speaker_mapping": None, "meeting_type": None,
        }),
    )
    monkeypatch.setattr(
        db_module.history_repo, "save_processing_result", AsyncMock(return_value=101)
    )

    monkeypatch.setattr(
        lg, "resolve_active_preset",
        AsyncMock(return_value={"key": "openai-gpt-5", "name": "GPT-5",
                                "model": "openai/gpt-5"}),
    )
    monkeypatch.setattr(lg.settings, "enable_protocol_validation", False)
    # Содержательный протокол: форматтер отбраковывает рендер короче 50 символов
    # и уходит в фолбэк-расшифровку, что скрыло бы проверку доставки.
    monkeypatch.setattr(
        protocol_generator, "generate",
        AsyncMock(return_value={
            "meeting_title": "Планёрка",
            "decisions": (
                "1. Согласовать бюджет проекта до конца недели\n"
                "2. Перенести релиз на следующий спринт"
            ),
        }),
    )

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(
                id=5, name="Дейли",
                content="# {{ meeting_title }}\n\n## Решения\n{{ decisions }}",
            )

        def extract_template_variables(self, _content):
            return ["meeting_title", "decisions"]

    delivered = {}

    async def fake_send_result(bot, chat_id, user_id, request, result,
                               progress_tracker=None):
        delivered["result"] = result
        return True

    monkeypatch.setattr(protocol_actions, "send_result_to_user", fake_send_result)

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True, "перегенерация должна доходить до доставки без метрик"
    assert "Согласовать бюджет" in delivered["result"].protocol_text
