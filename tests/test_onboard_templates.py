"""Онбординг кастомных шаблонов и находимость системных (критика v3).

- Системные шаблоны без category делали категории /templates пустыми:
  «Протокол ОД» нельзя было найти под «Управленческие».
- Кастомный шаблон без {% if %} молча нарушает «ничего пустого»: пустые
  поля оставляют заголовки-сироты. Превью предупреждает — не блокируя.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Legacy-модули внутри хендлеров используют голый `from services import ...`.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))

from src.services.template_library import TemplateLibrary  # noqa: E402

_KNOWN_CATEGORIES = {"general", "technical", "management", "educational"}


# ---------------------------------------------------------------------------
# Категории системных шаблонов
# ---------------------------------------------------------------------------

def test_every_system_template_has_known_category():
    for template in TemplateLibrary().get_all_templates():
        assert template.get("category") in _KNOWN_CATEGORIES, template["name"]


def test_od_protocol_is_management():
    od = next(
        t for t in TemplateLibrary().get_all_templates() if "ОД" in t["name"]
    )
    assert od["category"] == "management"


def test_lecture_is_educational():
    lecture = next(
        t for t in TemplateLibrary().get_all_templates() if "Лекция" in t["name"]
    )
    assert lecture["category"] == "educational"


# ---------------------------------------------------------------------------
# Превью кастомного шаблона: предупреждение про {% if %}
# ---------------------------------------------------------------------------

def _fake_template_service() -> SimpleNamespace:
    return SimpleNamespace(render_template=lambda content, variables: "отрендерено")


async def _preview_text(monkeypatch, content: str) -> str:
    import src.handlers.template_handlers as th

    sent = {}

    async def fake_answer(message, text, **kwargs):
        sent["text"] = text
        return object()

    monkeypatch.setattr(th, "safe_answer", fake_answer)

    message = MagicMock()
    message.answer = AsyncMock()
    await th._show_template_preview(
        message,
        {"template_name": "Мой шаблон", "template_content": content},
        _fake_template_service(),
    )
    return sent["text"]


@pytest.mark.asyncio
async def test_preview_warns_when_no_conditional_sections(monkeypatch):
    text = await _preview_text(
        monkeypatch, "# {{ meeting_title }}\n\n## Решения\n{{ decisions }}"
    )
    assert "{% if" in text  # подсказка про условные секции


@pytest.mark.asyncio
async def test_preview_does_not_warn_with_conditionals(monkeypatch):
    text = await _preview_text(
        monkeypatch,
        "# {{ meeting_title }}\n\n{% if decisions %}\n## Решения\n{{ decisions }}\n{% endif %}",
    )
    assert "заголовки" not in text.lower()
