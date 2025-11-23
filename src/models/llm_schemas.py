"""
JSON Schema модели для OpenAI Structured Outputs
"""

from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
import json




class ProtocolSchema(BaseModel):
    """
    Схема для основного протокола встречи
    
    ВАЖНО: Все поля - строки! Промпт явно требует:
    "Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов"
    """
    meeting_title: str = Field(description="Название встречи")
    meeting_date: str = Field(default="", description="Дата встречи")
    meeting_time: str = Field(default="", description="Время встречи")
    participants: str = Field(description="Список участников (каждое имя с новой строки через \\n)")
    agenda: str = Field(description="Повестка дня (пункты списком через \\n)")
    key_points: str = Field(description="Ключевые моменты (пункты списком через \\n)")
    decisions: str = Field(description="Принятые решения (каждое с новой строки через \\n)")
    action_items: str = Field(description="Задачи и поручения (каждая с новой строки через \\n)")
    next_meeting: str = Field(default="", description="Информация о следующей встрече")
    additional_notes: str = Field(default="", description="Дополнительные заметки")
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


class SelfReflectionSchema(BaseModel):
    """Схема для self-reflection (самопроверка модели)"""
    completeness: float = Field(default=0.0, description="Полнота извлечения информации (0.0-1.0)")
    missing_info: List[str] = Field(default_factory=list, description="Список информации, которую не удалось извлечь")
    ambiguous_points: List[str] = Field(default_factory=list, description="Неоднозначные моменты в транскрипции")
    quality_concerns: List[str] = Field(default_factory=list, description="Проблемы качества данных")

    class Config:
        extra = "forbid"




class UnifiedProtocolSchema(BaseModel):
    """Схема для unified подхода: извлечение + self-reflection в одном запросе"""
    protocol_data: Dict[str, str] = Field(default_factory=dict, description="Извлеченные данные протокола (ключ=переменная шаблона, значение=строка)")
    self_reflection: SelfReflectionSchema = Field(default_factory=SelfReflectionSchema)
    confidence_score: float = Field(default=0.0, description="Общая уверенность (0.0-1.0)")
    quality_notes: str = Field(default="", description="Заметки по качеству")
    detected_speaker_mapping: Optional[Dict[str, str]] = Field(default=None, description="Автоопределенное сопоставление SPEAKER_N с именами участников")
    speaker_confidence_scores: Optional[Dict[str, float]] = Field(default=None, description="Уверенность в сопоставлении для каждого спикера")
    unmapped_speakers: Optional[List[str]] = Field(default=None, description="Спикеры которых не удалось сопоставить")
    mapping_notes: Optional[str] = Field(default=None, description="Заметки по автоопределению участников")
    
    class Config:
        extra = "forbid"




class SpeakerMappingSchema(BaseModel):
    """Схема для сопоставления спикеров с участниками"""
    speaker_mappings: Dict[str, str] = Field(
        description="Сопоставление speaker_id -> participant_name в формате 'Имя Фамилия' (БЕЗ отчества)"
    )
    confidence_scores: Dict[str, float] = Field(
        description="Уверенность в сопоставлении для каждого спикера (0.0-1.0). Только спикеры с уверенностью >= 0.7 включаются в speaker_mappings"
    )
    unmapped_speakers: List[str] = Field(
        description="Список speaker_id (например, SPEAKER_3) с уверенностью < 0.7, которых не удалось надежно сопоставить с участниками"
    )
    mapping_notes: str = Field(description="Заметки по сопоставлению")


















class ODProtocolSchema(BaseModel):
    """Схема для OD протокола (протокол поручений руководителей)"""
    tasks: List[Dict[str, str]] = Field(default_factory=list, description="Список задач/проектов с данными")
    meeting_date: Optional[str] = Field(default=None, description="Дата встречи")
    participants: Optional[str] = Field(default=None, description="Список участников через запятую")
    managers: Optional[str] = Field(default=None, description="Список руководителей через запятую")
    additional_notes: Optional[str] = Field(default=None, description="Дополнительные заметки")

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
SPEAKER_MAPPING_SCHEMA = get_json_schema(SpeakerMappingSchema)
OD_PROTOCOL_SCHEMA = get_json_schema(ODProtocolSchema)


