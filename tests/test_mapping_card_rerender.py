"""Перерисовка карточки сопоставления не возвращает подавленные цитаты (#55).

Сессия сопоставления несёт множество спикеров с доставленными фрагментами;
callbacks (смена/выбор/назад) перерисовывают карточку из сессии — цитаты
спикеров с фрагментами не «воскресают».
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via handlers.
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.processing import ProcessingRequest, TranscriptionResult  # noqa: E402
from src.performance.metrics import ProcessingMetrics  # noqa: E402
from src.services.mapping_session import MappingSession  # noqa: E402


def _session(speakers_with_audio):
    request = ProcessingRequest(
        user_id=42, file_name="встреча.mp3", template_id=2, llm_provider="openai",
        participants_list=[{"name": "Иван Иванов"}],
    )
    transcription = TranscriptionResult(
        transcription="текст",
        diarization={
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "segments": [
                {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "цитата первого"},
                {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "цитата второго"},
            ],
        },
        speakers_text={"SPEAKER_1": "цитата первого", "SPEAKER_2": "цитата второго"},
        formatted_transcript="...", speakers_summary="2 спикера", compression_info=None,
    )
    return MappingSession(
        request=request,
        transcription_result=transcription,
        speaker_mapping={"SPEAKER_1": "Иван Иванов"},
        meeting_type="general",
        temp_file_path=None,
        cache_key=None,
        task_id=None,
        metrics=ProcessingMetrics(file_name="встреча.mp3", user_id=42, start_time=datetime.now()),
        speakers_with_audio=speakers_with_audio,
    )


@pytest.mark.asyncio
async def test_rerender_keeps_quotes_suppressed(monkeypatch):
    import src.utils.telegram_safe as ts
    from src.handlers.callbacks.speaker_mapping_callbacks import _show_main_view

    edited_texts = []

    async def fake_edit(message, text, **kwargs):
        edited_texts.append(text)
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    callback = SimpleNamespace(message=SimpleNamespace())
    await _show_main_view(callback, _session({"SPEAKER_1"}), user_id=42)

    assert len(edited_texts) == 1
    assert "цитата первого" not in edited_texts[0]  # фрагмент доставлен — без цитаты
    assert "цитата второго" in edited_texts[0]      # фрагмента нет — цитата на месте


@pytest.mark.asyncio
async def test_rerender_without_fragments_shows_all_quotes(monkeypatch):
    import src.utils.telegram_safe as ts
    from src.handlers.callbacks.speaker_mapping_callbacks import _show_main_view

    edited_texts = []

    async def fake_edit(message, text, **kwargs):
        edited_texts.append(text)
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    callback = SimpleNamespace(message=SimpleNamespace())
    await _show_main_view(callback, _session(set()), user_id=42)

    assert "цитата первого" in edited_texts[0]
    assert "цитата второго" in edited_texts[0]
