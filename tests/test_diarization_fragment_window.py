"""Характеризация окна фрагмента записи как потребителя диаризации (#57).

`select_fragment_window` уже покрыт в test_audio_fragment_service.py. Здесь
закрепляем СВЯЗКУ потребителя с формой диаризации: `_prepare_clip` достаёт
сегменты именно из ключа `diarization_data["segments"]` и передаёт выбранные
тайминги (start, duration) в нарезчик. Это тот стык, который затронет типизация
«Диаризации» (#58): сегменты должны остаться доступны потребителю аудиопревью.

Нарезка (ffmpeg) замокана — тест офлайновый и быстрый.
"""

import os
import sys

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Bare `from services import ...` внутри модулей, транзитивно тянущихся через src/ux.
sys.path.insert(0, os.path.join(_root, "src"))

import src.ux.speaker_audio_preview as preview  # noqa: E402
from src.config import settings  # noqa: E402
from src.services.audio_fragment_service import select_fragment_window  # noqa: E402


def _expected_window(segments, speaker_id):
    """Эталонное окно теми же параметрами, что берёт _prepare_clip из настроек."""
    return select_fragment_window(
        segments,
        speaker_id,
        max_seconds=float(settings.speaker_preview_max_seconds),
        min_segment_seconds=float(settings.speaker_preview_min_segment_seconds),
    )


@pytest.mark.asyncio
async def test_prepare_clip_derives_window_from_segments(monkeypatch):
    """_prepare_clip берёт сегменты из diarization_data['segments'] и режет по ним."""
    segments = [
        {"start": 0.0, "end": 0.4, "speaker": "SPEAKER_1", "text": "да"},
        {"start": 2.0, "end": 7.0, "speaker": "SPEAKER_1", "text": "длинная реплика"},
        {"start": 8.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "другой"},
    ]
    diarization_data = {"speakers": ["SPEAKER_1", "SPEAKER_2"], "segments": segments}

    captured = {}

    async def fake_cut(src_path, start, duration, out_path, **kwargs):
        captured["start"] = start
        captured["duration"] = duration
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", diarization_data, "audio.wav", user_id=7)

    expected_start, expected_duration = _expected_window(segments, "SPEAKER_1")
    assert captured["start"] == expected_start
    assert captured["duration"] == expected_duration
    assert out is not None


@pytest.mark.asyncio
async def test_prepare_clip_returns_none_when_speaker_absent_in_segments(monkeypatch):
    """Нет сегментов спикера → окна нет, нарезчик не зовётся, возвращается None."""
    diarization_data = {
        "speakers": ["SPEAKER_2"],
        "segments": [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_2", "text": "..."}],
    }

    called = False

    async def fake_cut(*args, **kwargs):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", diarization_data, "audio.wav", user_id=7)

    assert out is None
    assert called is False


@pytest.mark.asyncio
async def test_prepare_clip_returns_none_when_segments_key_missing(monkeypatch):
    """характеризация: сегменты читаются только из ключа 'segments' (иначе — пусто)."""
    diarization_data = {"speakers": ["SPEAKER_1"]}  # без ключа 'segments'

    async def fake_cut(*args, **kwargs):
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", diarization_data, "audio.wav", user_id=7)

    assert out is None
