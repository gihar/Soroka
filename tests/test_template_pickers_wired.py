"""Оба пикера шаблонов подключены к общему билдеру.

Пикер перегенерации и пикер шаблона по умолчанию строят клавиатуру одним
`build_template_picker`: сетка 2 колонки. У перегенерации есть строка отмены.
"""

import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


def _tpl(tid, name):
    return SimpleNamespace(id=tid, name=name, category="general")


def _rows(markup):
    return markup.inline_keyboard


def _datas(markup):
    return {btn.callback_data for row in _rows(markup) for btn in row if btn.callback_data}


# --- Пикер перегенерации ------------------------------------------------------

def _regen_handler(name, templates):
    import src.handlers.callbacks.protocol_actions_callbacks as pac

    class FakeTemplateService:
        async def get_all_templates(self):
            return list(templates)

    router = pac.setup_protocol_actions_callbacks(
        user_service=MagicMock(), template_service=FakeTemplateService()
    )
    handler = next(
        h.callback for h in router.callback_query.handlers if h.callback.__name__ == name
    )
    return pac, handler


@pytest.mark.asyncio
async def test_regen_picker_is_two_column_grid_with_cancel(monkeypatch):
    templates = [_tpl(1, "А"), _tpl(2, "Б"), _tpl(3, "В")]
    pac, handler = _regen_handler("protocol_regen_callback", templates)

    import src.database as db_module
    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value={"transcription_text": "расшифровка"}),
    )
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    sent = {}

    async def fake_answer(text, reply_markup=None, **kwargs):
        sent["text"] = text
        sent["markup"] = reply_markup

    callback = SimpleNamespace(
        data="proto_regen_7",
        message=SimpleNamespace(answer=fake_answer, chat=SimpleNamespace(id=1)),
        from_user=SimpleNamespace(id=1),
    )
    await handler(callback)

    rows = _rows(sent["markup"])
    # 3 шаблона по 2 в ряд + строка отмены
    assert [len(r) for r in rows] == [2, 1, 1]
    assert rows[0][0].callback_data == "proto_regen_go_7_1"
    assert "proto_regen_cancel" in _datas(sent["markup"])


@pytest.mark.asyncio
async def test_regen_cancel_edits_message(monkeypatch):
    pac, handler = _regen_handler("protocol_regen_cancel_callback", [])
    edits = {}

    async def fake_edit(message, text, **kwargs):
        edits["text"] = text

    monkeypatch.setattr(pac, "safe_edit_text", fake_edit)
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    callback = SimpleNamespace(
        data="proto_regen_cancel",
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        from_user=SimpleNamespace(id=1),
    )
    await handler(callback)
    assert edits["text"] == "Перегенерация отменена."


# --- Пикер шаблона по умолчанию ----------------------------------------------

@pytest.mark.asyncio
async def test_default_template_picker_is_two_column_with_smart_and_footer(monkeypatch):
    import src.handlers.callbacks.template_mgmt_callbacks as mgmt

    templates = [_tpl(1, "А"), _tpl(2, "Б"), _tpl(3, "В")]

    class FakeTemplateService:
        async def get_all_templates(self):
            return list(templates)

    router = mgmt.setup_template_mgmt_callbacks(
        user_service=MagicMock(), template_service=FakeTemplateService(),
        processing_service=MagicMock(),
    )
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "settings_default_template_callback"
    )

    captured = {}

    async def fake_edit(message, text, reply_markup=None, **kwargs):
        captured["markup"] = reply_markup

    monkeypatch.setattr(mgmt, "safe_edit_text", fake_edit)

    callback = SimpleNamespace(
        data="settings_default_template",
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    await handler(callback)

    rows = _rows(captured["markup"])
    datas = _datas(captured["markup"])
    assert "set_default_template_0" in datas          # умный выбор
    assert {"set_default_template_1", "set_default_template_2", "set_default_template_3"} <= datas
    assert "reset_default_template" in datas          # футер
    assert "back_to_settings" in datas
    # сетка шаблонов — по 2 в ряд
    grid_rows = [r for r in rows if all(
        (b.callback_data or "").startswith("set_default_template_") and b.callback_data != "set_default_template_0"
        for b in r
    ) and r]
    assert any(len(r) == 2 for r in grid_rows)


# --- Оба используют общий билдер ---------------------------------------------

def test_both_pickers_reference_common_builder():
    import src.handlers.callbacks.protocol_actions_callbacks as pac
    import src.handlers.callbacks.template_mgmt_callbacks as mgmt

    for module in (pac, mgmt):
        assert "build_template_picker" in inspect.getsource(module)
