"""Компилятор брифов: бриф -> Jinja-контент, строгая схема, правила промпта.

Единственный источник структуры системного шаблона — ``ProtocolBrief``. Контент
собирается детерминированно, чтобы совпадать с текущими шаблонами байт-в-байт
(инвариант Фазы 1, проверяется снапшот-тестом).
"""

import copy

from src.models.llm_schemas import PROTOCOL_DATA_SCHEMA
from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.protocol_briefs import HEADER_FIELDS, ProtocolBrief

# Шапка: дата/время и участники — общие для всех брифов. Лекция вставляет между
# ними строку «Лектор» (include_lecturer_in_header).
_DATE_BLOCK = (
    "{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}\n{% endif %}"
)
_LECTURER_BLOCK = "{% if lecturer %}**Лектор:** {{ lecturer }}\n{% endif %}"
_PARTICIPANTS_BLOCK = "{% if participants %}**👥 Участники:**\n{{ participants }}\n{% endif %}"


def _header(brief: ProtocolBrief) -> str:
    if brief.include_lecturer_in_header:
        return _DATE_BLOCK + _LECTURER_BLOCK + _PARTICIPANTS_BLOCK
    return _DATE_BLOCK + _PARTICIPANTS_BLOCK


def _header_extra_keys(brief: ProtocolBrief) -> tuple[str, ...]:
    """Шапочные поля сверх общих HEADER_FIELDS (лекция показывает «Лектор»).

    Такое поле обязано попасть в схему и правила промпта: strict-схема с
    additionalProperties:false запрещает лишние ключи, поэтому без него LLM не
    смог бы вернуть lecturer и шапка лекции была бы всегда пустой.
    """
    return ("lecturer",) if brief.include_lecturer_in_header else ()


def _section_block(section) -> str:
    block = f"{{% if {section.key} %}}\n## {section.heading}\n{{{{ {section.key} }}}}\n"
    if section.empty_text is not None:
        block += f"{{% else %}}\n{section.empty_text}\n"
    block += "{% endif %}"
    return block


def brief_to_template_content(brief: ProtocolBrief) -> str:
    """Собрать Jinja-контент системного шаблона из брифа."""
    title = f"# {{{{ meeting_title or '{brief.title_fallback}' }}}}\n\n"
    body = "\n".join(_section_block(section) for section in brief.sections)
    return title + _header(brief) + "\n" + body


def _protocol_data_object(brief: ProtocolBrief) -> dict:
    """Закрытый объект ``protocol_data``: фиксированные ключи (шапка + секции).

    Все поля required, string; ``additionalProperties: false`` закрывает набор —
    strict mode начинает гарантировать покрытие секций (в отличие от legacy
    Dict[str, str], где ключи динамические).
    """
    properties = {
        key: {"type": "string"}
        for key in (
            *HEADER_FIELDS,
            *_header_extra_keys(brief),
            *(section.key for section in brief.sections),
        )
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def brief_to_schema(brief: ProtocolBrief) -> dict:
    """Строгая схема, ЗЕРКАЛЯЩАЯ прод-обёртку ``PROTOCOL_DATA_SCHEMA``.

    Корень и мета-поля (``quality_score``, ``issues``, ``context_used``)
    идентичны прод-схеме — иначе парсинг ``generation_result.get('protocol_data')``
    не совпал бы. Отличие ровно одно: ``protocol_data`` — не Dict[str, str], а
    закрытый объект с фиксированными ключами (шапка + секции брифа). Из-за этого
    ``protocol_data`` становится required: провайдер исключает из required только
    Dict-поля (с типизированным additionalProperties), а закрытый объект — нет.
    """
    schema = copy.deepcopy(PROTOCOL_DATA_SCHEMA)
    root = schema["schema"]
    root["properties"]["protocol_data"] = _protocol_data_object(brief)
    if "protocol_data" not in root["required"]:
        root["required"] = [*root["required"], "protocol_data"]
    return schema


def brief_field_rules(brief: ProtocolBrief) -> dict[str, str]:
    """Правила извлечения для промпта: {ключ: инструкция}.

    Секции — плюс шапочные extra-поля (лекция: lecturer), которые тоже
    заполняются LLM и потому нуждаются в инструкции.
    """
    rules = {key: FIELD_SPECIFIC_RULES.get(key, "") for key in _header_extra_keys(brief)}
    rules.update({section.key: section.instruction for section in brief.sections})
    return rules
