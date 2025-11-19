# OD Протокол - Быстрый старт

## Что это?

**OD протокол** (`od_protokol`) — специальный режим для создания протокола поручений от руководителей.

## Быстрый пример

```python
from src.models.processing import ProcessingRequest

# 1. Подготовьте участников с ролями
participants = [
    {"name": "Иванов Иван", "role": "Директор"},
    {"name": "Петров Петр", "role": "Менеджер"}
]

# 2. Создайте запрос с OD режимом
request = ProcessingRequest(
    file_name="meeting.mp3",
    llm_provider="openai",
    user_id=123,
    processing_mode="od_protokol",  # <-- OD режим
    participants_list=participants
)

# 3. Обработайте через сервис
# result = await service.process_file(request)
```

## Результат

```
ПРОТОКОЛ ПОРУЧЕНИЙ
============================================================
Дата встречи: 19.11.2025

1. Название задачи
   Описание поручения (от Иванов Иван).
   Отв. Петров П. Срок — 25.11.
```

## Требования

✅ `processing_mode = "od_protokol"`  
✅ `participants_list` с ролями  
✅ `llm_provider = "openai"`  
✅ Минимум 1 руководитель (роль содержит: директор, руководитель, начальник, CEO, etc.)

## Тестирование

```bash
python test_od_protocol_simple.py
```

## Документация

Полная документация: [docs/OD_PROTOCOL_MODE.md](docs/OD_PROTOCOL_MODE.md)

## Что было реализовано

- ✅ Схемы данных (ODProtocolSchema, ODProtocolTaskSchema, ODProtocolAssignmentSchema)
- ✅ Поле `processing_mode` в ProcessingRequest
- ✅ Функция генерации `generate_protocol_od()` в llm_providers.py
- ✅ Функция форматирования `format_od_protocol()`
- ✅ Интеграция в OptimizedProcessingService
- ✅ Специализированные промпты для OD режима
- ✅ Автоматическое определение руководителей по ролям
- ✅ Группировка поручений по задачам/проектам
- ✅ Извлечение ответственных и сроков

## Измененные файлы

1. `src/models/llm_schemas.py` — добавлены схемы OD протокола
2. `src/models/processing.py` — добавлено поле `processing_mode`
3. `llm_providers.py` — добавлены функции генерации и форматирования OD протокола
4. `src/services/optimized_processing_service.py` — интегрирован OD режим

## Примеры использования

Смотрите файлы:
- `test_od_protocol_simple.py` — простые unit-тесты
- `test_od_protocol.py` — полные тесты (требует все зависимости)
- `docs/OD_PROTOCOL_MODE.md` — подробная документация

