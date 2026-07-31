"""Шапка готового протокола: правка титула и даты без перегенерации.

Дата и название живут в двух первых строках рендера («# Титул» и «**Дата:** …»),
поэтому поправить их можно прямо в тексте — LLM и расшифровка для этого не
нужны. Это дешевле перегенерации и, в отличие от неё, не может переписать тело
протокола, которое пользователь уже прочитал.

Все функции чистые и возвращают новые значения (входной текст не мутируется).
"""

import re
from typing import Optional, Tuple

from src.utils.date_format import normalize_russian_date

# Строка даты в шапке: «**Дата:** 30 июля 2026», возможно с хвостом
# « · 14:00» (бриф) или « | **Время:** 14:00» (фолбэк-форматтер). Хвост
# принадлежит записи, а не правке, поэтому сохраняется как есть.
_DATE_LINE = re.compile(r"^\*\*Дата:\*\*\s*(?P<value>.*)$")
_DATE_TAIL = re.compile(r"\s+(?:·|\|)\s.*$")

# Титул — первый заголовок первого уровня. «# » внутри тела (цитата, пример)
# титулом не считается.
_TITLE_LINE = re.compile(r"^#\s+(?P<value>.*)$")

_MAX_DATE_LEN = 60
_MAX_TITLE_LEN = 120


def rewrite_protocol_header(
    protocol_text: str,
    *,
    date: Optional[str],
    title: Optional[str],
) -> str:
    """Вернуть протокол с новой датой и/или названием в шапке.

    ``None`` означает «не трогать это поле». Отсутствующая строка даты
    вставляется сразу под титулом (шапка прячет пустое поле, но после правки
    дате есть чем быть), отсутствующий титул — первой строкой.
    """
    if not date and not title:
        return protocol_text

    lines = protocol_text.splitlines()
    lines = _apply_title(lines, title) if title else lines
    lines = _apply_date(lines, date) if date else lines

    rewritten = "\n".join(lines)
    # splitlines() съедает финальный перевод строки — возвращаем его, чтобы
    # правка шапки не меняла хвост документа.
    if protocol_text.endswith("\n") and not rewritten.endswith("\n"):
        rewritten += "\n"
    return rewritten


def _apply_title(lines: list[str], title: str) -> list[str]:
    """Заменить первый «# …» или вставить титул первой строкой."""
    for index, line in enumerate(lines):
        if _TITLE_LINE.match(line.strip()):
            return [*lines[:index], f"# {title}", *lines[index + 1 :]]
    return [f"# {title}", *lines]


def _apply_date(lines: list[str], date: str) -> list[str]:
    """Заменить первую «**Дата:** …» (сохранив хвост времени) или вставить её."""
    for index, line in enumerate(lines):
        match = _DATE_LINE.match(line.strip())
        if match:
            tail = _DATE_TAIL.search(match.group("value"))
            suffix = tail.group(0) if tail else ""
            return [*lines[:index], f"**Дата:** {date}{suffix}", *lines[index + 1 :]]

    # Строки даты нет — ставим сразу под титулом, где её ждёт и рендер, и
    # сплиттер многочастного протокола (он тянет в шапку части именно эти две
    # строки).
    for index, line in enumerate(lines):
        if _TITLE_LINE.match(line.strip()):
            return [*lines[: index + 1], f"**Дата:** {date}", *lines[index + 1 :]]
    return [f"**Дата:** {date}", *lines]


def parse_header_input(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """Разобрать ввод «дата, затем название» в пару значений.

    Первая непустая строка — дата, всё остальное — название (склеивается в одну
    строку: название из двух строк не должно молча потеряться). Пустой ввод даёт
    ``(None, None)`` — вызывающий отвечает за подсказку.
    """
    lines = [line.strip() for line in (raw or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None, None

    date = normalize_russian_date(lines[0])[:_MAX_DATE_LEN].strip()
    title = " ".join(lines[1:]).strip()[:_MAX_TITLE_LEN].strip() or None
    return date or None, title
