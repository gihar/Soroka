"""Один кеш на этап (#48): LLM-этап не кеширует сам себя.

Кеширование результата — забота верхнего кеша process_file с полным ключом;
этапный кеш LLM с неполным ключом удалён.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


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
    )


def _transcription():
    return SimpleNamespace(
        transcription="текст встречи", diarization=None,
        formatted_transcript="", diarization_analysis=None,
    )


async def test_llm_generation_runs_on_every_call(gen_service, monkeypatch):
    """Идентичные аргументы дважды → генерация выполняется дважды (этапного кеша нет)."""
    from src.llm import protocol_generator

    fake_generate = AsyncMock(return_value={"decisions": "решения", "_meeting_type": "status"})
    monkeypatch.setattr(protocol_generator, "generate", fake_generate)

    metrics = MagicMock()
    for _ in range(2):
        result = await gen_service.optimized_llm_generation(
            _transcription(), {"content": "{{decisions}}"}, _request(), metrics,
        )
        assert result["decisions"] == "решения"

    assert fake_generate.await_count == 2