class ExtractionSchema(BaseModel):
    """
    Схема для первого запроса: сопоставление спикеров + извлечение структуры встречи
    """
    # Speaker mapping results
    speaker_mappings: Dict[str, str] = Field(
        default_factory=dict,
        description="Сопоставление SPEAKER_N → 'Имя Фамилия' для спикеров с уверенностью >= 0.7"
    )
    speaker_confidence_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Уверенность в сопоставлении для каждого спикера (0.0-1.0)"
    )
    unmapped_speakers: List[str] = Field(
        default_factory=list,
        description="Список SPEAKER_N с уверенностью < 0.7, которых не удалось надежно сопоставить"
    )
    mapping_notes: str = Field(
        default="",
        description="Заметки по процессу сопоставления спикеров"
    )

    # Meeting structure extraction results
    meeting_title: str = Field(default="", description="Название встречи")
    meeting_type: str = Field(default="", description="Тип встречи определенный из анализа (technical, business, educational, brainstorm, status, general)")
    meeting_date: str = Field(default="", description="Дата встречи")
    meeting_time: str = Field(default="", description="Время встречи")
    participants: str = Field(default="", description="Список участников (каждое с новой строки через \\n)")
    agenda: str = Field(default="", description="Повестка дня (пункты списком через \\n)")
    discussion: str = Field(default="", description="Подробное обсуждение по темам (структурированный текст с атрибуцией высказываний через \\n)")
    key_points: str = Field(default="", description="Краткие итоги и выводы (пункты списком через \\n)")
    decisions: str = Field(default="", description="Принятые решения (каждое с новой строки через \\n)")
    action_items: str = Field(default="", description="Задачи и поручения (каждая с новой строки через \\n)")
    next_meeting: str = Field(default="", description="Информация о следующей встрече")
    additional_notes: str = Field(default="", description="Дополнительные заметки")

    # Quality assessment
    extraction_confidence: float = Field(default=0.0, description="Общая уверенность в извлечении (0.0-1.0)")
    missing_elements: List[str] = Field(
        default_factory=list,
        description="Элементы протокола, которые не удалось извлечь из транскрипции"
    )
    quality_issues: List[str] = Field(
        default_factory=list,
        description="Выявленные проблемы качества (неоднозначность, противоречия и т.д.)"
    )
    extraction_notes: str = Field(
        default="",
        description="Общие заметки по процессу извлечения"
    )

    # Compatibility fields for templates
    date: str = Field(default="", description="Дата встречи (alias для meeting_date)")
    time: str = Field(default="", description="Время встречи (alias для meeting_time)")
    managers: str = Field(default="", description="Список руководителей через запятую")
    platform: str = Field(default="", description="Платформа проведения (для онлайн-встреч)")

    # Additional fields used by templates
    tasks: str = Field(default="", description="Задачи и распределение ответственности")
    next_steps: str = Field(default="", description="Следующие шаги и контрольные точки")
    deadlines: str = Field(default="", description="Сроки выполнения задач")
    issues: str = Field(default="", description="Выявленные проблемы и вопросы")
    questions: str = Field(default="", description="Открытые вопросы")
    risks_and_blockers: str = Field(default="", description="Риски и блокеры")
    technical_issues: str = Field(default="", description="Технические вопросы и проблемы")
    architecture_decisions: str = Field(default="", description="Архитектурные решения")
    technical_tasks: str = Field(default="", description="Технические задачи")
    speaker_contributions: str = Field(default="", description="Вклад каждого участника")
    dialogue_analysis: str = Field(default="", description="Анализ диалога и взаимодействия")
    speakers_summary: str = Field(default="", description="Краткая характеристика участников")
    learning_objectives: str = Field(default="", description="Цели обучения (для образовательных встреч)")
    key_concepts: str = Field(default="", description="Ключевые концепции и определения")
    examples_and_cases: str = Field(default="", description="Примеры и кейсы")
    practical_exercises: str = Field(default="", description="Практические упражнения")
    homework: str = Field(default="", description="Домашнее задание")
    materials: str = Field(default="", description="Материалы и ресурсы")
    next_sprint_plans: str = Field(default="", description="Планы на следующий спринт")

    # Educational template specific fields
    professional_secrets: str = Field(default="", description="Профессиональные секреты и лайфхаки")
    audience_practice: str = Field(default="", description="Практика под руководством мастера")
    group_formation: str = Field(default="", description="Формирование групп")
    group_results: str = Field(default="", description="Результаты работы групп")
    peer_feedback: str = Field(default="", description="Взаимная обратная связь")
    individual_reflections: str = Field(default="", description="Индивидуальные рефлексии")
    poll_results: str = Field(default="", description="Результаты опросов и голосований")
    chat_questions: str = Field(default="", description="Вопросы из чата")
    live_demonstration: str = Field(default="", description="Демонстрация в реальном времени")
    downloadable_materials: str = Field(default="", description="Материалы для скачивания")
    additional_materials: str = Field(default="", description="Дополнительные материалы и ресурсы")

    # Additional educational fields
    practical_demonstration: str = Field(default="", description="Практическая демонстрация")
    feedback_session: str = Field(default="", description="Сессия обратной связи")
    group_work: str = Field(default="", description="Работа в группах")
    controversial_points: str = Field(default="", description="Ключевые точки мнений")
    participant_contributions: str = Field(default="", description="Вклад участников")
    questions_and_answers: str = Field(default="", description="Вопросы и ответы")

    class Config:
        extra = "forbid"


