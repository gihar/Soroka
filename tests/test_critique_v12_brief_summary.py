"""Критика v12: «Краткое резюме встречи» перестаёт быть Стандартным минус секции.

Замеры по 19 живым прод-протоколам текущей формы (id 368–411):

* «Ключевые выводы» — 36,6% массы документа и единственная секция, выросшая
  против Стандартного (839 → 973 знака, +16%), тогда как Решения (−1%) и Задачи
  (−3%) не изменились. Внутрь неё стекало то, для чего в брифе не было места:
  20 пунктов Решений и Выводов с маркерами риска в 13 протоколах из 19, 13%
  выводов с телеграф-атрибуцией «Имя: глагол» (правило запрещало её только для
  decisions), медиана пункта 146 знаков против 110 у задач.
* Дублирование, снятое в v8 удалением next_steps, переехало внутрь: 24 пары
  Решения↔Задачи в 13 протоколах из 19 (дословных совпадений 0 — все парафраз,
  поэтому запрет «дословно не повторяй» бессилен по построению).
* Столбик участников занимал 56-69% первого мобильного экрана при медиане 7
  человек.

Отсюда три правки: секция рисков возвращена, выводы получили первое в проекте
бриф-специфичное правило, шапка склеивается в строку. Правило-разделитель
«решение против задачи» общее — путаница не специфична для этого шаблона.
"""

import pytest
from jinja2 import Template

from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.brief_compiler import (
    brief_field_rules,
    brief_to_template_content,
)
from src.services.protocol_briefs import ALL_BRIEFS, get_brief_for

_SUMMARY = "Краткое резюме встречи"


def _brief():
    return get_brief_for(_SUMMARY)


def _section_keys(template_name: str) -> list[str]:
    return [s.key for s in get_brief_for(template_name).sections]


# ---------------------------------------------------------------------------
# 1. Секция рисков возвращена — и стоит там, где велит канон порядка
# ---------------------------------------------------------------------------


def test_brief_summary_has_risks_section():
    assert "risks_and_blockers" in _section_keys(_SUMMARY)


def test_risks_stand_between_tasks_and_key_points():
    keys = _section_keys(_SUMMARY)
    assert keys == ["decisions", "action_items", "risks_and_blockers", "key_points"]


def test_risks_section_carries_the_canonical_heading():
    content = brief_to_template_content(_brief())
    assert "## ⚠️ Блокеры и риски" in content


def test_risks_rule_is_the_shared_one():
    # Своего правила рискам не нужно: общее уже требует жирный ярлык и митигацию.
    rules = brief_field_rules(_brief())
    assert rules["risks_and_blockers"] == FIELD_SPECIFIC_RULES["risks_and_blockers"]


def test_v8_gain_is_not_undone():
    # Возврат рисков не тянет за собой next_steps — тот дефект остаётся закрытым.
    assert "next_steps" not in _section_keys(_SUMMARY)


# ---------------------------------------------------------------------------
# 2. Бриф-специфичное правило key_points
# ---------------------------------------------------------------------------


def test_key_points_rule_is_overridden_for_this_brief_only():
    own = brief_field_rules(_brief())["key_points"]
    assert own != FIELD_SPECIFIC_RULES["key_points"]
    # Остальные брифы с этим полем продолжают жить на общем правиле.
    for brief in ALL_BRIEFS:
        if brief.template_name == _SUMMARY:
            continue
        rules = brief_field_rules(brief)
        if "key_points" in rules:
            assert rules["key_points"] == FIELD_SPECIFIC_RULES["key_points"]


@pytest.mark.parametrize(
    "requirement",
    [
        "3-5 пунктов",   # потолок числа пунктов — краткость как ограничение
        "160 знаков",    # потолок длины пункта
        '"Имя:"',        # запрет телеграф-атрибуции (13% выводов в проде)
        "пересказом",    # additive сохранён из v8
    ],
)
def test_key_points_override_carries_its_constraints(requirement):
    assert requirement in brief_field_rules(_brief())["key_points"]


def test_key_points_override_routes_risks_to_their_own_section():
    rule = brief_field_rules(_brief())["key_points"]
    assert "Риски, блокеры" in rule
    assert "НЕ включай" in rule


def test_key_points_override_keeps_numbering_convention():
    # Правило-переопределение подчиняется тому же канону, что и общие правила.
    rule = brief_field_rules(_brief())["key_points"]
    assert "НУМЕРОВАН" in rule.upper()
    assert "- " not in rule


