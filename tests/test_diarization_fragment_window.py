"""Окно фрагмента записи как потребитель типизированной диаризации (#57 → #59).

`select_fragment_window` покрыт в test_audio_fragment_service.py на голых
сегментах — его контракт не менялся. Здесь закрепляем СТЫК потребителя с
типизированной «Диаризацией» (#59): `_prepare_clip` берёт сегменты из
`diarization.segments` (список `Segment`), отдаёт их выборщику окна и ведёт
выбранные тайминги (start, duration) в нарезчик. Без диаризации окна нет.

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
from src.models.diarization import Diarization, Segment  # noqa: E402
from src.services.audio_fragment_service import select_fragment_window  # noqa: E402


def _expected_window(diarization, speaker_id):
    """Эталонное окно теми же параметрами и сегментами, что берёт _prepare_clip."""
    segments = [s.model_dump() for s in diarization.segments]
    return select_fragment_window(
        segments,
        speaker_id,
        max_seconds=float(settings.speaker_preview_max_seconds),
        min_segment_seconds=float(settings.speaker_preview_min_segment_seconds),
    )


@pytest.mark.asyncio
async def test_prepare_clip_derives_window_from_segments(monkeypatch):
    """_prepare_clip берёт сегменты из diarization.segments и режет по ним."""
    diarization = Diarization(segments=[
        Segment(start=0.0, end=0.4, speaker="SPEAKER_1", text="да"),
        Segment(start=2.0, end=7.0, speaker="SPEAKER_1", text="длинная реплика"),
        Segment(start=8.0, end=9.0, speaker="SPEAKER_2", text="другой"),
    ])

    captured = {}

    async def fake_cut(src_path, start, duration, out_path, **kwargs):
        captured["start"] = start
        captured["duration"] = duration
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", diarization, "audio.wav", user_id=7)

    expected_start, expected_duration = _expected_window(diarization, "SPEAKER_1")
    assert captured["start"] == expected_start
    assert captured["duration"] == expected_duration
    assert out is not None


@pytest.mark.asyncio
async def test_prepare_clip_returns_none_when_speaker_absent_in_segments(monkeypatch):
    """Нет сегментов спикера → окна нет, нарезчик не зовётся, возвращается None."""
    diarization = Diarization(segments=[
        Segment(start=0.0, end=5.0, speaker="SPEAKER_2", text="..."),
    ])

    called = False

    async def fake_cut(*args, **kwargs):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", diarization, "audio.wav", user_id=7)

    assert out is None
    assert called is False


@pytest.mark.asyncio
async def test_prepare_clip_returns_none_when_diarization_absent(monkeypatch):
    """характеризация: без диаризации сегментов нет, окно не выбирается."""
    async def fake_cut(*args, **kwargs):
        return True

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)

    out = await preview._prepare_clip("SPEAKER_1", None, "audio.wav", user_id=7)

    assert out is None
