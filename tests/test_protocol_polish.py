"""Финальный проход по бэклогу UX-критики: мелкие дефекты рендеринга."""

from src.models.processing import TranscriptionResult
from src.services.processing.protocol_formatter import ProtocolFormatter
from src.utils.pdf_converter import _is_horizontal_rule


# ---------------------------------------------------------------------------
# PDF: markdown-линейка не должна печататься текстом «---»
# ---------------------------------------------------------------------------

def test_dashes_line_is_horizontal_rule():
    assert _is_horizontal_rule("---")
    assert _is_horizontal_rule("----------")


def test_bullet_and_text_are_not_rules():
    assert not _is_horizontal_rule("- пункт")
    assert not _is_horizontal_rule("обычный текст")
    assert not _is_horizontal_rule("--")


# ---------------------------------------------------------------------------
# Fallback: пустой meeting_title не оставляет заголовка-сироты «# »
# ---------------------------------------------------------------------------

def test_enhanced_fallback_empty_title_uses_default():
    formatter = ProtocolFormatter()
    out = formatter._format_enhanced_fallback(
        {
            "meeting_title": "",
            "discussion": "Достаточно длинное обсуждение деталей запуска, "
            "чтобы fallback не свалился в базовую транскрипцию. " * 3,
        },
        TranscriptionResult(transcription="текст"),
    )
    assert not out.startswith("# \n")
    assert out.startswith("# Протокол встречи")
