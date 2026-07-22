"""Списковые секции системных шаблонов диктуют нумерацию «N. …», а не «- ».

Механизм — правила полей (FIELD_SPECIFIC_RULES), тот же, что уже нумерует
tasks_od. Jinja-контент шаблонов не меняется (снапшот остаётся байт-в-байт).

Исключения сознательны: participants — перечень имён в шапке; discussion и
дейли-блоки «по людям» — атрибуция, а не плоский список; лекционный жанр —
учебный материал; tasks_od уже нумерован.
"""

from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.protocol_briefs import ALL_BRIEFS

# Списковые секции, переведённые на нумерацию «N. …».
NUMBERED_SECTIONS = {
    "decisions",
    "action_items",
    "key_points",
    "agenda",
    "risks_and_blockers",
    "next_steps",
    "went_well",
    "to_improve",
    "questions",
    "technical_issues",
    "architecture_decisions",
    "technical_tasks",
    "next_sprint_plans",
}

# Секции системных шаблонов, сознательно НЕ переведённые на нумерацию.
NON_NUMBERED_SECTIONS = {
    "discussion",          # тематические блоки с атрибуцией
    "yesterday_progress",  # дейли: блоки по людям (атрибуция)
    "today_plans",
    "dialogue_analysis",   # проза (как обсуждалось)
    "additional_notes",    # проза-«ловушка»
    "tasks_od",            # уже нумерован
    # лекционный жанр — учебный материал, не список решений/поручений:
    "learning_objectives",
    "key_concepts",
    "examples_and_cases",
    "questions_and_answers",
    "homework",
    "additional_materials",
}


def _all_brief_section_keys() -> set[str]:
    return {section.key for brief in ALL_BRIEFS for section in brief.sections}


def test_every_system_section_is_consciously_classified():
    """Ни одна секция брифов не забыта: покрыта numbered ∪ non-numbered."""
    assert _all_brief_section_keys() == NUMBERED_SECTIONS | NON_NUMBERED_SECTIONS


def test_numbered_sections_instruct_numbering_not_bullets():
    for key in NUMBERED_SECTIONS:
        rule = FIELD_SPECIFIC_RULES[key]
        assert "НУМЕРОВАН" in rule.upper(), key
        # Маркер плоского списка «- » (дефис-пробел) больше не диктуется.
        assert "- " not in rule, key


def test_numbered_sections_keep_content_requirements():
    # Формат сменился, но содержательные требования на месте.
    assert "Ответственный" in FIELD_SPECIFIC_RULES["action_items"]
    assert "Обоснование" in FIELD_SPECIFIC_RULES["architecture_decisions"]
    assert "РЕШЕНО" in FIELD_SPECIFIC_RULES["decisions"]
    assert "митигаци" in FIELD_SPECIFIC_RULES["risks_and_blockers"]


def test_excluded_sections_are_not_forced_to_number():
    # discussion остаётся атрибуцией по темам, participants — перечнем имён.
    assert "НУМЕРОВАН" not in FIELD_SPECIFIC_RULES["discussion"].upper()
    assert "НУМЕРОВАН" not in FIELD_SPECIFIC_RULES["participants"].upper()
