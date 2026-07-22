"""Меню «📤 Вывод протокола»: выбор формата доставки, включая Word (.docx)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.handlers.callbacks.settings_callbacks as sc


def _handler(name: str):
    router = sc.setup_settings_callbacks(
        user_service=MagicMock(), template_service=MagicMock(),
        processing_service=MagicMock(),
    )
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == name
    )
    return handler


def _router_with_user_service(user_service):
    return sc.setup_settings_callbacks(
        user_service=user_service, template_service=MagicMock(),
        processing_service=MagicMock(),
    )


def _menu_handler(user_service):
    router = _router_with_user_service(user_service)
    return next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "settings_protocol_output_callback"
    )


def _callback(data="settings_protocol_output"):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        answer=AsyncMock(),
    )


def _datas(markup):
    return {
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    }


def _checked_texts(markup):
    return [
        btn.text
        for row in markup.inline_keyboard
        for btn in row
        if btn.text.startswith("✅")
    ]


@pytest.mark.asyncio
async def test_menu_offers_word_option(monkeypatch):
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text
        captured["markup"] = kwargs.get("reply_markup")

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)

    user_service = SimpleNamespace(
        get_user_by_telegram_id=AsyncMock(
            return_value=SimpleNamespace(protocol_output_mode="messages")
        )
    )
    await _menu_handler(user_service)(_callback())

    datas = _datas(captured["markup"])
    assert "set_protocol_output_docx" in datas
    # Все четыре формата + возврат присутствуют.
    assert {
        "set_protocol_output_messages",
        "set_protocol_output_file",
        "set_protocol_output_pdf",
        "set_protocol_output_docx",
    } <= datas
    # Описание меню упоминает Word.
    assert "Word" in captured["text"]


@pytest.mark.asyncio
async def test_setting_docx_saves_mode(monkeypatch):
    async def fake_edit(message, text, **kwargs):
        pass

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)

    saved = {}
    user_service = SimpleNamespace(
        update_user_protocol_output_preference=AsyncMock(
            side_effect=lambda uid, mode: saved.update(uid=uid, mode=mode)
        )
    )
    router = _router_with_user_service(user_service)
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "set_protocol_output_mode_callback"
    )

    await handler(_callback("set_protocol_output_docx"))

    assert saved["mode"] == "docx"


def test_docx_callback_is_registered_in_filter_set():
    import inspect

    # Фильтр F.data.in_ должен пропускать docx, иначе кнопка мертва в проде.
    src_text = inspect.getsource(sc.setup_settings_callbacks)
    assert "set_protocol_output_docx" in src_text
    assert 'endswith(\'docx\')' in src_text or 'endswith("docx")' in src_text


@pytest.mark.asyncio
async def test_menu_checkmarks_current_docx_mode(monkeypatch):
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["markup"] = kwargs.get("reply_markup")

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)

    user_service = SimpleNamespace(
        get_user_by_telegram_id=AsyncMock(
            return_value=SimpleNamespace(protocol_output_mode="docx")
        )
    )
    await _menu_handler(user_service)(_callback())

    checked = _checked_texts(captured["markup"])
    assert len(checked) == 1
    assert "Word" in checked[0]
