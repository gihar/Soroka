# Исправление ошибки Azure OpenAI Schema для UnifiedProtocolSchema

## Проблема

При вызове `generate_protocol_unified` с Azure OpenAI возникала ошибка:

```
Invalid schema for response_format 'UnifiedProtocolSchema': 
In context=('properties', 'self_reflection'), 
'additionalProperties' is required to be supplied and to be false.
```

## Причина

Azure OpenAI в strict mode требует, чтобы все объекты (type: object) имели явно установленное поле `additionalProperties: false`, чтобы гарантировать фиксированную структуру. 

Проблема была в том, что поле `self_reflection` было определено как `Dict[str, Any]`, что в JSON Schema превращалось в объект БЕЗ явного `additionalProperties`, что недопустимо для Azure.

## Решение

Создана отдельная Pydantic-модель `SelfReflectionSchema` с фиксированной структурой и `additionalProperties: false`:

### До исправления

```python
class UnifiedProtocolSchema(BaseModel):
    protocol_data: Dict[str, str] = Field(...)
    self_reflection: Dict[str, Any] = Field(...)  # ❌ Нет фиксированной структуры
    # ...
```

### После исправления

```python
class SelfReflectionSchema(BaseModel):
    """Схема для self-reflection (самопроверка модели)"""
    completeness: float = Field(default=0.0, description="Полнота извлечения информации (0.0-1.0)")
    missing_info: List[str] = Field(default_factory=list, description="Список информации, которую не удалось извлечь")
    ambiguous_points: List[str] = Field(default_factory=list, description="Неоднозначные моменты в транскрипции")
    quality_concerns: List[str] = Field(default_factory=list, description="Проблемы качества данных")
    
    class Config:
        extra = "forbid"  # Генерирует additionalProperties: false


class UnifiedProtocolSchema(BaseModel):
    """Схема для unified подхода: извлечение + self-reflection в одном запросе"""
    protocol_data: Dict[str, str] = Field(...)
    self_reflection: SelfReflectionSchema = Field(...)  # ✅ Фиксированная структура
    # ...
```

## Результат JSON Schema

После исправления генерируется корректная JSON Schema:

```json
{
  "name": "UnifiedProtocolSchema",
  "schema": {
    "$defs": {
      "SelfReflectionSchema": {
        "additionalProperties": false,  // ✅ Явно установлено
        "properties": {
          "completeness": {"type": "number", ...},
          "missing_info": {"type": "array", "items": {"type": "string"}, ...},
          "ambiguous_points": {"type": "array", "items": {"type": "string"}, ...},
          "quality_concerns": {"type": "array", "items": {"type": "string"}, ...}
        },
        "required": ["completeness", "missing_info", "ambiguous_points", "quality_concerns"]
      }
    },
    "properties": {
      "protocol_data": {
        "type": "object",
        "additionalProperties": {"type": "string"}  // Динамические ключи разрешены
      },
      "self_reflection": {
        "$ref": "#/$defs/SelfReflectionSchema"  // Ссылка на фиксированную структуру
      },
      // ...
    },
    "required": ["self_reflection", "confidence_score", ...]  // self_reflection обязателен
  },
  "strict": true
}
```

## Изменённые файлы

1. **`src/models/llm_schemas.py`**
   - Добавлена модель `SelfReflectionSchema`
   - Обновлена модель `UnifiedProtocolSchema` для использования `SelfReflectionSchema`

2. **`docs/LLM_PIPELINE_OPTIMIZATION.md`**
   - Обновлена документация схемы

3. **`llm_providers.py`**
   - Промпты уже были корректны (структура self_reflection описана верно)

## Проверка исправления

Для проверки корректности схемы был создан тестовый скрипт, который проверяет:

1. ✅ Структура JSON Schema корректна
2. ✅ `SelfReflectionSchema` имеет `additionalProperties: false`
3. ✅ `protocol_data` допускает динамические ключи (Dict[str, str])
4. ✅ Pydantic модели работают корректно (сериализация/десериализация)
5. ✅ Схема совместима с Azure OpenAI Strict Mode

## Тестирование в production

После деплоя изменений:

1. Отправьте аудиофайл для обработки
2. Подтвердите speaker mapping
3. Убедитесь что генерация протокола проходит успешно без ошибки schema validation

## Дополнительная информация

### Почему Dict[str, str] для protocol_data работает?

`protocol_data` имеет `additionalProperties: {"type": "string"}`, что явно указывает тип значений и НЕ является нарушением strict mode. Azure разрешает динамические ключи, если тип значений явно указан.

### Почему Dict[str, Any] для self_reflection не работал?

`Dict[str, Any]` генерирует объект БЕЗ явного `additionalProperties`, что Azure трактует как неопределённую структуру и отклоняет в strict mode.

### Совместимость с другими провайдерами

Изменения полностью совместимы с:
- ✅ OpenAI API
- ✅ Azure OpenAI
- ✅ OpenRouter и другие OpenAI-совместимые API

Все провайдеры корректно обрабатывают схему с `$ref` на вложенные определения.

