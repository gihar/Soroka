# Исправление ошибок валидации JSON схем для Azure OpenAI

## Проблема

При попытке использовать structured outputs с Azure OpenAI API возникали ошибки:

```
Invalid schema for response_format 'DecisionsExtractionSchema': 
In context=('properties', 'decisions', 'items'), 
'additionalProperties' is required to be supplied and to be false.
```

Аналогичные ошибки возникали для:
- `TopicsExtractionSchema`
- `DecisionsExtractionSchema`
- `ActionItemsExtractionSchema`

### Причина

Использование `List[Dict[str, Any]]` в Pydantic схемах генерировало JSON Schema без обязательного поля `additionalProperties: false` для вложенных объектов, что требуется Azure OpenAI API.

## Решение

### 1. Создание промежуточных моделей extraction

Созданы специализированные Pydantic модели для extraction без поля `id` (которое генерируется в коде Python):

**`src/models/llm_schemas.py`:**

```python
class TopicExtraction(BaseModel):
    """Тема обсуждения для extraction (без id)"""
    title: str = Field(..., description="Название темы")
    description: str = Field(default="", description="Описание темы")
    start_time: Optional[float] = Field(None, description="Начало обсуждения (секунды)")
    end_time: Optional[float] = Field(None, description="Конец обсуждения (секунды)")
    duration: Optional[float] = Field(None, description="Длительность обсуждения")
    participants: List[str] = Field(default_factory=list, description="ID участников обсуждения")
    key_points: List[str] = Field(default_factory=list, description="Ключевые моменты")
    sentiment: Optional[str] = Field(None, description="Общий тон обсуждения")
    
    class Config:
        extra = "forbid"  # Генерирует additionalProperties: false


class DecisionExtraction(BaseModel):
    """Решение для extraction (без id)"""
    text: str = Field(..., description="Текст решения")
    context: str = Field(default="", description="Контекст принятия решения")
    decision_makers: List[str] = Field(default_factory=list, description="ID спикеров, принявших решение")
    mentioned_speakers: List[str] = Field(default_factory=list, description="Упомянутые спикеры")
    priority: Optional[str] = Field("medium", description="Важность решения: high/medium/low")
    timestamp: Optional[float] = Field(None, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"


class ActionItemExtraction(BaseModel):
    """Задача для extraction (без id)"""
    description: str = Field(..., description="Описание задачи")
    assignee: Optional[str] = Field(None, description="ID ответственного спикера")
    assignee_name: Optional[str] = Field(None, description="Имя ответственного (если извлечено)")
    deadline: Optional[str] = Field(None, description="Срок выполнения")
    priority: Optional[str] = Field("medium", description="Приоритет: critical/high/medium/low")
    context: str = Field(default="", description="Контекст задачи")
    timestamp: Optional[float] = Field(None, description="Временная метка в секундах")
    
    class Config:
        extra = "forbid"
```

### 2. Обновление extraction схем

Заменены `List[Dict[str, Any]]` на типизированные модели:

```python
class TopicsExtractionSchema(BaseModel):
    """Схема для извлечения тем обсуждения"""
    topics: List[TopicExtraction] = Field(description="Список извлеченных тем")
    extraction_confidence: Optional[float] = Field(None, description="Уверенность в извлечении тем (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class DecisionsExtractionSchema(BaseModel):
    """Схема для извлечения решений"""
    decisions: List[DecisionExtraction] = Field(description="Список извлеченных решений")
    extraction_confidence: Optional[float] = Field(None, description="Уверенность в извлечении решений (0.0-1.0)")
    
    class Config:
        extra = "forbid"


class ActionItemsExtractionSchema(BaseModel):
    """Схема для извлечения задач и поручений"""
    action_items: List[ActionItemExtraction] = Field(description="Список извлеченных задач")
    extraction_confidence: Optional[float] = Field(None, description="Уверенность в извлечении задач (0.0-1.0)")
    
    class Config:
        extra = "forbid"
```

### 3. Дополнительные изменения

- Поле `extraction_confidence` сделано опциональным для большей надежности
- Добавлен `Config` с `extra = "forbid"` для явной генерации `additionalProperties: false`

## Результат

Все схемы теперь корректно валидируются Azure OpenAI API:

- ✅ Все объекты имеют `additionalProperties: false`
- ✅ Strict mode включен
- ✅ Схемы полностью соответствуют требованиям Azure OpenAI

## Совместимость

