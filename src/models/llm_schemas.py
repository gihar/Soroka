"""
JSON Schema модели для OpenAI Structured Outputs
"""

from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
import json

from src.models.meeting_structure import DecisionPriority, ActionItemPriority


class ProtocolSchema(BaseModel):
    """
    Схема для основного протокола встречи
    
    ВАЖНО: Все поля - строки! Промпт явно требует:
    "Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов"
    """
    meeting_title: str = Field(description="Название встречи")
    meeting_date: Optional[str] = Field(default=None, description="Дата встречи")
    meeting_time: Optional[str] = Field(default=None, description="Время встречи")
    participants: str = Field(description="Список участников (каждое имя с новой строки через \\n)")
    agenda: str = Field(description="Повестка дня (пункты списком через \\n)")
    key_points: str = Field(description="Ключевые моменты (пункты списком через \\n)")
    decisions: str = Field(description="Принятые решения (каждое с новой строки через \\n)")
    action_items: str = Field(description="Задачи и поручения (каждая с новой строки через \\n)")
    next_meeting: Optional[str] = Field(default=None, description="Информация о следующей встрече")
    additional_notes: Optional[str] = Field(default=None, description="Дополнительные заметки")
    detected_speaker_mapping: Optional[Dict[str, str]] = Field(default=None, description="Автоопределенное сопоставление SPEAKER_N с именами участников")
    speaker_confidence_scores: Optional[Dict[str, float]] = Field(default=None, description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: Optional[List[str]] = Field(default=None, description="Спикеры которых не удалось сопоставить")
    mapping_notes: Optional[str] = Field(default=None, description="Заметки по автоопределению участников")
    
    class Config:
        extra = "forbid"


class TwoStageExtractionSchema(BaseModel):
    """
    Схема для первого этапа двухэтапной генерации (извлечение)
    
    ВАЖНО: 
    - extracted_data содержит только строковые значения (не объекты, не массивы)
      Ключи = поля из template_variables, значения = строки с извлеченными данными
    - Optional поля (detected_speaker_mapping и др.) используются для автоопределения спикеров
      Они заполняются только если в транскрипции есть метки SPEAKER_N
    - Все Dict поля не включаются в required из-за ограничений Azure OpenAI strict mode
      (additionalProperties не может быть в required fields)
    """
    extracted_data: Dict[str, str] = Field(default_factory=dict, description="Извлеченные данные из транскрипции (ключ=переменная шаблона, значение=строка)")
    confidence_score: float = Field(default=0.0, description="Уровень уверенности в извлечении (0.0-1.0)")
    extraction_notes: str = Field(default="", description="Заметки по извлечению")
    detected_speaker_mapping: Optional[Dict[str, str]] = Field(default=None, description="Автоопределенное сопоставление SPEAKER_N с именами участников")
    speaker_confidence_scores: Optional[Dict[str, float]] = Field(default=None, description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: Optional[List[str]] = Field(default=None, description="Спикеры которых не удалось сопоставить")
    mapping_notes: Optional[str] = Field(default=None, description="Заметки по автоопределению участников")
    
    class Config:
        extra = "forbid"


class TwoStageReflectionSchema(BaseModel):
    """Схема для второго этапа двухэтапной генерации (рефлексия)"""
    refined_data: Dict[str, str] = Field(default_factory=dict, description="Уточненные данные после рефлексии (ключ=переменная шаблона, значение=строка)")
    reflection_notes: str = Field(default="", description="Заметки по рефлексии")
    quality_score: float = Field(default=0.0, description="Оценка качества результата (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class UnifiedProtocolSchema(BaseModel):
    """Схема для unified подхода: извлечение + self-reflection в одном запросе"""
    protocol_data: Dict[str, str] = Field(default_factory=dict, description="Извлеченные данные протокола (ключ=переменная шаблона, значение=строка)")
    self_reflection: Dict[str, Any] = Field(default_factory=dict, description="Самопроверка модели")
    confidence_score: float = Field(default=0.0, description="Общая уверенность (0.0-1.0)")
    quality_notes: str = Field(default="", description="Заметки по качеству")
    detected_speaker_mapping: Optional[Dict[str, str]] = Field(default=None, description="Автоопределенное сопоставление SPEAKER_N с именами участников")
    speaker_confidence_scores: Optional[Dict[str, float]] = Field(default=None, description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: Optional[List[str]] = Field(default=None, description="Спикеры которых не удалось сопоставить")
    mapping_notes: Optional[str] = Field(default=None, description="Заметки по автоопределению участников")
    
    class Config:
        extra = "forbid"


class SegmentSchema(BaseModel):
    """Схема для обработки одного сегмента транскрипции"""
    segment_data: Dict[str, str] = Field(default_factory=dict, description="Данные сегмента (ключ=переменная шаблона, значение=строка)")
    speaker_mapping: Dict[str, str] = Field(default_factory=dict, description="Сопоставление SPEAKER_N с именами участников")
    confidence_scores: Dict[str, float] = Field(default_factory=dict, description="Уверенность в сопоставлении для каждого спикера (0.0-1.0)")
    unmapped_speakers: List[str] = Field(default_factory=list, description="Список SPEAKER_N которых не удалось сопоставить")
    mapping_notes: str = Field(default="", description="Заметки по процессу сопоставления")
    segment_confidence: float = Field(default=0.0, description="Уверенность в обработке сегмента (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class SynthesisSchema(BaseModel):
    """Схема для синтеза в chain-of-thought подходе"""
    synthesized_content: Dict[str, str] = Field(default_factory=dict, description="Синтезированный контент (ключ=переменная шаблона, значение=строка)")
    final_speaker_mapping: Dict[str, str] = Field(default_factory=dict, description="Итоговый маппинг SPEAKER_N → имена участников")
    final_confidence_scores: Dict[str, float] = Field(default_factory=dict, description="Итоговая уверенность для каждого спикера (0.0-1.0)")
    final_unmapped_speakers: List[str] = Field(default_factory=list, description="Итоговый список несопоставленных спикеров")
    aggregation_notes: str = Field(default="", description="Заметки по агрегации маппингов из сегментов")
    synthesis_quality: float = Field(default=0.0, description="Качество синтеза (0.0-1.0)")
    synthesis_notes: str = Field(default="", description="Заметки по синтезу")
    
    class Config:
        extra = "forbid"


class SpeakerMappingSchema(BaseModel):
    """Схема для сопоставления спикеров с участниками"""
    speaker_mappings: Dict[str, str] = Field(default_factory=dict, description="Сопоставление speaker_id -> participant_name")
    confidence_scores: Dict[str, float] = Field(default_factory=dict, description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: List[str] = Field(default_factory=list, description="Спикеры, которые не удалось сопоставить")
    mapping_notes: str = Field(default="", description="Заметки по сопоставлению")


# Промежуточные модели для extraction (без поля id, которое генерируется в коде)
class TopicExtraction(BaseModel):
    """Тема обсуждения для extraction (без id)"""
    title: str = Field(..., description="Название темы")
    description: str = Field(default="", description="Описание темы")
    start_time: float = Field(default=0.0, description="Начало обсуждения (секунды)")
    end_time: float = Field(default=0.0, description="Конец обсуждения (секунды)")
    duration: float = Field(default=0.0, description="Длительность обсуждения")
    participants: List[str] = Field(default_factory=list, description="ID участников обсуждения")
    key_points: List[str] = Field(default_factory=list, description="Ключевые моменты")
    sentiment: str = Field(default="", description="Общий тон обсуждения")
    
    class Config:
        extra = "forbid"


class DecisionExtraction(BaseModel):
    """Решение для extraction (без id)"""
    text: str = Field(..., description="Текст решения")
    context: str = Field(default="", description="Контекст принятия решения")
    decision_makers: List[str] = Field(default_factory=list, description="ID спикеров, принявших решение")
    mentioned_speakers: List[str] = Field(default_factory=list, description="Упомянутые спикеры")
    priority: str = Field(default="medium", description="Важность решения: high/medium/low")
    timestamp: float = Field(default=0.0, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"


class ActionItemExtraction(BaseModel):
    """Задача для extraction (без id)"""
    description: str = Field(..., description="Описание задачи")
    assignee: str = Field(default="", description="ID ответственного спикера")
    assignee_name: str = Field(default="", description="Имя ответственного (если извлечено)")
    deadline: str = Field(default="", description="Срок выполнения")
    priority: str = Field(default="medium", description="Приоритет: critical/high/medium/low")
    context: str = Field(default="", description="Контекст задачи")
    timestamp: float = Field(default=0.0, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"


class TopicsExtractionSchema(BaseModel):
    """Схема для извлечения тем обсуждения"""
    topics: List[TopicExtraction] = Field(description="Список извлеченных тем")
    extraction_confidence: float = Field(default=0.0, description="Уверенность в извлечении тем (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class DecisionsExtractionSchema(BaseModel):
    """Схема для извлечения решений"""
    decisions: List[DecisionExtraction] = Field(description="Список извлеченных решений")
    extraction_confidence: float = Field(default=0.0, description="Уверенность в извлечении решений (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class ActionItemsExtractionSchema(BaseModel):
    """Схема для извлечения задач и поручений"""
    action_items: List[ActionItemExtraction] = Field(description="Список извлеченных задач")
    extraction_confidence: float = Field(default=0.0, description="Уверенность в извлечении задач (0.0-1.0)")
    
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
    
    def fix_required_fields(schema_dict: Dict[str, Any]) -> None:
        """
        Рекурсивно исправить required для всех схем.
        
        Azure OpenAI в strict mode не позволяет включать в required поля с additionalProperties
        (т.е. поля типа Dict[str, T]). Такие поля должны быть опциональными.
        Также Azure требует явно установить additionalProperties: false для всех Dict полей.
        """
        if "properties" in schema_dict:
            required_fields = []
            for prop_name, prop_schema in schema_dict["properties"].items():
                # Azure OpenAI требует явно установить additionalProperties: false
                if "additionalProperties" in prop_schema:
                    # Устанавливаем additionalProperties: false для Dict полей
                    prop_schema["additionalProperties"] = False
                else:
                    # Поля без additionalProperties добавляем в required
                    required_fields.append(prop_name)
                
                # Рекурсивно обрабатываем вложенные объекты
                if prop_schema.get("type") == "object" and "properties" in prop_schema:
                    fix_required_fields(prop_schema)
                
                # Обрабатываем массивы с вложенными объектами
                if prop_schema.get("type") == "array" and "items" in prop_schema:
                    items_schema = prop_schema["items"]
                    if isinstance(items_schema, dict):
                        if "additionalProperties" in items_schema:
                            items_schema["additionalProperties"] = False
                        if items_schema.get("type") == "object" and "properties" in items_schema:
                            fix_required_fields(items_schema)
            
            # Устанавливаем required только если есть обязательные поля
            if required_fields:
                schema_dict["required"] = required_fields
        
        # Обработать вложенные схемы в $defs
        if "$defs" in schema_dict:
            for def_name, def_schema in schema_dict["$defs"].items():
                fix_required_fields(def_schema)
    
    fix_required_fields(schema)
    
    # OpenAI требует определенный формат
    return {
        "name": schema.get("title", model_class.__name__),
        "schema": schema,
        "strict": True
    }


# Предопределенные схемы для быстрого доступа
PROTOCOL_SCHEMA = get_json_schema(ProtocolSchema)
TWO_STAGE_EXTRACTION_SCHEMA = get_json_schema(TwoStageExtractionSchema)
TWO_STAGE_REFLECTION_SCHEMA = get_json_schema(TwoStageReflectionSchema)
UNIFIED_PROTOCOL_SCHEMA = get_json_schema(UnifiedProtocolSchema)
SEGMENT_SCHEMA = get_json_schema(SegmentSchema)
SYNTHESIS_SCHEMA = get_json_schema(SynthesisSchema)
SPEAKER_MAPPING_SCHEMA = get_json_schema(SpeakerMappingSchema)
TOPICS_EXTRACTION_SCHEMA = get_json_schema(TopicsExtractionSchema)
DECISIONS_EXTRACTION_SCHEMA = get_json_schema(DecisionsExtractionSchema)
ACTION_ITEMS_EXTRACTION_SCHEMA = get_json_schema(ActionItemsExtractionSchema)


def get_schema_by_type(schema_type: str) -> Dict[str, Any]:
    """
    Получить схему по типу
    
    Args:
        schema_type: Тип схемы ('protocol', 'two_stage_extraction', etc.)
        
    Returns:
        JSON Schema в формате OpenAI
    """
    schemas = {
        'protocol': PROTOCOL_SCHEMA,
        'two_stage_extraction': TWO_STAGE_EXTRACTION_SCHEMA,
        'two_stage_reflection': TWO_STAGE_REFLECTION_SCHEMA,
        'unified_protocol': UNIFIED_PROTOCOL_SCHEMA,
        'segment': SEGMENT_SCHEMA,
        'synthesis': SYNTHESIS_SCHEMA,
        'speaker_mapping': SPEAKER_MAPPING_SCHEMA,
        'topics': TOPICS_EXTRACTION_SCHEMA,
        'decisions': DECISIONS_EXTRACTION_SCHEMA,
        'action_items': ACTION_ITEMS_EXTRACTION_SCHEMA,
    }
    
    if schema_type not in schemas:
        raise ValueError(f"Неизвестный тип схемы: {schema_type}. Доступные: {list(schemas.keys())}")
    
    return schemas[schema_type]
