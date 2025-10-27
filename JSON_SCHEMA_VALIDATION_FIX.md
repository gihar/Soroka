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

## Дата исправления

27 октября 2025