# ---------------------------------------------------------------------------
# 3. Разделительный тест «решение против задачи» (общее правило)
# ---------------------------------------------------------------------------


def test_decisions_rule_separates_decision_from_task():
    rule = FIELD_SPECIFIC_RULES["decisions"]
    assert "назначить ему ответственного" in rule
    assert "action_items" in rule


def test_decisions_rule_keeps_its_earlier_requirements():
    # Разделитель дописан, а не заменил собой правила v6/v7.
    rule = FIELD_SPECIFIC_RULES["decisions"]
    assert "утвердили" in rule
    assert "телеграфом" in rule
    assert "- " not in rule


# ---------------------------------------------------------------------------
# 4. Инлайн-шапка участников
# ---------------------------------------------------------------------------


def test_only_brief_summary_inlines_participants():
    inlining = {b.template_name for b in ALL_BRIEFS if b.inline_participants}
    assert inlining == {_SUMMARY}


def test_inline_header_keeps_participants_on_one_line():
    content = brief_to_template_content(_brief())
    header_line = next(
        line for line in content.splitlines() if "👥 Участники" in line
    )
    assert "{{ participants" in header_line  # значение на той же строке, что и метка


def test_other_briefs_keep_the_column_header():
    content = brief_to_template_content(get_brief_for("Стандартный протокол встречи"))
    assert "**👥 Участники:**\n{{ participants }}\n" in content


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Ли Ясмина\nСветлана Сибатрова", "Ли Ясмина, Светлана Сибатрова"),
        ("Один\n\n  Два  \nТри", "Один, Два, Три"),  # пустые строки и пробелы
        ("Ольга Львова\n", "Ольга Львова"),          # хвостовой перевод строки
        ("Единственный", "Единственный"),
    ],
)
def test_inline_participants_render(raw, expected):
    rendered = Template(brief_to_template_content(_brief())).render(
        meeting_title="Встреча", date="17 августа 2026", participants=raw
    )
    assert f"**👥 Участники:** {expected}\n" in rendered


def test_empty_participants_leave_no_orphan_label():
    rendered = Template(brief_to_template_content(_brief())).render(
        meeting_title="Встреча", date="17 августа 2026", participants=""
    )
    assert "👥" not in rendered


def test_inline_header_saves_lines_on_a_real_roster():
    """Семь имён (медиана прода) — одна строка вместо восьми."""
    roster = "\n".join(f"Участник {n}" for n in range(1, 8))
    values = dict(meeting_title="Встреча", date="17 августа 2026", participants=roster)

    inline = Template(brief_to_template_content(_brief())).render(**values)
    column = Template(
        brief_to_template_content(get_brief_for("Стандартный протокол встречи"))
    ).render(**values)

    # Титул, пустая строка, дата, участники — и всё.
    assert len(inline.strip().splitlines()) == 4
    # Столбик тратит на тот же состав восемь строк вместо одной.
    assert len(column.strip().splitlines()) == len(inline.strip().splitlines()) + 7


# ---------------------------------------------------------------------------
# 5. Крайние случаи новой четвёртой секции
# ---------------------------------------------------------------------------


def _render(**values) -> str:
    return Template(brief_to_template_content(_brief())).render(**values)


def test_empty_risks_leave_no_orphan_heading():
    rendered = _render(
        meeting_title="Встреча",
        date="17 августа 2026",
        decisions="1. Решение",
        action_items="1. Задача",
        risks_and_blockers="",
        key_points="1. Вывод",
    )
    assert "Блокеры и риски" not in rendered
    assert "## ✅ Решения" in rendered
    assert "## 💡 Ключевые выводы" in rendered


def test_risks_render_between_tasks_and_key_points():
    rendered = _render(
        meeting_title="Встреча",
        decisions="1. Решение",
        action_items="1. Задача",
        risks_and_blockers="1. **Риск**: описание",
        key_points="1. Вывод",
    )
    order = [
        rendered.index("## ✅ Решения"),
        rendered.index("## 📌 Задачи и сроки"),
        rendered.index("## ⚠️ Блокеры и риски"),
        rendered.index("## 💡 Ключевые выводы"),
    ]
    assert order == sorted(order)


def test_risks_only_protocol_still_renders():
    # Встреча без решений и задач, но с блокерами: секция не осиротеет.
    rendered = _render(meeting_title="Встреча", risks_and_blockers="1. **Блокер**: описание")
    assert "## ⚠️ Блокеры и риски" in rendered
    assert "## ✅ Решения" not in rendered
