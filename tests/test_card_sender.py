"""Отправитель карточек: единый шов доставки интерактивных экранов (ADR-0005).

Один контракт и для первичной отправки, и для перерисовки: HTML в норме, при
неудаче — ЕДИНСТВЕННЫЙ фолбэк на plain-страховку (то же содержимое без тегов).
"""

import os
import sys
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

import src.utils.telegram_safe as ts  # noqa: E402
from src.ux.card_content import MappingCard, SpeakerRow  # noqa: E402
from src.ux.card_sender import edit_card, send_card  # noqa: E402

_CONTENT = MappingCard(
    header="Проверьте сопоставление спикеров",
    rows=(SpeakerRow(speaker_id="SPEAKER_1", display_name=None, quote="цитата"),),
)


@pytest.mark.asyncio
async def test_send_card_sends_html_when_ok(monkeypatch):
    """В норме карточка уходит одним HTML-сообщением, без страховки."""
    calls = []

    async def fake_send(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace()  # truthy Message

    monkeypatch.setattr(ts, "safe_send_message", fake_send)

    result = await send_card(bot=None, chat_id=1, content=_CONTENT, keyboard="kb")

    assert result is not None
    assert len(calls) == 1
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[0]["text"] == _CONTENT.to_html()
    assert calls[0]["reply_markup"] == "kb"


@pytest.mark.asyncio
async def test_send_card_falls_back_to_plain_on_html_failure(monkeypatch):
    """HTML не ушёл → ровно один ретрай plain-страховкой той же карточки."""
    calls = []

    async def fake_send(**kwargs):
        calls.append(kwargs)
        return None if kwargs["parse_mode"] == "HTML" else SimpleNamespace()

    monkeypatch.setattr(ts, "safe_send_message", fake_send)

    result = await send_card(bot=None, chat_id=1, content=_CONTENT)

    assert result is not None
    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[1]["parse_mode"] is None
    assert calls[1]["text"] == _CONTENT.to_plain()


@pytest.mark.asyncio
async def test_edit_card_edits_html_when_ok(monkeypatch):
    """Перерисовка в норме — один HTML-edit, без страховки."""
    calls = []

    async def fake_edit(message, text, parse_mode=None, reply_markup=None, **kw):
        calls.append((text, parse_mode))
        return SimpleNamespace()

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    result = await edit_card(message=object(), content=_CONTENT, keyboard="kb")

    assert result is not None
    assert len(calls) == 1
    assert calls[0][1] == "HTML"
    assert calls[0][0] == _CONTENT.to_html()


@pytest.mark.asyncio
async def test_edit_card_falls_back_to_plain_on_html_failure(monkeypatch):
    """Тот же единый контракт при перерисовке: HTML-фейл → один plain-ретрай."""
    calls = []

    async def fake_edit(message, text, parse_mode=None, reply_markup=None, **kw):
        calls.append((text, parse_mode))
        return None if parse_mode == "HTML" else SimpleNamespace()

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    result = await edit_card(message=object(), content=_CONTENT)

    assert result is not None
    assert len(calls) == 2
    assert calls[0][1] == "HTML"
    assert calls[1][1] is None
    assert calls[1][0] == _CONTENT.to_plain()
