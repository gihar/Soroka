"""Разбиение протокола на сообщения по границам секций.

Длинный протокол делится на части так, чтобы секции не рвались посередине;
при вынужденном разрыве заголовок секции повторяется с пометкой «(продолжение)».
"""

from src.services.protocol_render import render_protocol_messages


def _section(title: str, lines: int, line_text: str = "строка обсуждения") -> str:
    body = "\n".join(f"- {line_text} {i}" for i in range(lines))
    return f"## {title}\n{body}"


def test_short_protocol_is_single_message():
    md = "# Дейли\n\n## ✅ Решения\n- запускаем"
    parts = render_protocol_messages(md)
    assert parts == ["<b><u>Дейли</u></b>\n\n<b>✅ Решения</b>\n• запускаем"]


def test_parts_respect_max_length():
    md = "# Протокол\n\n" + "\n\n".join(
        _section(f"Секция {i}", 30) for i in range(10)
    )
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)


def test_split_happens_on_section_boundary():
    md = "# Протокол\n\n" + _section("✅ Решения", 20) + "\n\n" + _section("📌 Задачи", 20)
    parts = render_protocol_messages(md, max_length=600)
    # после шапки документа вторая часть начинается с заголовка секции,
    # а не с обрывка списка
    assert len(parts) == 2
    body = parts[1].split("\n\n", 1)[1]
    assert "<b>📌 Задачи</b>" in body.splitlines()[0]


def test_broken_section_repeats_heading_with_continuation():
    md = "# Протокол\n\n" + _section("💬 Обсуждение", 200)
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    continuations = [p.split("\n\n", 1)[1] for p in parts[1:]]
    assert any(
        "💬 Обсуждение (продолжение)" in body.splitlines()[0] for body in continuations
    )


def test_monster_line_is_hard_wrapped():
    md = "# Протокол\n\n## 💬 Обсуждение\n" + "х" * 5000
    parts = render_protocol_messages(md, max_length=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "х" * 100 in "".join(parts)


def test_bold_tags_balanced_in_every_part():
    md = "# Протокол\n\n" + "\n\n".join(_section(f"Секция {i}", 40) for i in range(6))
    parts = render_protocol_messages(md, max_length=800)
    for part in parts:
        assert part.count("<b>") == part.count("</b>")


# ---------------------------------------------------------------------------
# Части 2..M самодостаточны: пересланная часть несёт название встречи и дату
# ---------------------------------------------------------------------------

def _long_protocol(title_line: str, header: str = "") -> str:
    body = "\n\n".join(_section(f"Секция {i}", 30) for i in range(10))
    return f"{title_line}\n\n{header}{body}"


def test_parts_after_first_start_with_meeting_title():
    md = _long_protocol("# Планёрка продукта", "**Дата:** 20 мая\n\n")
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    for part in parts[1:]:
        lines = part.splitlines()
        assert lines[0] == "<b><u>Планёрка продукта</u></b>"
        assert lines[1] == "<b>Дата:</b> 20 мая"
    assert all(len(p) <= 1000 for p in parts)


def test_title_header_without_date_line():
    md = _long_protocol("# Планёрка продукта")
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    for part in parts[1:]:
        assert part.splitlines()[0] == "<b><u>Планёрка продукта</u></b>"


def test_title_not_duplicated_in_first_part():
    md = _long_protocol("# Планёрка продукта")
    parts = render_protocol_messages(md, max_length=1000)
    assert parts[0].count("<b><u>Планёрка продукта</u></b>") == 1


def test_protocol_without_title_splits_without_header():
    md = "\n\n".join(_section(f"Секция {i}", 30) for i in range(10))
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)


def test_overlong_title_is_truncated_in_part_header():
    md = _long_protocol("# " + "Очень длинное название встречи " * 20)
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    header_line = parts[1].splitlines()[0]
    assert len(header_line) <= 140
    assert header_line.endswith("…</u></b>")


# ---------------------------------------------------------------------------
# Резерв балансировки покрывает худший случай: перенос внутри <b><code>
# ---------------------------------------------------------------------------

def test_underline_title_stays_balanced_when_split():
    # H1-титул рендерится как <b><u>…</u></b>; вынужденный перенос длинного
    # титула не должен осиротить <u> на границе части (как и <b>).
    md = "# " + "Очень длинное название встречи " * 300 + "\n\n## 💬 Обсуждение\n- пункт"
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    for part in parts:
        assert part.count("<u>") == part.count("</u>")
        assert part.count("<b>") == part.count("</b>")


def test_nested_bold_code_wrap_stays_within_limit():
    md = "# П\n\n## 💬 Обсуждение\n**`" + "х" * 3000 + "`**"
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 2
    assert all(len(p) <= 1000 for p in parts)
    for part in parts:
        assert part.count("<b>") == part.count("</b>")
        assert part.count("<code>") == part.count("</code>")
