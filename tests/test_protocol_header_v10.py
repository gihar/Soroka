"""Критика v10: дата и название протокола — правда, а не молчаливая подстановка.

Прод-факт, зафиксированный самим кодом (`with_protocol_date_fallback`): «LLM
почти никогда не извлекает дату из аудио», поэтому фолбэк на момент обработки —
штатный путь, а не край. Встреча в понедельник, обработанная в четверг, уходила
«наверх» документом от четверга, и получатель этого не видел.

Три шва здесь:
1. ``protocol_date_source`` — откуда пришла дата (llm / request / processing).
   Чистая функция, вызывается ДО фолбэка, поэтому ничего не ломает в v6.
2. ``rewrite_protocol_header`` — переписать шапку готового текста, не трогая тело
   (перегенерация не нужна: дата и титул живут в двух строках).
3. ``parse_header_input`` — разбор пользовательского ввода «дата / название».
"""

from datetime import datetime

import pytest

from src.services.processing.llm_generation import protocol_date_source
from src.services.protocol_header import (
    parse_header_input,
    rewrite_protocol_header,
)

_MOMENT = datetime(2026, 7, 30)


# ---------------------------------------------------------------------------
# 1. Источник даты: различить «знаем» и «подставили»
# ---------------------------------------------------------------------------


def test_llm_date_is_reported_as_llm_source():
    assert protocol_date_source({"date": "20 октября 2024"}, meeting_date=None) == "llm"


def test_request_date_is_reported_as_request_source():
    assert protocol_date_source({"date": ""}, meeting_date="15 июля 2026") == "request"


def test_no_source_is_reported_as_processing():
    assert protocol_date_source({"date": ""}, meeting_date=None) == "processing"


def test_missing_date_key_is_processing_source():
    assert protocol_date_source({}, meeting_date=None) == "processing"


def test_whitespace_date_is_not_a_source():
    assert protocol_date_source({"date": "   "}, meeting_date="  ") == "processing"


def test_llm_date_wins_over_request_date():
    """Порядок совпадает с with_protocol_date_fallback — иначе метка соврёт."""
    assert (
        protocol_date_source({"date": "20 октября 2024"}, meeting_date="15 июля 2026")
        == "llm"
    )


# ---------------------------------------------------------------------------
# 2. Переписывание шапки готового протокола
# ---------------------------------------------------------------------------

_PROTOCOL = (
    "# Встреча 30 июля\n"
    "**Дата:** 30 июля 2026\n"
    "**👥 Участники:**\n"
    "Иван, Мария\n"
    "\n"
    "## ✅ Решения\n"
    "Запускаем.\n"
)


def test_rewrite_replaces_date_only():
    out = rewrite_protocol_header(_PROTOCOL, date="27 июля 2026", title=None)
    assert "**Дата:** 27 июля 2026" in out
    assert "30 июля 2026" not in out
    # Титул и тело не тронуты.
    assert out.startswith("# Встреча 30 июля\n")
    assert "## ✅ Решения\nЗапускаем." in out


def test_rewrite_replaces_title_only():
    out = rewrite_protocol_header(_PROTOCOL, date=None, title="Планёрка по смете")
    assert out.startswith("# Планёрка по смете\n")
    assert "**Дата:** 30 июля 2026" in out


def test_rewrite_replaces_both():
    out = rewrite_protocol_header(
        _PROTOCOL, date="27 июля 2026", title="Планёрка по смете"
    )
    assert out.startswith("# Планёрка по смете\n")
    assert "**Дата:** 27 июля 2026" in out


def test_rewrite_preserves_time_suffix():
    """Шапка брифа — «**Дата:** X · HH:MM»: время принадлежит записи, не правке."""
    text = "# Встреча\n**Дата:** 30 июля 2026 · 14:00\n\n## ✅ Решения\nОк.\n"
    out = rewrite_protocol_header(text, date="27 июля 2026", title=None)
    assert "**Дата:** 27 июля 2026 · 14:00" in out


