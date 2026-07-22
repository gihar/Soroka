"""Доставка протокола в чат: HTML parse_mode вместо legacy Markdown."""

from unittest.mock import AsyncMock

import pytest

from src.services import result_sender


@pytest.mark.asyncio
async def test_messages_mode_sends_html(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()  # успешная отправка

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    await result_sender._send_protocol_as_messages(
        AsyncMock(), 1, "# Дейли\n\n## ✅ Решения\n- запускаем"
    )

    assert len(sent) == 1
    assert sent[0]["parse_mode"] == "HTML"
    assert sent[0]["text"] == "<b><u>Дейли</u></b>\n\n<b>✅ Решения</b>\n• запускаем"


@pytest.mark.asyncio
async def test_long_protocol_split_into_html_parts(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    body = "\n".join(f"- пункт номер {i} с достаточно длинным текстом" for i in range(300))
    protocol = f"# Протокол\n\n## 💬 Обсуждение\n{body}"

    await result_sender._send_protocol_as_messages(AsyncMock(), 1, protocol)

    assert len(sent) > 1
    for kwargs in sent:
        assert kwargs["parse_mode"] == "HTML"
        assert len(kwargs["text"]) <= result_sender.MAX_MESSAGE_LENGTH
    # разорванная секция продолжается со своим заголовком
    assert any("(продолжение)" in kwargs["text"] for kwargs in sent[1:])
