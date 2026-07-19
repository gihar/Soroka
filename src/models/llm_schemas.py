"""
JSON Schema модели для OpenAI Structured Outputs
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class SpeakerMappingSchema(BaseModel):
    """Схема для сопоставления спикеров с участниками и определения типа встречи"""
    meeting_type: str = Field(
        description="Тип встречи (technical, business, educational, brainstorm, status, management, general)"
    )
    speaker_mappings: Dict[str, str] = Field(
        description="Сопоставление speaker_id -> participant_name в формате 'Имя Фамилия' (БЕЗ отчества)"
    )
    confidence_scores: Dict[str, float] = Field(
        description="Уверенность в сопоставлении для каждого спикера (0.0-1.0). Только спикеры с уверенностью >= 0.7 включаются в speaker_mappings"
    )
    unmapped_speakers: List[str] = Field(
        description="Список speaker_id (например, SPEAKER_3) с уверенностью < 0.7, которых не удалось надежно сопоставить с участниками"
    )
    mapping_notes: str = Field(description="Заметки по сопоставлению и определению типа встречи")

    class Config:
        extra = "forbid"


















def get_json_schema(model_class: BaseModel) -> Dict[str, Any]:
    """
    Получить JSON Schema для Pydantic модели в формате OpenAI
    
    Args:
        model_class: Класс Pydantic модели
        
    Returns:
        Словарь с JSON Schema в формате OpenAI
    """
    schema = model_class.model_json_schema()
    
    # OpenAI Structured Outputs в strict режиме требует добавлять поля с default в required,
    # НО Azure OpenAI не позволяет включать в required поля с additionalProperties (Dict[str, T]).
    # Поэтому добавляем в required только поля с фиксированными типами.
    # Для Dict полей сохраняем их additionalProperties (тип значений), что позволяет LLM
    # заполнять динамические ключи согласно инструкциям промпта.
    
    def fix_required_fields(schema_dict: Dict[str, Any]) -> None:
        """
        Рекурсивно исправить required для всех схем.

        Azure OpenAI в strict mode требует ВСЕ поля (кроме Dict) в required массиве,
        даже если у них есть default. Это отличие от стандартного OpenAI.
        """
        if "properties" in schema_dict:
            required_fields = []
            for prop_name, prop_schema in schema_dict["properties"].items():
                # Для Dict полей (с additionalProperties) НЕ добавляем в required
                # Azure OpenAI не позволяет Dict поля в strict mode
                if "additionalProperties" in prop_schema:
                    # Оставляем additionalProperties как есть (строка, число и т.д.)
                    # Это позволяет LLM заполнять динамические ключи
                    pass
                else:
                    # Azure OpenAI требует ВСЕ поля в required, даже с default
                    # Это решает ошибку "Missing 'meeting_date'" и подобные
                    required_fields.append(prop_name)

                # Рекурсивно обрабатываем вложенные объекты
                if prop_schema.get("type") == "object" and "properties" in prop_schema:
                    fix_required_fields(prop_schema)

                # Обрабатываем массивы с вложенными объектами
                if prop_schema.get("type") == "array" and "items" in prop_schema:
                    items_schema = prop_schema["items"]
                    if isinstance(items_schema, dict):
                        # Для Dict внутри массивов также сохраняем тип
                        if items_schema.get("type") == "object" and "properties" in items_schema:
                            fix_required_fields(items_schema)

            # Azure OpenAI требует required массив с ВСЕМИ полями (кроме Dict)
            if required_fields:
                schema_dict["required"] = required_fields

        # Обработать вложенные схемы в $defs
        if "$defs" in schema_dict:
            for def_name, def_schema in schema_dict["$defs"].items():
                fix_required_fields(def_schema)
    
    def enforce_additional_properties_false(node: Dict[str, Any]) -> None:
        """Strict Structured Outputs требует additionalProperties:false на КАЖДОМ
        объектном узле (включая корень). Проставляем его рекурсивно, НЕ трогая
        узлы, где additionalProperties уже задан — это типизированные Dict-карты
        вида {"additionalProperties": {"type": "string"}}, которые провайдер
        принимает и которые нужны для динамических ключей.
        """
        if not isinstance(node, dict):
            return

        if node.get("type") == "object" and "additionalProperties" not in node:
            node["additionalProperties"] = False

        properties = node.get("properties")
        if isinstance(properties, dict):
            for child in properties.values():
                enforce_additional_properties_false(child)

        defs = node.get("$defs")
        if isinstance(defs, dict):
            for child in defs.values():
                enforce_additional_properties_false(child)

        items = node.get("items")
        if isinstance(items, dict):
            enforce_additional_properties_false(items)

        for combiner in ("anyOf", "oneOf", "allOf"):
            branches = node.get(combiner)
            if isinstance(branches, list):
                for branch in branches:
                    enforce_additional_properties_false(branch)

    fix_required_fields(schema)
    enforce_additional_properties_false(schema)

    # OpenAI требует определенный формат
    return {
        "name": schema.get("title", model_class.__name__),
        "schema": schema,
        "strict": True
    }


# Предопределенные схемы для быстрого доступа

class MeetingAnalysisSchema(BaseModel):
    """
    Схема для первого запроса: анализ типа встречи и сопоставление спикеров
    """
    meeting_type: str = Field(
        description="Тип встречи (technical, business, educational, brainstorm, status, management, general)"
    )
    speaker_mappings: Dict[str, str] = Field(
        default_factory=dict,
        description="Сопоставление SPEAKER_N → 'Имя Фамилия' для спикеров с уверенностью >= 0.7"
    )
    unmapped_speakers: List[str] = Field(
        default_factory=list,
        description="Список SPEAKER_N с уверенностью < 0.7, которых не удалось надежно сопоставить"
    )
    analysis_confidence: float = Field(
        default=0.0,
        description="Уверенность в анализе (0.0-1.0)"
    )
    analysis_notes: str = Field(
        default="",
        description="Заметки по анализу типа и спикеров"
    )

    class Config:
        extra = "forbid"


class ProtocolDataSchema(BaseModel):
    """
    Схема для второго запроса: извлечение данных протокола
    """
    protocol_data: Dict[str, str] = Field(
        default_factory=dict,
        description="Извлеченные данные протокола (ключ=переменная шаблона, значение=строка)"
    )
    quality_score: float = Field(
        default=0.0,
        description="Оценка качества извлечения (0.0-1.0)"
    )
    issues: List[str] = Field(
        default_factory=list,
        description="Проблемы или неоднозначности при извлечении"
    )
    context_used: bool = Field(
        default=False,
        description="Использовался ли дополнительный контекст (повестка, проекты)"
    )

    class Config:
        extra = "forbid"


# Предопределенные схемы для быстрого доступа
SPEAKER_MAPPING_SCHEMA = get_json_schema(SpeakerMappingSchema)
MEETING_ANALYSIS_SCHEMA = get_json_schema(MeetingAnalysisSchema)
PROTOCOL_DATA_SCHEMA = get_json_schema(ProtocolDataSchema)
