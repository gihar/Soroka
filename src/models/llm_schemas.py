"""
JSON Schema модели для OpenAI Structured Outputs
"""

from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
import json


class ProtocolSchema(BaseModel):
    """Схема для основного протокола встречи"""
    meeting_title: str = Field(description="Название встречи")
    meeting_date: Optional[str] = Field(None, description="Дата встречи")
    meeting_time: Optional[str] = Field(None, description="Время встречи")
    participants: List[Dict[str, str]] = Field(description="Список участников")
    agenda: List[str] = Field(description="Повестка дня")
    key_points: List[str] = Field(description="Ключевые моменты")
    decisions: List[Dict[str, Any]] = Field(description="Принятые решения")
    action_items: List[Dict[str, Any]] = Field(description="Задачи и поручения")
    next_meeting: Optional[Dict[str, str]] = Field(None, description="Следующая встреча")
    additional_notes: Optional[str] = Field(None, description="Дополнительные заметки")


class TwoStageExtractionSchema(BaseModel):
    """Схема для первого этапа двухэтапной генерации (извлечение)"""
    extracted_data: Dict[str, Any] = Field(description="Извлеченные данные из транскрипции")
    confidence_score: float = Field(description="Уровень уверенности в извлечении (0.0-1.0)")
    extraction_notes: Optional[str] = Field(None, description="Заметки по извлечению")


class TwoStageReflectionSchema(BaseModel):
    """Схема для второго этапа двухэтапной генерации (рефлексия)"""
    refined_data: Dict[str, Any] = Field(description="Уточненные данные после рефлексии")
    reflection_notes: Optional[str] = Field(None, description="Заметки по рефлексии")
    quality_score: float = Field(description="Оценка качества результата (0.0-1.0)")


class SegmentSchema(BaseModel):
    """Схема для обработки одного сегмента транскрипции"""
    segment_data: Dict[str, Any] = Field(description="Данные сегмента")
    speaker_id: Optional[str] = Field(None, description="ID спикера")
    segment_confidence: float = Field(description="Уверенность в обработке сегмента (0.0-1.0)")


class SynthesisSchema(BaseModel):
    """Схема для синтеза в chain-of-thought подходе"""
    synthesized_content: Dict[str, Any] = Field(description="Синтезированный контент")
    synthesis_quality: float = Field(description="Качество синтеза (0.0-1.0)")
    synthesis_notes: Optional[str] = Field(None, description="Заметки по синтезу")


class SpeakerMappingSchema(BaseModel):
    """Схема для сопоставления спикеров с участниками"""
    speaker_mappings: Dict[str, str] = Field(description="Сопоставление speaker_id -> participant_name")
    confidence_scores: Dict[str, float] = Field(description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: List[str] = Field(description="Спикеры, которые не удалось сопоставить")
    mapping_notes: Optional[str] = Field(None, description="Заметки по сопоставлению")


class TopicsExtractionSchema(BaseModel):
    """Схема для извлечения тем обсуждения"""
    topics: List[Dict[str, Any]] = Field(description="Список извлеченных тем")
    extraction_confidence: float = Field(description="Уверенность в извлечении тем (0.0-1.0)")


class DecisionsExtractionSchema(BaseModel):
    """Схема для извлечения решений"""
    decisions: List[Dict[str, Any]] = Field(description="Список извлеченных решений")
    extraction_confidence: float = Field(description="Уверенность в извлечении решений (0.0-1.0)")


class ActionItemsExtractionSchema(BaseModel):
    """Схема для извлечения задач и поручений"""
    action_items: List[Dict[str, Any]] = Field(description="Список извлеченных задач")
    extraction_confidence: float = Field(description="Уверенность в извлечении задач (0.0-1.0)")


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
