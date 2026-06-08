"""Тест безопасной отправки голосового сообщения."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_safe_send_voice_calls_rate_limited_send(monkeypatch):
    import src.utils.telegram_safe as ts

    calls = {}

    async def fake_safe_send_with_retry(method, **kwargs):
        calls["method"] = method
        calls["kwargs"] = kwargs
        return "SENT"

    monkeypatch.setattr(
        ts.telegram_rate_limiter, "safe_send_with_retry", fake_safe_send_with_retry
    )

    class FakeBot:
        async def send_voice(self, **kwargs):
            return None

    bot = FakeBot()
    result = await ts.safe_send_voice(
        bot, chat_id=123, voice="path/clip.ogg", caption="🔊 SPEAKER_1"
    )

    assert result == "SENT"
    assert calls["method"] == bot.send_voice
    assert calls["kwargs"]["chat_id"] == 123
    assert calls["kwargs"]["voice"] == "path/clip.ogg"
    assert calls["kwargs"]["caption"] == "🔊 SPEAKER_1"


@pytest.mark.asyncio
async def test_safe_send_voice_swallows_exceptions(monkeypatch):
    import src.utils.telegram_safe as ts

    async def boom(method, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(ts.telegram_rate_limiter, "safe_send_with_retry", boom)

    class FakeBot:
        async def send_voice(self, **kwargs):
            return None

    result = await ts.safe_send_voice(FakeBot(), chat_id=1, voice="x.ogg")
    assert result is None


@pytest.mark.asyncio
async def test_safe_send_audio_calls_rate_limited_send(monkeypatch):
    import src.utils.telegram_safe as ts

    calls = {}

    async def fake_safe_send_with_retry(method, **kwargs):
        calls["method"] = method
        calls["kwargs"] = kwargs
        return "SENT"

    monkeypatch.setattr(
        ts.telegram_rate_limiter, "safe_send_with_retry", fake_safe_send_with_retry
    )

    class FakeBot:
        async def send_audio(self, **kwargs):
            return None

    bot = FakeBot()
    result = await ts.safe_send_audio(
        bot, chat_id=123, audio="path/clip.ogg", caption="🔊 SPEAKER_1"
    )

    assert result == "SENT"
    assert calls["method"] == bot.send_audio
    assert calls["kwargs"]["chat_id"] == 123
    assert calls["kwargs"]["audio"] == "path/clip.ogg"
    assert calls["kwargs"]["caption"] == "🔊 SPEAKER_1"


@pytest.mark.asyncio
async def test_safe_send_audio_swallows_exceptions(monkeypatch):
    import src.utils.telegram_safe as ts

    async def boom(method, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(ts.telegram_rate_limiter, "safe_send_with_retry", boom)

    class FakeBot:
        async def send_audio(self, **kwargs):
            return None

    result = await ts.safe_send_audio(FakeBot(), chat_id=1, audio="x.ogg")
    assert result is None
