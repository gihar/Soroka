"""Тесты выбора окна и нарезки аудиофрагмента спикера."""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.audio_fragment_service import select_fragment_window


def _seg(start, end, speaker, text=""):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


def test_picks_first_weighty_segment_start():
    segments = [
        _seg(0.0, 0.5, "SPEAKER_1", "да"),          # короткий, пропускаем
        _seg(2.0, 7.0, "SPEAKER_1", "длинная фраза"),  # первый весомый
        _seg(10.0, 12.0, "SPEAKER_2", "другой"),
    ]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=15.0, min_segment_seconds=1.5)
    assert window == (2.0, 15.0)


def test_fallback_to_first_segment_when_all_short():
    segments = [
        _seg(3.0, 3.4, "SPEAKER_1", "ага"),
        _seg(5.0, 5.3, "SPEAKER_1", "да"),
    ]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=15.0, min_segment_seconds=1.5)
    assert window == (3.0, 15.0)


def test_duration_is_capped_at_max_seconds():
    segments = [_seg(1.0, 999.0, "SPEAKER_1", "очень длинный монолог")]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=10.0, min_segment_seconds=1.5)
    assert window == (1.0, 10.0)


def test_no_segments_for_speaker_returns_none():
    segments = [_seg(0.0, 5.0, "SPEAKER_2", "только второй")]
    assert select_fragment_window(segments, "SPEAKER_1") is None


def test_empty_segments_returns_none():
    assert select_fragment_window([], "SPEAKER_1") is None


def test_invalid_timestamps_return_none():
    segments = [
        {"start": None, "end": None, "speaker": "SPEAKER_1", "text": "битый"},
        {"speaker": "SPEAKER_1", "text": "без таймстампов"},
    ]
    assert select_fragment_window(segments, "SPEAKER_1") is None


def test_input_segments_not_mutated():
    segments = [_seg(2.0, 7.0, "SPEAKER_1"), _seg(0.0, 0.5, "SPEAKER_1")]
    snapshot = [dict(s) for s in segments]
    select_fragment_window(segments, "SPEAKER_1")
    assert segments == snapshot


def _ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe не установлены в окружении",
)
async def test_cut_voice_fragment_produces_valid_ogg(tmp_path):
    from src.services.audio_fragment_service import cut_voice_fragment

    # Сгенерировать 20-секундный тон как исходник
    src = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-y", str(src)],
        capture_output=True, text=True, check=True,
    )

    out = tmp_path / "clip.ogg"
    ok = await cut_voice_fragment(str(src), start=5.0, duration=8.0, out_path=str(out))

    assert ok is True
    assert out.exists() and out.stat().st_size > 0
    # Длительность близка к запрошенным 8 с
    assert abs(_ffprobe_duration(str(out)) - 8.0) < 1.0


@pytest.mark.asyncio
async def test_cut_voice_fragment_missing_source_returns_false(tmp_path):
    from src.services.audio_fragment_service import cut_voice_fragment

    out = tmp_path / "clip.ogg"
    ok = await cut_voice_fragment(str(tmp_path / "nope.wav"), start=0.0, duration=5.0, out_path=str(out))
    assert ok is False
    assert not out.exists()