class ConsolidatedProtocolSchema(BaseModel):
    """
    Консолидированная схема для второго запроса: финальная генерация протокола + QA
    """
    # Final protocol fields (with template formatting)
    meeting_title: str = Field(default="", description="Название встречи")
    meeting_date: str = Field(default="", description="Дата встречи")
    meeting_time: str = Field(default="", description="Время встречи")
    participants: str = Field(default="", description="Список участников (каждое имя с новой строки через \\n)")
    agenda: str = Field(default="", description="Повестка дня (пункты списком через \\n)")
    discussion: str = Field(default="", description="Подробное обсуждение по темам (структурированный текст с атрибуцией высказываний через \\n)")
    key_points: str = Field(default="", description="Краткие итоги и выводы (пункты списком через \\n)")
    decisions: str = Field(default="", description="Принятые решения (каждое с новой строки через \\n)")
    action_items: str = Field(default="", description="Задачи и поручения (каждая с новой строки через \\n)")
    next_meeting: str = Field(default="", description="Информация о следующей встрече")
    additional_notes: str = Field(default="", description="Дополнительные заметки")

    # Enhanced speaker mapping with verified names
    verified_speaker_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Проверенное сопоставление SPEAKER_N → 'Имя Фамилия'"
    )
    speaker_mapping_confidence: float = Field(
        default=0.0,
        description="Общая уверенность в сопоставлении спикеров (0.0-1.0)"
    )

    # Quality assurance and validation
    protocol_quality_score: float = Field(
        default=0.0,
        description="Общая оценка качества протокола (0.0-1.0)"
    )
    consistency_checks: Dict[str, bool] = Field(
        default_factory=dict,
        description="Результаты проверок на согласованность (participants_consistent, dates_valid, etc.)"
    )
    completeness_assessment: str = Field(
        default="",
        description="Оценка полноты протокола"
    )
    improvement_suggestions: List[str] = Field(
        default_factory=list,
        description="Предложения по улучшению протокола"
    )
    self_reflection_notes: str = Field(
        default="",
        description="Заметки саморефлексии по качеству генерации"
    )

    # Meeting classification and type-specific data
    meeting_type: str = Field(
        default="general",
        description="Тип встречи (general, technical, business, educational, brainstorm, status)"
    )
    type_specific_observations: str = Field(
        default="",
        description="Специфичные наблюдения для типа встречи"
    )

    # Compatibility fields for templates
    date: str = Field(default="", description="Дата встречи (alias для meeting_date)")
    time: str = Field(default="", description="Время встречи (alias для meeting_time)")
    managers: str = Field(default="", description="Список руководителей через запятую")
    platform: str = Field(default="", description="Платформа проведения (для онлайн-встреч)")

    # Additional fields used by templates
    tasks: str = Field(default="", description="Задачи и распределение ответственности")
    next_steps: str = Field(default="", description="Следующие шаги и контрольные точки")
    deadlines: str = Field(default="", description="Сроки выполнения задач")
    issues: str = Field(default="", description="Выявленные проблемы и вопросы")
    questions: str = Field(default="", description="Открытые вопросы")
    risks_and_blockers: str = Field(default="", description="Риски и блокеры")
    technical_issues: str = Field(default="", description="Технические вопросы и проблемы")
    architecture_decisions: str = Field(default="", description="Архитектурные решения")
    technical_tasks: str = Field(default="", description="Технические задачи")
    speaker_contributions: str = Field(default="", description="Вклад каждого участника")
    dialogue_analysis: str = Field(default="", description="Анализ диалога и взаимодействия")
    speakers_summary: str = Field(default="", description="Краткая характеристика участников")
    learning_objectives: str = Field(default="", description="Цели обучения (для образовательных встреч)")
    key_concepts: str = Field(default="", description="Ключевые концепции и определения")
    examples_and_cases: str = Field(default="", description="Примеры и кейсы")
    practical_exercises: str = Field(default="", description="Практические упражнения")
    homework: str = Field(default="", description="Домашнее задание")
    materials: str = Field(default="", description="Материалы и ресурсы")
    next_sprint_plans: str = Field(default="", description="Планы на следующий спринт")

    # Educational template specific fields
    professional_secrets: str = Field(default="", description="Профессиональные секреты и лайфхаки")
    audience_practice: str = Field(default="", description="Практика под руководством мастера")
    group_formation: str = Field(default="", description="Формирование групп")
    group_results: str = Field(default="", description="Результаты работы групп")
    peer_feedback: str = Field(default="", description="Взаимная обратная связь")
    individual_reflections: str = Field(default="", description="Индивидуальные рефлексии")
    poll_results: str = Field(default="", description="Результаты опросов и голосований")
    chat_questions: str = Field(default="", description="Вопросы из чата")
    live_demonstration: str = Field(default="", description="Демонстрация в реальном времени")
    downloadable_materials: str = Field(default="", description="Материалы для скачивания")
    additional_materials: str = Field(default="", description="Дополнительные материалы и ресурсы")

    # Additional educational fields
    practical_demonstration: str = Field(default="", description="Практическая демонстрация")
    feedback_session: str = Field(default="", description="Сессия обратной связи")
    group_work: str = Field(default="", description="Работа в группах")
    controversial_points: str = Field(default="", description="Ключевые точки мнений")
    participant_contributions: str = Field(default="", description="Вклад участников")
    questions_and_answers: str = Field(default="", description="Вопросы и ответы")

    class Config:
        extra = "forbid"


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
        'speaker_mapping': SPEAKER_MAPPING_SCHEMA,
        'od_protocol': OD_PROTOCOL_SCHEMA,
        # New consolidated schemas for two-request approach
        'extraction': get_json_schema(ExtractionSchema),
        'consolidated_protocol': get_json_schema(ConsolidatedProtocolSchema),
    }

    if schema_type not in schemas:
        raise ValueError(f"Неизвестный тип схемы: {schema_type}. Доступные: {list(schemas.keys())}")

    return schemas[schema_type]
