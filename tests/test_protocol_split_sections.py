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
    assert parts == ["<b>Дейли</b>\n\n<b>✅ Решения</b>\n• запускаем"]


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
    # вторая часть начинается с заголовка секции, а не с обрывка списка
    assert len(parts) == 2
    assert "<b>📌 Задачи</b>" in parts[1].splitlines()[0]


def test_broken_section_repeats_heading_with_continuation():
    md = "# Протокол\n\n" + _section("💬 Обсуждение", 200)
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    assert any("💬 Обсуждение (продолжение)" in p.splitlines()[0] for p in parts[1:])


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
