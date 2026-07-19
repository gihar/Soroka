"""Брифы системных шаблонов протоколов — декларативный источник структуры.

Бриф описывает шаблон как данные (заголовок-фолбэк + упорядоченные секции), а не
как готовый Jinja-текст. Из брифа компилятор (``brief_compiler``) выводит три
роли, которые раньше склеивались через совпадение строковых имён:

1. Jinja-контент системного шаблона (байт-в-байт равный текущему),
2. строгую схему с фиксированными ключами,
3. правила извлечения для промпта.

Фаза 1: связь с ``templates.name`` — по имени; БД не трогаем (см.
docs/design/protocol-briefs-phase1.md).
"""

from dataclasses import dataclass

from src.prompts.prompts import FIELD_SPECIFIC_RULES

# Шапочные поля присутствуют в схеме всех брифов, даже если шаблон их не
# показывает (решение владельца: шапка едина).
HEADER_FIELDS: tuple[str, ...] = ("meeting_title", "date", "time", "participants")


@dataclass(frozen=True)
class BriefSection:
    """Одна секция протокола."""

    key: str  # ключ схемы и llm_result (например, "decisions")
    heading: str  # заголовок секции без "## " (например, "✅ Решения")
    instruction: str  # правило извлечения для промпта
    kind: str = "prose"  # Фаза 1: только "prose"; "tasks"/"decisions" — Фаза 2
    empty_text: str | None = None  # текст вместо пустоты (ОД: «Поручений… не зафиксировано.»)


@dataclass(frozen=True)
class ProtocolBrief:
    """Декларация структуры одного системного шаблона."""

    template_name: str  # связь с templates.name (Фаза 1 — по имени)
    title_fallback: str  # "# {{ meeting_title or '<title_fallback>' }}"
    sections: tuple[BriefSection, ...]
    include_lecturer_in_header: bool = False  # шапка лекции содержит строку «Лектор»


def _section(key: str, heading: str, *, empty_text: str | None = None) -> BriefSection:
    """Секция с инструкцией из FIELD_SPECIFIC_RULES (пустая, если правила нет)."""
    return BriefSection(
        key=key,
        heading=heading,
        instruction=FIELD_SPECIFIC_RULES.get(key, ""),
        empty_text=empty_text,
    )


_STANDARD = ProtocolBrief(
    template_name="Стандартный протокол встречи",
    title_fallback="Протокол встречи",
    sections=(
        _section("agenda", "📋 Повестка дня"),
        _section("decisions", "✅ Решения"),
        _section("action_items", "📌 Задачи и сроки"),
        _section("risks_and_blockers", "⚠️ Блокеры и риски"),
        _section("key_points", "💡 Ключевые выводы"),
        _section("discussion", "💬 Обсуждение"),
        _section("questions", "❓ Открытые вопросы"),
        _section("next_steps", "📅 Следующие шаги"),
    ),
)


_BRIEF_SUMMARY = ProtocolBrief(
    template_name="Краткое резюме встречи",
    title_fallback="Резюме встречи",
    sections=(
        _section("decisions", "✅ Решения"),
        _section("action_items", "📌 Задачи и сроки"),
        _section("key_points", "💡 Ключевые выводы"),
        _section("next_steps", "📅 Следующие шаги"),
    ),
)


_TECHNICAL = ProtocolBrief(
    template_name="Техническое совещание",
    title_fallback="Техническое совещание",
    sections=(
        _section("agenda", "📋 Повестка дня"),
        _section("decisions", "✅ Решения"),
        _section("action_items", "📌 Задачи и сроки"),
        _section("risks_and_blockers", "⚠️ Блокеры и риски"),
        _section("technical_issues", "Технические вопросы"),
        _section("architecture_decisions", "Архитектурные решения"),
        _section("technical_tasks", "Технические задачи"),
        _section("discussion", "💬 Обсуждение"),
        _section("next_sprint_plans", "📅 Планы на следующий спринт"),
    ),
)


_OD = ProtocolBrief(
    template_name="Протокол ОД (Поручения)",
    title_fallback="Протокол поручений",
    sections=(
        _section(
            "tasks_od",
            "📌 Поручения",
            empty_text="Поручений в записи не зафиксировано.",
        ),
        _section("additional_notes", "Дополнительные заметки"),
    ),
)


_DAILY = ProtocolBrief(
    template_name="Дейли",
    title_fallback="Дейли",
    sections=(
        _section("decisions", "✅ Решения"),
        _section("action_items", "📌 Задачи и сроки"),
        _section("risks_and_blockers", "⚠️ Блокеры и риски"),
        _section("yesterday_progress", "Вчера"),
        _section("today_plans", "Сегодня"),
        _section("discussion", "💬 Обсуждение"),
        _section("next_steps", "📅 Следующие шаги"),
    ),
)


_RETROSPECTIVE = ProtocolBrief(
    template_name="Ретроспектива спринта",
    title_fallback="Ретроспектива спринта",
    sections=(
        _section("decisions", "✅ Решения"),
        _section("action_items", "📌 Задачи и сроки"),
        _section("risks_and_blockers", "⚠️ Блокеры и риски"),
        _section("went_well", "Что прошло хорошо"),
        _section("to_improve", "Что улучшить"),
        _section("dialogue_analysis", "Анализ взаимодействия"),
        _section("discussion", "💬 Обсуждение"),
        _section("next_sprint_plans", "📅 Следующий спринт"),
    ),
)


_LECTURE = ProtocolBrief(
    template_name="Лекция и презентация",
    title_fallback="Лекция",
    include_lecturer_in_header=True,
    sections=(
        _section("learning_objectives", "Цели обучения"),
        _section("agenda", "📋 Структура лекции"),
        _section("key_concepts", "Ключевые концепции"),
        _section("discussion", "💬 Основной материал"),
        _section("examples_and_cases", "Примеры и кейсы"),
        _section("questions_and_answers", "❓ Вопросы и ответы"),
        _section("key_points", "💡 Ключевые выводы"),
        _section("homework", "Домашнее задание"),
        _section("additional_materials", "Дополнительные материалы"),
        _section("next_steps", "📅 Следующие шаги"),
    ),
)


ALL_BRIEFS: tuple[ProtocolBrief, ...] = (
    _STANDARD,
    _BRIEF_SUMMARY,
    _TECHNICAL,
    _OD,
    _DAILY,
    _RETROSPECTIVE,
    _LECTURE,
)

_BY_NAME: dict[str, ProtocolBrief] = {b.template_name: b for b in ALL_BRIEFS}


def get_brief_for(template_name: str) -> ProtocolBrief | None:
    """Бриф системного шаблона по имени; ``None`` для кастомных шаблонов."""
    return _BY_NAME.get(template_name)
