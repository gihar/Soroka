"""Рендер канонического Markdown протокола в Telegram HTML.

Telegram parse_mode="Markdown" (legacy) не поддерживает #-заголовки и **жирный**,
поэтому в чат протокол уходит как HTML: заголовки -> <b>, **x** -> <b>x</b>,
`x` -> <code>x</code>, спецсимволы экранируются.
"""

from src.services.protocol_render.telegram_html import markdown_to_telegram_html


def test_h1_heading_becomes_bold_underlined_title():
    assert markdown_to_telegram_html("# Дейли") == "<b><u>Дейли</u></b>"


def test_h2_heading_becomes_bold_line():
    assert markdown_to_telegram_html("## ✅ Решения") == "<b>✅ Решения</b>"


def test_h1_title_stronger_than_h2_sections():
    """Титул (H1) — жирный + подчёркивание, секции (H2) — только жирный.

    В Telegram нет размеров шрифта; эмодзи-якоря делают секции заметными, и
    без различения титул визуально слабее секций. Подчёркивание — сдержанный
    «титульный» приём (спокойные заголовки), а не украшение.
    """
    title = markdown_to_telegram_html("# Планёрка команды")
    section = markdown_to_telegram_html("## ✅ Решения")
    assert title == "<b><u>Планёрка команды</u></b>"
    assert "<u>" not in section


def test_h3_heading_becomes_bold_line():
    assert markdown_to_telegram_html("### Детали") == "<b>Детали</b>"


def test_double_asterisk_bold_converted():
    assert markdown_to_telegram_html("**Дата:** 20 мая") == "<b>Дата:</b> 20 мая"


def test_html_special_chars_escaped():
    assert markdown_to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_unpaired_double_asterisk_stays_literal():
    assert markdown_to_telegram_html("вес **не указан") == "вес **не указан"


def test_single_asterisk_multiplication_stays_literal():
    assert markdown_to_telegram_html("5 * 3 = 15") == "5 * 3 = 15"


def test_underscores_in_speaker_labels_stay_literal():
    text = "SPEAKER_1 и SPEAKER_2 согласились"
    assert markdown_to_telegram_html(text) == text


def test_inline_code_converted_and_escaped():
    assert markdown_to_telegram_html("`a<b>`") == "<code>a&lt;b&gt;</code>"


def test_leading_dash_bullet_becomes_dot():
    assert markdown_to_telegram_html("- пункт один") == "• пункт один"


def test_leading_asterisk_bullet_becomes_dot():
    assert markdown_to_telegram_html("* **Тема**: обсуждение") == "• <b>Тема</b>: обсуждение"


def test_indented_bullet_keeps_indent():
    assert markdown_to_telegram_html("  - вложенный") == "  • вложенный"


def test_horizontal_rule_dropped():
    assert markdown_to_telegram_html("текст\n\n---\n\nещё") == "текст\n\nещё"


def test_multiline_document():
    md = "# Протокол\n\n## ✅ Решения\n- запускаем\n\n**Итог:** ок"
    expected = "<b><u>Протокол</u></b>\n\n<b>✅ Решения</b>\n• запускаем\n\n<b>Итог:</b> ок"
    assert markdown_to_telegram_html(md) == expected


def test_bold_inside_bullet_with_html_chars():
    assert (
        markdown_to_telegram_html("- **Риск**: x<y")
        == "• <b>Риск</b>: x&lt;y"
    )
