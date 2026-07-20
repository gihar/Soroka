"""Общий билдер пикера шаблонов: одна сетка 2 колонки для всех точек выбора.

Раньше пикер перегенерации был плоским списком в 1 колонку без отмены, а
пикер шаблона по умолчанию — сеткой 2 колонки. Теперь оба строятся одним
билдером `build_template_picker`.
"""

from types import SimpleNamespace

from src.ux.keyboards import build_template_picker


def _tpl(tid, name):
    return SimpleNamespace(id=tid, name=name)


def _rows(markup):
    return markup.inline_keyboard


def test_grid_is_two_columns():
    templates = [_tpl(1, "А"), _tpl(2, "Б"), _tpl(3, "В")]
    markup = build_template_picker(templates, lambda t: f"pick_{t.id}")
    rows = _rows(markup)
    assert [len(r) for r in rows] == [2, 1]  # 3 шаблона → ряды по 2


def test_callback_data_built_by_factory():
    templates = [_tpl(7, "Дейли")]
    markup = build_template_picker(templates, lambda t: f"proto_regen_go_99_{t.id}")
    assert _rows(markup)[0][0].callback_data == "proto_regen_go_99_7"


def test_templates_sorted_by_name():
    templates = [_tpl(1, "Ретро"), _tpl(2, "Дейли")]
    markup = build_template_picker(templates, lambda t: str(t.id))
    texts = [btn.text for row in _rows(markup) for btn in row]
    assert texts == ["Дейли", "Ретро"]


def test_cancel_row_appended_last():
    templates = [_tpl(1, "А")]
    markup = build_template_picker(
        templates, lambda t: str(t.id), cancel_callback="proto_regen_cancel"
    )
    last_row = _rows(markup)[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "proto_regen_cancel"


def test_no_cancel_row_when_not_requested():
    templates = [_tpl(1, "А")]
    markup = build_template_picker(templates, lambda t: str(t.id))
    datas = {btn.callback_data for row in _rows(markup) for btn in row}
    assert datas == {"1"}


def test_top_and_bottom_rows_wrap_the_grid():
    from aiogram.types import InlineKeyboardButton

    top = [[InlineKeyboardButton(text="🤖 Умный выбор", callback_data="set_default_template_0")]]
    bottom = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_settings")]]
    templates = [_tpl(5, "Дейли")]
    markup = build_template_picker(
        templates, lambda t: f"set_default_template_{t.id}",
        top_rows=top, bottom_rows=bottom,
    )
    rows = _rows(markup)
    assert rows[0][0].callback_data == "set_default_template_0"  # умный выбор сверху
    assert rows[1][0].callback_data == "set_default_template_5"  # сетка
    assert rows[-1][0].callback_data == "back_to_settings"       # назад снизу