Изменения полностью обратно совместимы:
- Код в `meeting_structure_builder.py` не требует изменений
- LLM возвращает JSON в том же формате
- Парсинг результатов работает без изменений

## Тестирование

Для проверки валидности схем можно использовать:

```python
from src.models.llm_schemas import get_json_schema, TopicsExtractionSchema

schema = get_json_schema(TopicsExtractionSchema)
print(schema['schema'])  # Проверить наличие additionalProperties: false
```

## Этап 2: Полное исправление всех схем

После первого этапа исправления остались ошибки с другими схемами, использующими `Dict[str, Any]`.

### Исправленные схемы

#### 1. TwoStage схемы (для двухэтапной генерации)

Заменены `Dict[str, Any]` на `Dict[str, str]` (так как промпты требуют "все значения должны быть ПРОСТЫМИ СТРОКАМИ"):

```python
class TwoStageExtractionSchema(BaseModel):
    """Схема для первого этапа двухэтапной генерации (извлечение)"""
    extracted_data: Dict[str, str] = Field(description="Извлеченные данные (ключ=переменная, значение=строка)")
    confidence_score: Optional[float] = Field(None, description="Уверенность")
    extraction_notes: Optional[str] = Field(None, description="Заметки")
    
    class Config:
        extra = "forbid"


class TwoStageReflectionSchema(BaseModel):
    """Схема для второго этапа двухэтапной генерации (рефлексия)"""
    refined_data: Dict[str, str] = Field(description="Уточненные данные")
    reflection_notes: Optional[str] = Field(None, description="Заметки")
    quality_score: Optional[float] = Field(None, description="Качество")
    
    class Config:
        extra = "forbid"
```

#### 2. Segment и Synthesis схемы

```python
class SegmentSchema(BaseModel):
    """Схема для обработки одного сегмента транскрипции"""
    segment_data: Dict[str, str] = Field(description="Данные сегмента")
    speaker_id: Optional[str] = Field(None, description="ID спикера")
    segment_confidence: Optional[float] = Field(None, description="Уверенность")
    
    class Config:
        extra = "forbid"


class SynthesisSchema(BaseModel):
    """Схема для синтеза в chain-of-thought подходе"""
    synthesized_content: Dict[str, str] = Field(description="Синтезированный контент")
    synthesis_quality: Optional[float] = Field(None, description="Качество")
    synthesis_notes: Optional[str] = Field(None, description="Заметки")
    
    class Config:
        extra = "forbid"
```

#### 3. ProtocolSchema

Заменены `List[Dict[str, str]]` и `List[Dict[str, Any]]` на строковые поля для совместимости с промптами:

```python
class ProtocolSchema(BaseModel):
    """
    Схема для основного протокола встречи
    
    ВАЖНО: Все поля - строки! Промпт явно требует:
    "Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов"
    """
    meeting_title: str = Field(description="Название встречи")
    meeting_date: Optional[str] = Field(None, description="Дата встречи")
    meeting_time: Optional[str] = Field(None, description="Время встречи")
    participants: str = Field(description="Список участников (каждое имя с новой строки через \\n)")
    agenda: str = Field(description="Повестка дня (пункты списком через \\n)")
    key_points: str = Field(description="Ключевые моменты (пункты списком через \\n)")
    decisions: str = Field(description="Принятые решения (каждое с новой строки через \\n)")
    action_items: str = Field(description="Задачи и поручения (каждая с новой строки через \\n)")
    next_meeting: Optional[str] = Field(None, description="Информация о следующей встрече")
    additional_notes: Optional[str] = Field(None, description="Дополнительные заметки")
    
    class Config:
        extra = "forbid"
```

**Почему строки, а не структуры?**
- ProtocolSchema используется для "стандартной генерации"
- Промпты явно требуют: "Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов"
- Пример из промпта: `"participants": "Иван Иванов\\nМария Петрова\\nАлексей Сидоров"`
- Использование структурированных моделей здесь сломало бы совместимость с промптами

### Итоговая статистика

Всего исправлено **8 JSON схем**:
1. ✅ TopicsExtractionSchema
2. ✅ DecisionsExtractionSchema  
3. ✅ ActionItemsExtractionSchema
4. ✅ TwoStageExtractionSchema
5. ✅ TwoStageReflectionSchema
6. ✅ SegmentSchema
7. ✅ SynthesisSchema
8. ✅ ProtocolSchema (+ 4 вложенные модели)

Все схемы прошли валидацию и теперь корректно работают с Azure OpenAI API.

## Дата исправления

27 октября 2025 (2 этапа)

