"""Превью аудио вызывается ПЕРЕД показом UI сопоставления и не ломает его при ошибке."""

import os
import sys
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))


def _make_service():
    # Метод не использует self — создаём инстанс без __init__.
    from src.services.processing.processing_service import ProcessingService
    return ProcessingService.__new__(ProcessingService)


def _make_args():
    request = SimpleNamespace(
        user_id=7,
        participants_list=[{"name": "Иван Иванов"}],
        model_dump=lambda: {},
    )
    transcription_result = SimpleNamespace(
        diarization={
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "segments": [
                {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "привет"},
                {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "да"},
            ],
        },
        transcription="t",
        formatted_transcript="f",
        speakers_text={"SPEAKER_1": "привет", "SPEAKER_2": "да"},
        speakers_summary="s",
    )
    progress_tracker = SimpleNamespace(
        update_task=None,
        message=SimpleNamespace(),
        bot=SimpleNamespace(),
        chat_id=42,
    )
    processing_metrics = SimpleNamespace(to_dict=lambda: {})
    return request, transcription_result, progress_tracker, processing_metrics


def _patch_common(monkeypatch, call_log, previews_raises=False):
    import src.services.mapping_state_cache as msc
    import src.utils.telegram_safe as ts
    import src.ux.speaker_audio_preview as preview
    import src.ux.speaker_mapping_ui as ui

    async def fake_save_state(user_id, state_data):
        call_log.append("save_state")

    monkeypatch.setattr(msc.mapping_state_cache, "save_state", fake_save_state)

    async def fake_edit(*a, **k):
        return None

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    async def fake_previews(**kwargs):
        call_log.append("previews")
        if previews_raises:
            raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(preview, "send_speaker_audio_previews", fake_previews)

    async def fake_show(**kwargs):
        call_log.append("show")
        return SimpleNamespace()  # truthy message => пауза

    monkeypatch.setattr(ui, "show_mapping_confirmation", fake_show)


@pytest.mark.asyncio
async def test_previews_called_before_show(monkeypatch):
    call_log = []
    _patch_common(monkeypatch, call_log)

    service = _make_service()
    request, tr, pt, pm = _make_args()

    result = await service._handle_speaker_mapping_confirmation(
        request=request,
        transcription_result=tr,
        speaker_mapping={"SPEAKER_1": "Иван Иванов"},
        meeting_type="general",
        temp_file_path="temp/audio.wav",
        processing_metrics=pm,
        progress_tracker=pt,
    )

    assert result is None  # пауза
    assert "previews" in call_log and "show" in call_log
    assert call_log.index("previews") < call_log.index("show")


@pytest.mark.asyncio
async def test_preview_failure_does_not_block_show(monkeypatch):
    call_log = []
    _patch_common(monkeypatch, call_log, previews_raises=True)

    service = _make_service()
    request, tr, pt, pm = _make_args()

    result = await service._handle_speaker_mapping_confirmation(
        request=request,
        transcription_result=tr,
        speaker_mapping={},
        meeting_type="general",
        temp_file_path="temp/audio.wav",
        processing_metrics=pm,
        progress_tracker=pt,
    )

    assert result is None  # пауза всё равно наступает
    assert "show" in call_log  # UI сопоставления показан несмотря на ошибку превью
