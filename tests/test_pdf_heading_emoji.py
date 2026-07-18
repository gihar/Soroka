"""PDF-рендер: эмодзи-метки секций снимаются с заголовков.

Кириллические TTF-шрифты PDF не содержат эмодзи-глифов; навигационные метки
из чата в PDF превращались бы в «тофу» (□). В PDF иерархию несут стили.
"""

from src.utils.pdf_converter import strip_heading_emoji, strip_label_emoji


def test_section_emoji_removed():
    assert strip_heading_emoji("✅ Решения") == "Решения"


def test_emoji_with_variation_selector_removed():
    assert strip_heading_emoji("⚠️ Блокеры и риски") == "Блокеры и риски"


def test_plain_heading_untouched():
    assert strip_heading_emoji("Обсуждение") == "Обсуждение"


def test_emoji_in_middle_kept():
    # снимаем только ведущую метку — контент не трогаем
    assert strip_heading_emoji("Итоги ✅ спринта") == "Итоги ✅ спринта"


def test_bold_label_emoji_removed():
    assert strip_label_emoji("**👥 Участники:**") == "**Участники:**"


def test_plain_label_untouched():
    assert strip_label_emoji("**Дата:** 17 июля") == "**Дата:** 17 июля"


def test_label_emoji_only_at_line_start():
    assert strip_label_emoji("Метка **👥 внутри** строки") == "Метка **👥 внутри** строки"
