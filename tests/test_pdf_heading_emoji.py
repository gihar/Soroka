"""PDF: эмодзи снимаются единым проходом в _format_inline.

В TTF-шрифтах PDF нет эмодзи-глифов. Снятие происходит в одном месте —
strip_emoji внутри _format_inline; точечных стрипперов для заголовков и
меток шапки больше нет (они дублировали общий проход).
"""

from src.utils import pdf_converter
from src.utils.pdf_converter import _format_inline, strip_emoji


def test_heading_emoji_stripped():
    assert _format_inline("✅ Решения") == "Решения"


def test_heading_emoji_with_variation_selector_stripped():
    assert _format_inline("⚠️ Блокеры и риски") == "Блокеры и риски"


def test_bold_label_emoji_stripped_without_inner_space():
    assert _format_inline("**👥 Участники:**") == "<b>Участники:</b>"


def test_emoji_between_words_leaves_single_space():
    assert strip_emoji("Решили ✅ запускать") == "Решили запускать"


def test_emoji_glued_to_word_removed():
    assert strip_emoji("итоги✅") == "итоги"


def test_plain_text_untouched():
    text = "Обычный текст с дефисом - и числом 15"
    assert _format_inline(text) == text


def test_no_redundant_point_strippers():
    assert not hasattr(pdf_converter, "strip_heading_emoji")
    assert not hasattr(pdf_converter, "strip_label_emoji")
