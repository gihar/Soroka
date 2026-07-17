"""Структурный контракт системных шаблонов протоколов.

Единая структура (бриф redesign 2026-07):
- шапка: название встречи (meeting_title с фолбэком), дата, участники;
- порядок секций: решения -> задачи/сроки -> блокеры -> спец-секции -> обсуждение -> следующие шаги;
- эмодзи-словарь секций: 👥 ✅ 📌 ⚠️ 💬 📅;
- каждая секция обёрнута в {% if %}: пустая секция не оставляет заголовка-сироты;
- русский язык без английских артефактов и подписей генератора.
"""

import re

from jinja2 import Environment, meta

from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.template_library import TemplateLibrary


def all_system_templates() -> list[dict]:
    return TemplateLibrary().get_all_templates()


def _render_with_empty_vars(content: str) -> str:
    env = Environment()
    variables = meta.find_undeclared_variables(env.parse(content))
    return env.from_string(content).render(**{var: "" for var in variables})


def _template_variables(content: str) -> set[str]:
    env = Environment()
    return meta.find_undeclared_variables(env.parse(content))


def test_library_contains_all_seven_system_templates():
    names = {t["name"] for t in all_system_templates()}
    assert names == {
        "Стандартный протокол встречи",
        "Краткое резюме встречи",
        "Техническое совещание",
        "Протокол ОД (Поручения)",
        "Дейли",
        "Ретроспектива спринта",
        "Лекция и презентация",
    }


def test_header_uses_meeting_title_with_fallback():
    for t in all_system_templates():
        first_line = t["content"].lstrip().splitlines()[0]
        assert first_line.startswith("# "), t["name"]
        assert "{{ meeting_title" in first_line, t["name"]


def test_unified_section_order():
    order = ["✅ Решения", "📌 Задачи", "⚠️ Блокеры", "💬 Обсуждение", "📅 "]
    for t in all_system_templates():
        content = t["content"]
        positions = [content.find(marker) for marker in order]
        present = [p for p in positions if p != -1]
        assert present == sorted(present), (
            f"{t['name']}: секции нарушают единый порядок {order}"
        )


def test_empty_variables_leave_no_orphan_headings():
    for t in all_system_templates():
        rendered = _render_with_empty_vars(t["content"])
        for line in rendered.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip()
                assert heading_text, f"{t['name']}: голый маркер заголовка «{stripped}»"
        assert "Не указано" not in rendered, t["name"]


def test_every_section_heading_is_conditional():
    """Рендер с пустыми переменными не должен оставлять ни одной ##-секции."""
    for t in all_system_templates():
        rendered = _render_with_empty_vars(t["content"])
        section_headings = [
            line for line in rendered.splitlines() if line.strip().startswith("##")
        ]
        assert section_headings == [], (
            f"{t['name']}: секции без {{% if %}}: {section_headings}"
        )


def test_no_english_artifacts_or_generator_signatures():
    banned = [
        "Action Items",
        "standup",
        "Standup",
        "generated automatically",
        "Retro generated",
        "составлен автоматически",
        "создан автоматически",
    ]
    for t in all_system_templates():
        for phrase in banned:
            assert phrase not in t["content"], f"{t['name']}: «{phrase}»"


def test_no_ascii_dividers():
    for t in all_system_templates():
        assert "====" not in t["content"], t["name"]


def test_no_conditional_inside_heading_line():
    """Конструкция `## {% if x %}Заголовок{% endif %}` даёт голые ## при пустой переменной."""
    for t in all_system_templates():
        for line in t["content"].splitlines():
            if line.strip().startswith("#"):
                assert "{%" not in line, f"{t['name']}: условие внутри заголовка: {line}"


def test_all_template_variables_have_llm_field_rules():
    core = {"meeting_title", "date", "time", "meeting_date", "meeting_time", "participants"}
    for t in all_system_templates():
        for var in _template_variables(t["content"]):
            assert var in core or var in FIELD_SPECIFIC_RULES, (
                f"{t['name']}: переменная {var} без правила для LLM"
            )


def test_daily_has_targeted_fields_instead_of_rubber_discussion():
    daily = next(t for t in all_system_templates() if t["name"] == "Дейли")
    variables = _template_variables(daily["content"])
    assert "yesterday_progress" in variables
    assert "today_plans" in variables


def test_retro_has_targeted_fields():
    retro = next(
        t for t in all_system_templates() if t["name"] == "Ретроспектива спринта"
    )
    variables = _template_variables(retro["content"])
    assert "went_well" in variables
    assert "to_improve" in variables
    assert "key_points" not in variables  # «Что прошло хорошо» больше не подменяется выводами


def test_lecture_has_lecturer_field():
    lecture = next(
        t for t in all_system_templates() if t["name"] == "Лекция и презентация"
    )
    assert "lecturer" in _template_variables(lecture["content"])


def test_od_protocol_uses_common_markup():
    od = next(
        t for t in all_system_templates() if t["name"] == "Протокол ОД (Поручения)"
    )
    content = od["content"]
    assert content.lstrip().startswith("# ")
    assert "ПРОТОКОЛ ПОРУЧЕНИЙ" not in content
    assert "## 📌 Поручения" in content


def test_new_targeted_fields_have_rules():
    for field in ("yesterday_progress", "today_plans", "went_well", "to_improve", "lecturer"):
        assert field in FIELD_SPECIFIC_RULES, field


def test_emoji_used_once_per_section_heading():
    """Эмодзи — навигационные метки: не более одного в строке заголовка."""
    emoji_re = re.compile(r"👥|✅|📌|⚠️|💬|📅")
    for t in all_system_templates():
        for line in t["content"].splitlines():
            if line.startswith("##"):
                assert len(emoji_re.findall(line)) <= 1, f"{t['name']}: {line}"
