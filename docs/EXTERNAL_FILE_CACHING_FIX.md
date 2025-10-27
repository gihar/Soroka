# Исправление кеширования для внешних файлов

## Дата: 26 октября 2025

## Проблема

При повторной отправке одной и той же ссылки на файл (Google Drive, Яндекс.Диск) кеш полного результата не работал, потому что временные файлы получали случайные имена:

```
Первый раз:  tmpddck_rj0.mov  → ключ кеша: abc123 → Cache MISS
Второй раз:  tmpukcmuv4o.mov → ключ кеша: def456 → Cache MISS
```

Из-за этого при повторной обработке той же ссылки:
- ❌ Транскрипция кешировалась (использует SHA-256 содержимого) ✅
- ❌ LLM генерация НЕ кешировалась (полный результат использовал случайное имя файла)
- ⏱️ Время обработки: ~1-2 минуты вместо 0.1 секунды

## Решение

Использовать **оригинальный URL** в качестве идентификатора для внешних файлов в ключе кеша.

## Изменения

### 1. Модель ProcessingRequest
**Файл:** `src/models/processing.py`

```python
class ProcessingRequest(BaseModel):
    ...
    file_url: Optional[str] = Field(None, description="Оригинальный URL для внешних файлов")
    ...
```

### 2. Генерация ключа кеша
**Файл:** `src/services/optimized_processing_service.py`

```python
def _generate_result_cache_key(self, request: ProcessingRequest) -> str:
    """Генерировать ключ кэша для полного результата"""
    # Для внешних файлов используем оригинальный URL
    # Для Telegram файлов используем file_id
    if request.is_external_file and request.file_url:
        file_identifier = request.file_url
    elif request.file_id:
        file_identifier = request.file_id
    else:
        file_identifier = request.file_path
    
    key_data = {
        "file_identifier": file_identifier,
        "template_id": request.template_id,
        "llm_provider": request.llm_provider,
        "language": request.language,
        "is_external_file": request.is_external_file
    }
    return performance_cache._generate_key("full_result", key_data)
```

### 3. Сохранение URL в state
**Файл:** `src/handlers/message_handlers.py`

```python
# При обработке URL
await state.update_data(
    file_path=temp_path,
    file_name=original_filename,
    file_url=url,  # ← Добавлено
    is_external_file=True
)
```

### 4. Передача URL в ProcessingRequest
**Файлы:** `src/handlers/message_handlers.py`, `src/handlers/callback_handlers.py`

```python
request = ProcessingRequest(
    ...
    file_url=data.get('file_url'),  # ← Добавлено
    ...
)
```

## Результат

### До исправления:
```
Запрос 1 (URL): tmpddck_rj0.mov → cache key: abc123 → MISS → 7-12 мин
Запрос 2 (URL): tmpukcmuv4o.mov → cache key: def456 → MISS → 1-2 мин (только LLM)
```

### После исправления:
```
Запрос 1 (URL): google.com/...file123 → cache key: xyz789 → MISS → 7-12 мин
Запрос 2 (URL): google.com/...file123 → cache key: xyz789 → HIT → 0.1 сек ✅
```

## Ожидаемые логи

### При первом запросе (Cache MISS):
```
INFO | Проверяем кэш для файла
DEBUG | Cache miss: full_result:xyz789...
INFO | Начинаем обработку файла
...
INFO | Кэшируем результат
```

### При втором запросе (Cache HIT):
```
INFO | Проверяем кэш для файла
DEBUG | Cache hit (memory): full_result:xyz789...
INFO | Найден кэшированный результат для filename.mov
```

## Тестирование

Чтобы проверить исправление:

1. Отправить ссылку на Google Drive файл: `https://drive.google.com/file/d/...`
2. Дождаться полной обработки (7-12 минут)
3. Отправить **ту же ссылку** второй раз в течение часа
4. Проверить логи — должно быть "Найден кэшированный результат"
5. Время обработки должно быть ~0.1 секунды

### Команда для проверки логов:
```bash
tail -f logs/bot.log | grep -E "(Cache hit|Cache miss|кэшированный)"
```

## Обратная совместимость

✅ **Telegram файлы** — продолжают работать с `file_id`  
✅ **Локальные файлы** — используют `file_path` как раньше  
✅ **Внешние файлы** — теперь используют `file_url`

## Затронутые файлы

- ✅ `src/models/processing.py` — добавлено поле `file_url`
- ✅ `src/services/optimized_processing_service.py` — изменена логика генерации ключа
- ✅ `src/handlers/message_handlers.py` — сохранение и передача URL
- ✅ `src/handlers/callback_handlers.py` — передача URL из state

## Преимущества

1. ✅ **Ускорение** — повторная обработка за 0.1 сек вместо 1-2 минут
2. ✅ **Экономия** — не нужны повторные вызовы LLM API
3. ✅ **Простота** — минимальные изменения в коде
4. ✅ **Надежность** — URL не меняется, в отличие от временных имен
5. ✅ **Логичность** — URL это естественный идентификатор внешнего файла

## Метрики

- **Экономия времени:** ~1-2 минуты → 0.1 секунды (~1200x быстрее)
- **Экономия токенов:** 0 токенов вместо ~1000-5000 на LLM генерацию
- **Экономия ресурсов:** Не используется CPU/GPU для LLM

## Примечания

- TTL кеша полного результата: **1 час** (по умолчанию для `processing_result`)
- TTL кеша транскрипции: **24 часа**
- Кеш автоматически очищается каждые 30 минут (просроченные записи)
- Максимальный размер кеша в памяти: 512 МБ

---

**Автор:** AI Assistant  
**Статус:** ✅ Реализовано  
**Тестирование:** Требуется проверка с реальными ссылками

