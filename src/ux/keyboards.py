"""Общие билдеры клавиатур UX.

Единая точка правды для повторяющихся раскладок инлайн-кнопок, чтобы вид
не расходился между разными точками входа.
"""

from typing import Callable, List, Optional, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.utils.template_sort import sort_templates_by_name

_Row = List[InlineKeyboardButton]


def build_template_picker(
    templates: Sequence,
    callback_data: Callable[[object], str],
    *,
    top_rows: Optional[List[_Row]] = None,
    bottom_rows: Optional[List[_Row]] = None,
    cancel_callback: Optional[str] = None,
    cancel_text: str = "✖️ Отмена",
) -> InlineKeyboardMarkup:
    """Сетка выбора шаблона в 2 колонки — единый вид для всех пикеров.

    Шаблоны сортируются по имени; ``callback_data`` строится фабрикой по шаблону.
    ``top_rows``/``bottom_rows`` композируются вокруг сетки (умный выбор, «Назад»),
    а ``cancel_callback`` добавляет отдельную строку отмены в самый низ.
    """
    rows: List[_Row] = list(top_rows or [])

    grid_row: _Row = []
    for template in sort_templates_by_name(templates):
        grid_row.append(InlineKeyboardButton(
            text=template.name,
            callback_data=callback_data(template),
        ))
        if len(grid_row) == 2:
            rows.append(grid_row)
            grid_row = []
    if grid_row:
        rows.append(grid_row)

    rows.extend(bottom_rows or [])

    if cancel_callback:
        rows.append([InlineKeyboardButton(text=cancel_text, callback_data=cancel_callback)])

    return InlineKeyboardMarkup(inline_keyboard=rows)
