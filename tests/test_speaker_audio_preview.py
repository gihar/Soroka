"""Тесты оркестратора аудиопревью спикеров."""

import os
import sys

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from src.config import ...` and `from services import ...` used inside
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


@pytest.mark.asyncio
async def test_falls_back_to_audio_when_voice_fails(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    voice_calls = []
    audio_calls = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_voice(bot, chat_id, voice, caption=None, **k):
        voice_calls.append(caption)
        return None  # голосовые запрещены / не ушли

    async def fake_audio(bot, chat_id, audio, caption=None, **k):
        audio_calls.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_voice)
    monkeypatch.setattr(preview, "safe_send_audio", fake_audio)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={"SPEAKER_1": "привет всем"},
    )

    assert len(voice_calls) == 1  # голосовое пробуем первым
    assert len(audio_calls) == 1  # и падаем в фолбэк на аудиофайл
    assert "SPEAKER_1" in audio_calls[0]


@pytest.mark.asyncio
async def test_no_audio_fallback_when_voice_succeeds(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    audio_calls = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_voice(bot, chat_id, voice, caption=None, **k):
        return "MSG"

    async def fake_audio(bot, chat_id, audio, caption=None, **k):
        audio_calls.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_voice)
    monkeypatch.setattr(preview, "safe_send_audio", fake_audio)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert audio_calls == []  # голосовое ушло — фолбэк не нужен


@pytest.mark.asyncio
async def test_returns_delivered_speakers(monkeypatch, tmp_path):
    """Возвращается множество спикеров, чьи фрагменты реально доставлены."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    async def fake_cut(src_path, start, duration, out_path, **k):
        # SPEAKER_1 (start=0.0) не нарезается, SPEAKER_2 (start=6.0) успешен
        if start == 0.0:
            return False
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    delivered = await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert delivered == {"SPEAKER_2"}


@pytest.mark.asyncio
async def test_returns_empty_set_when_disabled_or_no_file(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    monkeypatch.setattr(preview.settings, "speaker_audio_preview_enabled", False)
    delivered_disabled = await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    monkeypatch.setattr(preview.settings, "speaker_audio_preview_enabled", True)
    delivered_no_file = await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=None,
        speakers_text={},
    )

    assert delivered_disabled == set()
    assert delivered_no_file == set()


@pytest.mark.asyncio
async def test_audio_fallback_counts_as_delivered(monkeypatch, tmp_path):
    """Фоллбек «голосовое → аудиофайл» — это доставка."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    async def fake_cut(src_path, start, duration, out_path, **k):
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_voice(bot, chat_id, voice, caption=None, **k):
        return None  # голосовые запрещены

    async def fake_audio(bot, chat_id, audio, caption=None, **k):
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_voice)
    monkeypatch.setattr(preview, "safe_send_audio", fake_audio)

    delivered = await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert delivered == {"SPEAKER_1"}


@pytest.mark.asyncio
async def test_send_failure_means_not_delivered(monkeypatch, tmp_path):
    """Ни голосовое, ни аудиофайл не ушли → спикер не считается доставленным."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    async def fake_cut(src_path, start, duration, out_path, **k):
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_none(bot, chat_id, caption=None, **k):
        return None

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_none)
    monkeypatch.setattr(preview, "safe_send_audio", fake_send_none)

    delivered = await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert delivered == set()


@pytest.mark.asyncio
async def test_caption_snippet_up_to_200_chars(monkeypatch, tmp_path):
    """Подпись фрагмента — единственная цитата спикера, лимит 200 символов."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    captions = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        captions.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    long_text = "а" * 300
    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={"SPEAKER_1": long_text},
    )

    assert len(captions) == 1
    assert "а" * 200 in captions[0]
    assert "а" * 201 not in captions[0]
    assert "…" in captions[0]


