"""Справка и таксономия говорят правду (критика v3, clarify).

- «management» — тип встречи главного сценария (Протокол ОД); LLM должна
  его знать, иначе типоспецифичных инструкций и буста категории нет.
- meeting_title управляет и заголовком протокола, и именем файла — без
  правила в промпте его качество случайно.
- templates_help_message была мёртвым кодом: справка обязана быть достижима
  из /templates и из флоу создания шаблона.
"""

import inspect
import os
import sys

# Legacy-модули внутри хендлеров используют голый `from services import ...`.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))

from src.prompts.prompts import (  # noqa: E402
    FIELD_SPECIFIC_RULES,
    _get_type_specific_instructions,
    build_analysis_prompt,
)
from src.services.protocol_render.telegram_html import (  # noqa: E402
    markdown_to_telegram_html,
)

# ---------------------------------------------------------------------------
# Таксономия: management — полноправный тип встречи
# ---------------------------------------------------------------------------

def test_management_in_classification_prompt():
    prompt = build_analysis_prompt("обсуждали поручения", participants_list="Иван")
    assert "**management**" in prompt


def test_management_in_speaker_mapping_prompt():
    import src.services.speaker_mapping_service as sms

    assert "**management**" in inspect.getsource(sms)


def test_management_has_specific_instructions():
    text = _get_type_specific_instructions("management")
    assert "поручени" in text.lower()


# ---------------------------------------------------------------------------
# meeting_title: правило качества заголовка
# ---------------------------------------------------------------------------

def test_meeting_title_has_field_rule():
    rule = FIELD_SPECIFIC_RULES.get("meeting_title", "")
    assert "назван" in rule.lower()


# ---------------------------------------------------------------------------
# Справка по шаблонам достижима
# ---------------------------------------------------------------------------

def test_templates_command_offers_help_button():
    import src.handlers.command_handlers as ch

    assert 'callback_data="templates_help"' in inspect.getsource(ch)


def test_templates_help_callback_sends_real_help():
    import src.handlers.callbacks.template_mgmt_callbacks as tmc

    src_text = inspect.getsource(tmc)
    assert '"templates_help"' in src_text
    assert "templates_help_message" in src_text


def test_creation_flow_uses_real_help_not_stale_list():
    import src.handlers.template_handlers as th

    src_text = inspect.getsource(th)
    assert "templates_help_message" in src_text
    # стена из 18 переменных с несуществующими полями удалена
    assert "dialogue_analysis" not in src_text


# ---------------------------------------------------------------------------
# Рендер: ```-фенс из справки превращается в <pre>, а не в мусор
# ---------------------------------------------------------------------------

def test_fenced_block_renders_as_pre():
    md = "Пример:\n```\n# {{ meeting_title }}\n```"
    out = markdown_to_telegram_html(md)
    assert "<pre># {{ meeting_title }}</pre>" in out
    assert "```" not in out


def test_unclosed_fence_keeps_content():
    md = "Текст\n```\nкод без закрытия"
    out = markdown_to_telegram_html(md)
    assert "код без закрытия" in out
