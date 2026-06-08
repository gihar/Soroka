"""Тесты оркестратора аудиопревью спикеров."""

import os
import sys

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from config import ...` and `from services import ...` used inside
# legacy modules that are transitively imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))

import src.ux.speaker_audio_preview as preview  # noqa: E402


def _diarization():
    return {
        "speakers": ["SPEAKER_1", "SPEAKER_2"],
        "segments": [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "привет всем"},
            {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "да, начнём"},
        ],
    }


@pytest.mark.asyncio
async def test_no_temp_file_sends_nothing(monkeypatch):
    sent = []

    async def fake_send_voice(*a, **k):
        sent.append(k)
        return "MSG"

    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=None,
        speakers_text={},
    )
    assert sent == []


@pytest.mark.asyncio
async def test_sends_one_voice_per_speaker_in_order(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent_order = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        # имитируем успешную нарезку — создаём непустой файл
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        sent_order.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={"SPEAKER_1": "привет всем", "SPEAKER_2": "да, начнём"},
    )

    assert len(sent_order) == 2
    assert "SPEAKER_1" in sent_order[0]
    assert "SPEAKER_2" in sent_order[1]


@pytest.mark.asyncio
async def test_one_speaker_cut_failure_does_not_block_others(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        # SPEAKER_1 (start=0.0) падает, SPEAKER_2 (start=6.0) успешен
        if start == 0.0:
            return False
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        sent.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert len(sent) == 1
    assert "SPEAKER_2" in sent[0]


@pytest.mark.asyncio
async def test_temp_clips_are_deleted(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    created_paths = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        created_paths.append(out_path)
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)
    # Пишем клипы во временную папку теста, а не в ./temp
    monkeypatch.setattr(preview, "_preview_dir", lambda: str(tmp_path))

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert created_paths, "клип должен был создаться"
    for p in created_paths:
        assert not os.path.exists(p), f"временный клип не удалён: {p}"


@pytest.mark.asyncio
async def test_disabled_by_config_sends_nothing(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent = []

    async def fake_send_voice(*a, **k):
        sent.append(k)
        return "MSG"

    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)
    monkeypatch.setattr(preview.settings, "speaker_audio_preview_enabled", False)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )
    assert sent == []
