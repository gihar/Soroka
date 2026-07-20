"""PDF: подряд идущие пустые строки не дают стопку Spacer.

Пустые `{% if %}`-секции оставляют несколько пустых строк подряд. Раньше каждая
давала свой Spacer → вертикальные дыры. Теперь Spacer не добавляется, если
предыдущий элемент story — тоже Spacer.
"""

from reportlab.platypus import Spacer

from src.utils.pdf_converter import (
    _FONT_BOLD,
    _FONT_REGULAR,
    _build_styles,
    _markdown_to_story,
)


def _story(markdown_text):
    styles = _build_styles(_FONT_REGULAR, _FONT_BOLD)
    return _markdown_to_story(markdown_text, styles)


def test_consecutive_blank_lines_collapse_to_single_spacer():
    story = _story("Первый абзац\n\n\n\nВторой абзац")
    for prev, cur in zip(story, story[1:]):
        assert not (isinstance(prev, Spacer) and isinstance(cur, Spacer)), \
            "подряд идущие Spacer дают вертикальную дыру"


def test_single_blank_line_still_separates_paragraphs():
    story = _story("Абзац А\n\nАбзац Б")
    assert any(isinstance(el, Spacer) for el in story)
