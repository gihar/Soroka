"""Финальный проход по бэклогу критики v3: мелочи, которые видит читатель."""

import inspect
import os
import sys

# Legacy-модули внутри хендлеров используют голый `from services import ...`.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.processing import TranscriptionResult  # noqa: E402
from src.services.processing.protocol_formatter import ProtocolFormatter  # noqa: E402
from src.services.template_library import TemplateLibrary  # noqa: E402
from src.ux.message_builder import MessageBuilder  # noqa: E402

# ---------------------------------------------------------------------------
# Время обработки: «5 мин 12 с», а не «312 с»
# ---------------------------------------------------------------------------

def test_duration_over_minute_readable():
    assert MessageBuilder._format_duration(312) == "5 мин 12 с"


def test_duration_under_minute_stays_seconds():
    assert MessageBuilder._format_duration(59) == "59 с"


def test_duration_round_minutes():
    assert MessageBuilder._format_duration(120) == "2 мин"


# ---------------------------------------------------------------------------
# ⭐ убран из списков шаблонов: «системный» читался как «рекомендуемый»
# ---------------------------------------------------------------------------

def test_template_lists_have_no_default_star():
    import src.handlers.callbacks.template_callbacks as tc
    import src.handlers.callbacks.template_mgmt_callbacks as tmc

    for module in (tc, tmc):
        assert "is_default else" not in inspect.getsource(module), module.__name__


# ---------------------------------------------------------------------------
# Заголовок секции соответствует содержимому (next_steps)
# ---------------------------------------------------------------------------

def test_next_steps_heading_consistent_across_templates():
    for template in TemplateLibrary().get_all_templates():
        content = template["content"]
        if "{{ next_steps }}" in content:
            assert "## 📅 Следующие шаги" in content, template["name"]
            assert "Следующая встреча" not in content, template["name"]
            assert "Следующая лекция" not in content, template["name"]


# ---------------------------------------------------------------------------
# dict/list от LLM рендерятся как Markdown, а не Python-repr
# ---------------------------------------------------------------------------

def test_list_values_render_as_markdown_not_repr():
    formatter = ProtocolFormatter()
    out = formatter.format_protocol(
        {
            "content": (
                "# {{ meeting_title }}\n\n"
                "{% if decisions %}## Решения\n{{ decisions }}\n{% endif %}"
            )
        },
        {
            "meeting_title": "Планёрка команды",
            "decisions": [
                "Запускаем пилот на двух командах",
                "Нанимаем DevOps-инженера до конца месяца",
            ],
        },
        TranscriptionResult(transcription="текст"),
    )
    assert "['" not in out and "']" not in out
    assert "Запускаем пилот" in out


# ---------------------------------------------------------------------------
# PDF: #### не печатается буквальным текстом
# ---------------------------------------------------------------------------

def test_pdf_handles_h4_headings():
    from src.utils import pdf_converter

    assert "startswith('#### ')" in inspect.getsource(pdf_converter)
