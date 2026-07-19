"""Бриф-компилятор: контент системных шаблонов генерируется из брифа.

Главный инвариант Фазы 1: сгенерированный из брифа Jinja-контент СТРОКОВО равен
замороженному снапшоту текущих шаблонов (байт-в-байт, без .strip()).
"""

import pytest
from fixtures.system_templates_snapshot import SYSTEM_TEMPLATES_SNAPSHOT

from src.models.llm_schemas import PROTOCOL_DATA_SCHEMA
from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.brief_compiler import (
    brief_field_rules,
    brief_to_schema,
    brief_to_template_content,
)
from src.services.protocol_briefs import ALL_BRIEFS, HEADER_FIELDS, get_brief_for


def _iter_object_nodes(node):
    """Все объектные узлы JSON-схемы (для проверки additionalProperties)."""
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        yield node
    for child in node.get("properties", {}).values():
        yield from _iter_object_nodes(child)
    items = node.get("items")
    if isinstance(items, dict):
        yield from _iter_object_nodes(items)
    for def_schema in node.get("$defs", {}).values():
        yield from _iter_object_nodes(def_schema)


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_brief_compiles_to_snapshot_byte_for_byte(brief):
    expected = SYSTEM_TEMPLATES_SNAPSHOT[brief.template_name]
    assert brief_to_template_content(brief) == expected


def test_every_snapshot_template_has_a_brief():
    covered = {b.template_name for b in ALL_BRIEFS}
    assert covered == set(SYSTEM_TEMPLATES_SNAPSHOT)


def test_get_brief_for_returns_none_for_custom_template():
    assert get_brief_for("Мой кастомный шаблон") is None


# ---------------------------------------------------------------------------
# brief_to_schema: строгая схема ЗЕРКАЛИТ прод-обёртку PROTOCOL_DATA_SCHEMA.
# Корень — {protocol_data, quality_score, issues, context_used}; фиксированные
# ключи брифа живут ВНУТРИ закрытого объекта protocol_data (совместимо с
# парсингом generation_result.get('protocol_data')).
# ---------------------------------------------------------------------------


def _protocol_data_node(brief):
    """Узел protocol_data строгой схемы брифа."""
    return brief_to_schema(brief)["schema"]["properties"]["protocol_data"]


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_schema_root_mirrors_prod_wrapper(brief):
    root = brief_to_schema(brief)["schema"]
    # Тот же набор корневых ключей, что у прод-схемы.
    assert set(root["properties"]) == set(PROTOCOL_DATA_SCHEMA["schema"]["properties"])
    # Мета-поля идентичны прод-схеме — меняется только protocol_data.
    for meta in ("quality_score", "issues", "context_used"):
        assert (
            root["properties"][meta]
            == PROTOCOL_DATA_SCHEMA["schema"]["properties"][meta]
        )
    # protocol_data — закрытый объект (не Dict), поэтому обязан быть в required.
    assert "protocol_data" in root["required"]


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_protocol_data_keys_are_header_fields_plus_sections(brief):
    props = _protocol_data_node(brief)["properties"]
    expected = set(HEADER_FIELDS) | {s.key for s in brief.sections}
    if brief.include_lecturer_in_header:
        expected.add("lecturer")  # шапка лекции показывает лектора -> ключ обязателен
    assert set(props) == expected


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_schema_is_strict_with_wrapper_shape(brief):
    schema = brief_to_schema(brief)
    assert set(schema) == {"name", "strict", "schema"}
    assert schema["strict"] is True
    assert schema["schema"]["type"] == "object"


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_schema_every_object_node_is_closed(brief):
    schema = brief_to_schema(brief)
    nodes = list(_iter_object_nodes(schema["schema"]))
    assert nodes, "должен быть хотя бы корневой объект"
    for node in nodes:
        assert node.get("additionalProperties") is False


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_protocol_data_fields_required_string(brief):
    node = _protocol_data_node(brief)
    props = node["properties"]
    for key, prop in props.items():
        assert prop == {"type": "string"}, key
    assert set(node["required"]) == set(props)


def test_protocol_data_standard_has_exact_keys():
    props = _protocol_data_node(get_brief_for("Стандартный протокол встречи"))[
        "properties"
    ]
    assert set(props) == {
        "meeting_title",
        "date",
        "time",
        "participants",
        "agenda",
        "decisions",
        "action_items",
        "risks_and_blockers",
        "key_points",
        "discussion",
        "questions",
        "next_steps",
    }


# ---------------------------------------------------------------------------
# brief_field_rules: инструкции для промпта покрывают ВСЕ ключи схемы (шапка +
# extra + секции). Паритет с legacy: без правил шапочных полей LLM теряет формат
# meeting_title/participants/date/time — тихая деградация шапки.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_field_rules_keys_match_schema_keys(brief):
    """Ключи правил и ключи protocol_data-схемы совпадают — не разъезжаются."""
    schema_keys = set(_protocol_data_node(brief)["properties"])
    assert set(brief_field_rules(brief)) == schema_keys


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_field_rules_include_header_fields(brief):
    """Шапочные поля несут тексты из FIELD_SPECIFIC_RULES (паритет с legacy)."""
    rules = brief_field_rules(brief)
    for key in HEADER_FIELDS:
        assert rules[key] == FIELD_SPECIFIC_RULES[key]


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_field_rules_cover_header_extras_and_sections(brief):
    expected = {key: FIELD_SPECIFIC_RULES.get(key, "") for key in HEADER_FIELDS}
    if brief.include_lecturer_in_header:
        expected["lecturer"] = FIELD_SPECIFIC_RULES["lecturer"]
    expected.update({s.key: s.instruction for s in brief.sections})
    assert brief_field_rules(brief) == expected


@pytest.mark.parametrize("brief", ALL_BRIEFS, ids=lambda b: b.template_name)
def test_field_rules_come_from_field_specific_rules(brief):
    rules = brief_field_rules(brief)
    for key, instruction in rules.items():
        assert instruction == FIELD_SPECIFIC_RULES.get(key, "")


def test_field_rules_standard_carry_real_texts():
    rules = brief_field_rules(get_brief_for("Стандартный протокол встречи"))
    assert rules["decisions"] == FIELD_SPECIFIC_RULES["decisions"]
    assert rules["discussion"].startswith("discussion —")


# ---------------------------------------------------------------------------
# Лектор в шапке лекции: strict-схема с фикс. ключами обязана содержать
# "lecturer", иначе LLM не сможет его вернуть и шапка всегда будет пустой.
# ---------------------------------------------------------------------------


def test_lecture_schema_and_rules_include_lecturer():
    lecture = get_brief_for("Лекция и презентация")
    node = _protocol_data_node(lecture)
    assert node["properties"]["lecturer"] == {"type": "string"}
    assert "lecturer" in node["required"]
    assert brief_field_rules(lecture)["lecturer"] == FIELD_SPECIFIC_RULES["lecturer"]


@pytest.mark.parametrize(
    "brief",
    [b for b in ALL_BRIEFS if not b.include_lecturer_in_header],
    ids=lambda b: b.template_name,
)
def test_non_lecture_briefs_omit_lecturer(brief):
    node = _protocol_data_node(brief)
    assert "lecturer" not in node["properties"]
    assert "lecturer" not in node["required"]
    assert "lecturer" not in brief_field_rules(brief)
