"""Тихий тон подтверждений шаблона по умолчанию.

Вместо стен текста с 🤖📊💡 и «рекомендуемый режим для большинства» —
1-2 строки статуса: что установлено/сброшено и что это значит.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

_FORBIDDEN = ["🤖", "📊", "💡"]


def _mgmt_handler(name, template_service):
    import src.handlers.callbacks.template_mgmt_callbacks as mgmt

    router = mgmt.setup_template_mgmt_callbacks(
        user_service=MagicMock(), template_service=template_service,
        processing_service=MagicMock(),
    )
    handler = next(
        h.callback for h in router.callback_query.handlers if h.callback.__name__ == name
    )
    return mgmt, handler


def _callback(data):
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )


async def _capture_edit(monkeypatch, mgmt):
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text

    monkeypatch.setattr(mgmt, "safe_edit_text", fake_edit)
    return captured


def _assert_quiet(text):
    assert len(text) < 200, f"стена текста ({len(text)}): {text!r}"
    for ch in _FORBIDDEN:
        assert ch not in text, f"украшательство {ch} в {text!r}"
    assert "рекомендуем" not in text.lower()


@pytest.mark.asyncio
async def test_smart_default_status_is_quiet(monkeypatch):
    class TS:
        async def set_user_default_template(self, uid, tid):
            return True

    mgmt, handler = _mgmt_handler("set_default_template_callback", TS())
    captured = await _capture_edit(monkeypatch, mgmt)
    await handler(_callback("set_default_template_0"))
    _assert_quiet(captured["text"])


@pytest.mark.asyncio
async def test_specific_default_status_is_quiet(monkeypatch):
    class TS:
        async def set_user_default_template(self, uid, tid):
            return True

        async def get_template_by_id(self, tid):
            return SimpleNamespace(name="Дейли")

    mgmt, handler = _mgmt_handler("set_default_template_callback", TS())
    captured = await _capture_edit(monkeypatch, mgmt)
    await handler(_callback("set_default_template_5"))
    _assert_quiet(captured["text"])
    assert "Дейли" in captured["text"]  # статус называет установленный шаблон


@pytest.mark.asyncio
async def test_reset_default_status_is_quiet(monkeypatch):
    class TS:
        async def reset_user_default_template(self, uid):
            return True

    mgmt, handler = _mgmt_handler("reset_default_template_callback", TS())
    captured = await _capture_edit(monkeypatch, mgmt)
    await handler(_callback("reset_default_template"))
    _assert_quiet(captured["text"])
