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
    
    class Config:
        extra = "forbid"


class TwoStageExtractionSchema(BaseModel):
    """Схема для первого этапа двухэтапной генерации (извлечение)"""
    extracted_data: Dict[str, str] = Field(description="Извлеченные данные из транскрипции (ключ=переменная шаблона, значение=строка)")
    confidence_score: Optional[float] = Field(default=None, description="Уровень уверенности в извлечении (0.0-1.0)")
    extraction_notes: Optional[str] = Field(default=None, description="Заметки по извлечению")
    
    class Config:
        extra = "forbid"


class TwoStageReflectionSchema(BaseModel):
    """Схема для второго этапа двухэтапной генерации (рефлексия)"""
    refined_data: Dict[str, str] = Field(description="Уточненные данные после рефлексии (ключ=переменная шаблона, значение=строка)")
    reflection_notes: Optional[str] = Field(default=None, description="Заметки по рефлексии")
    quality_score: Optional[float] = Field(default=None, description="Оценка качества результата (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class SegmentSchema(BaseModel):
    """Схема для обработки одного сегмента транскрипции"""
    segment_data: Dict[str, str] = Field(description="Данные сегмента (ключ=переменная шаблона, значение=строка)")
    speaker_id: Optional[str] = Field(default=None, description="ID спикера")
    segment_confidence: Optional[float] = Field(default=None, description="Уверенность в обработке сегмента (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class SynthesisSchema(BaseModel):
    """Схема для синтеза в chain-of-thought подходе"""
    synthesized_content: Dict[str, str] = Field(description="Синтезированный контент (ключ=переменная шаблона, значение=строка)")
    synthesis_quality: Optional[float] = Field(default=None, description="Качество синтеза (0.0-1.0)")
    synthesis_notes: Optional[str] = Field(default=None, description="Заметки по синтезу")
    
    class Config:
        extra = "forbid"


class SpeakerMappingSchema(BaseModel):
    """Схема для сопоставления спикеров с участниками"""
    speaker_mappings: Dict[str, str] = Field(description="Сопоставление speaker_id -> participant_name")
    confidence_scores: Dict[str, float] = Field(description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: List[str] = Field(description="Спикеры, которые не удалось сопоставить")
    mapping_notes: Optional[str] = Field(default=None, description="Заметки по сопоставлению")


# Промежуточные модели для extraction (без поля id, которое генерируется в коде)
class TopicExtraction(BaseModel):
    """Тема обсуждения для extraction (без id)"""
    title: str = Field(..., description="Название темы")
    description: str = Field(default="", description="Описание темы")
    start_time: Optional[float] = Field(default=None, description="Начало обсуждения (секунды)")
    end_time: Optional[float] = Field(default=None, description="Конец обсуждения (секунды)")
    duration: Optional[float] = Field(default=None, description="Длительность обсуждения")
    participants: List[str] = Field(default_factory=list, description="ID участников обсуждения")
    key_points: List[str] = Field(default_factory=list, description="Ключевые моменты")
    sentiment: Optional[str] = Field(default=None, description="Общий тон обсуждения")
    
    class Config:
        extra = "forbid"


class DecisionExtraction(BaseModel):
    """Решение для extraction (без id)"""
    text: str = Field(..., description="Текст решения")
    context: str = Field(default="", description="Контекст принятия решения")
    decision_makers: List[str] = Field(default_factory=list, description="ID спикеров, принявших решение")
    mentioned_speakers: List[str] = Field(default_factory=list, description="Упомянутые спикеры")
    priority: Optional[str] = Field("medium", description="Важность решения: high/medium/low")
    timestamp: Optional[float] = Field(default=None, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"


class ActionItemExtraction(BaseModel):
    """Задача для extraction (без id)"""
    description: str = Field(..., description="Описание задачи")
    assignee: Optional[str] = Field(default=None, description="ID ответственного спикера")
    assignee_name: Optional[str] = Field(default=None, description="Имя ответственного (если извлечено)")
    deadline: Optional[str] = Field(default=None, description="Срок выполнения")
    priority: Optional[str] = Field("medium", description="Приоритет: critical/high/medium/low")
    context: str = Field(default="", description="Контекст задачи")
    timestamp: Optional[float] = Field(default=None, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"


class TopicsExtractionSchema(BaseModel):
    """Схема для извлечения тем обсуждения"""
    topics: List[TopicExtraction] = Field(description="Список извлеченных тем")
    extraction_confidence: Optional[float] = Field(default=None, description="Уверенность в извлечении тем (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class DecisionsExtractionSchema(BaseModel):
    """Схема для извлечения решений"""
    decisions: List[DecisionExtraction] = Field(description="Список извлеченных решений")
    extraction_confidence: Optional[float] = Field(default=None, description="Уверенность в извлечении решений (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class ActionItemsExtractionSchema(BaseModel):
    """Схема для извлечения задач и поручений"""
    action_items: List[ActionItemExtraction] = Field(description="Список извлеченных задач")
    extraction_confidence: Optional[float] = Field(default=None, description="Уверенность в извлечении задач (0.0-1.0)")
    
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
