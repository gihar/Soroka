"""Справка по шаблонам говорит правду.

Каждая переменная из справки реально используется системными шаблонами,
справка учит условным секциям {% if %}, и не советует практик,
противоречащих бренд-принципам (эмодзи-перегруз).
"""

import re

from jinja2 import Environment, meta

from src.services.template_library import TemplateLibrary
from src.ux.message_builder import MessageBuilder

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _system_template_variables() -> set[str]:
    env = Environment()
    variables: set[str] = set()
    for template in TemplateLibrary().get_all_templates():
        variables |= meta.find_undeclared_variables(env.parse(template["content"]))
    return variables


def test_help_variables_exist_in_system_templates():
    help_text = MessageBuilder.templates_help_message()
    mentioned = set(_VAR_RE.findall(help_text))
    assert mentioned, "справка должна документировать переменные"
    unknown = mentioned - _system_template_variables()
    assert not unknown, f"справка упоминает неиспользуемые переменные: {unknown}"


def test_help_documents_conditional_sections():
    help_text = MessageBuilder.templates_help_message()
    assert "{% if" in help_text


def test_help_does_not_recommend_emoji():
    assert "эмодзи" not in MessageBuilder.templates_help_message().lower()


def test_help_example_follows_house_style():
    """Пример в справке — с шапкой meeting_title и условной секцией."""
    help_text = MessageBuilder.templates_help_message()
    assert "meeting_title" in help_text


def test_help_example_guards_meta_lines():
    """Дата/Участники в примере обёрнуты в {% if %} — как учит абзац выше.

    Иначе пример сам демонстрирует анти-паттерн: «Дата: » висит над пустотой,
    против которой справка предупреждает строкой выше.
    """
    help_text = MessageBuilder.templates_help_message()
    assert "{% if date %}" in help_text
    assert "{% if participants %}" in help_text
    # Стиль как у системной шапки: жирная метка.
    assert "**Дата:**" in help_text
    assert "**Участники:**" in help_text
    # Голой строки «Дата: {{ date }}» без охраны в примере не осталось.
    assert "Дата: {{ date }}" not in help_text
    assert "Участники: {{ participants }}" not in help_text