def test_rewrite_preserves_legacy_time_suffix():
    """Фолбэк-форматтер даёт «**Дата:** X | **Время:** Y» — тоже сохраняем."""
    text = "# Встреча\n**Дата:** 30 июля 2026 | **Время:** 14:00\n\n## ✅ Решения\nОк.\n"
    out = rewrite_protocol_header(text, date="27 июля 2026", title=None)
    assert "**Дата:** 27 июля 2026 | **Время:** 14:00" in out


def test_rewrite_inserts_date_line_when_absent():
    """Протокол без даты (шапка спрятала пустое поле) должен её получить."""
    text = "# Встреча\n**👥 Участники:**\nИван\n\n## ✅ Решения\nОк.\n"
    out = rewrite_protocol_header(text, date="27 июля 2026", title=None)
    lines = out.splitlines()
    assert lines[0] == "# Встреча"
    assert lines[1] == "**Дата:** 27 июля 2026"
    assert "**👥 Участники:**" in out


def test_rewrite_inserts_title_when_absent():
    text = "**Дата:** 30 июля 2026\n\n## ✅ Решения\nОк.\n"
    out = rewrite_protocol_header(text, date=None, title="Планёрка")
    assert out.splitlines()[0] == "# Планёрка"


def test_rewrite_without_values_returns_input_unchanged():
    assert rewrite_protocol_header(_PROTOCOL, date=None, title=None) == _PROTOCOL


def test_rewrite_does_not_mutate_input():
    original = _PROTOCOL
    rewrite_protocol_header(original, date="27 июля 2026", title="Другое")
    assert original == _PROTOCOL


def test_rewrite_touches_only_the_first_heading():
    """«# » внутри тела (цитата, код) не должен считаться титулом."""
    text = "# Встреча\n**Дата:** 30 июля 2026\n\n## ✅ Решения\n# не заголовок\n"
    out = rewrite_protocol_header(text, date=None, title="Планёрка")
    assert out.startswith("# Планёрка\n")
    assert "# не заголовок" in out


def test_rewrite_ignores_date_line_inside_body():
    """Вторая «**Дата:**» в теле — не шапка; правим только первую."""
    text = (
        "# Встреча\n**Дата:** 30 июля 2026\n\n"
        "## ✅ Решения\n**Дата:** дедлайна — 5 августа\n"
    )
    out = rewrite_protocol_header(text, date="27 июля 2026", title=None)
    assert "**Дата:** 27 июля 2026" in out
    assert "**Дата:** дедлайна — 5 августа" in out


# ---------------------------------------------------------------------------
# 3. Разбор пользовательского ввода
# ---------------------------------------------------------------------------


def test_parse_single_line_is_date():
    assert parse_header_input("27 июля 2026") == ("27 июля 2026", None)


def test_parse_second_line_is_title():
    assert parse_header_input("27 июля 2026\nПланёрка по смете") == (
        "27 июля 2026",
        "Планёрка по смете",
    )


def test_parse_strips_blank_lines_and_spaces():
    assert parse_header_input("  27 июля 2026  \n\n  Планёрка  \n") == (
        "27 июля 2026",
        "Планёрка",
    )


def test_parse_extra_lines_join_into_title():
    """Название из двух строк не должно молча потеряться."""
    assert parse_header_input("27 июля\nПланёрка\nпо смете") == (
        "27 июля",
        "Планёрка по смете",
    )


def test_parse_empty_input_is_rejected():
    assert parse_header_input("   \n  ") == (None, None)


@pytest.mark.parametrize("raw", ["27.07.2026", "27/07/2026", "27-07-2026"])
def test_parse_normalizes_numeric_date_to_russian(raw):
    """«27.07.2026» в шапке рядом с «30 июля 2026» — разнобой; приводим к одному виду."""
    assert parse_header_input(raw) == ("27 июля 2026", None)


def test_parse_keeps_unrecognized_date_as_typed():
    """Не распознали — не выдумываем: пользователь виднее."""
    assert parse_header_input("прошлый вторник") == ("прошлый вторник", None)


def test_parse_rejects_overlong_values():
    """Шапка — не поле для абзаца: длинный ввод отсекаем, а не рвём вёрстку."""
    date, title = parse_header_input("27 июля 2026\n" + "я" * 300)
    assert date == "27 июля 2026"
    assert len(title) <= 120
