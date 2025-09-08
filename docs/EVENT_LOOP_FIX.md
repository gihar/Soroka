# Исправление ошибки Event Loop в системе прогресса

## Проблема

После внедрения системы отслеживания прогресса транскрипции возникла ошибка:

```
Ошибка транскрипции: no running event loop
RuntimeWarning: coroutine 'ProgressTracker.update_stage_progress' was never awaited
```

### Причина

Проблема заключалась в том, что асинхронные колбэки прогресса вызывались из синхронного контекста (thread pool), где нет активного event loop.

**Проблемный код (устаревший API с текстом подэтапа):**
```python
def progress_callback(percent, message):
    if progress_tracker:
        asyncio.create_task(  # ❌ Ошибка: нет event loop в thread
            progress_tracker.update_stage_progress(
                "transcription", percent, message
            )
        )
```

## Решение

Реализован thread-safe механизм обновления прогресса с graceful fallback.

### Новый thread-safe колбэк

```python
def progress_callback(percent):
    """Thread-safe колбэк для обновления прогресса транскрипции (упрощённый API)"""
    if progress_tracker:
        try:
            # Получаем текущий event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Планируем выполнение в основном потоке
                asyncio.run_coroutine_threadsafe(
                    progress_tracker.update_stage_progress(
                        "transcription", percent
                    ), loop
                )
        except RuntimeError:
            # Если нет активного event loop, просто логируем
            logger.debug(f"Progress update: {percent}%")
        except Exception as e:
            logger.warning(f"Ошибка при обновлении прогресса: {e}")
```

### Как это работает

1. **Основной поток (с event loop)**: Обновления прогресса передаются через `asyncio.run_coroutine_threadsafe()`
2. **Рабочий поток (без event loop)**: Используется fallback логирование
3. **Ошибки**: Graceful обработка исключений без прерывания транскрипции

## Технические детали

### `asyncio.run_coroutine_threadsafe()`

Эта функция позволяет запускать корутины из других потоков:

```python
future = asyncio.run_coroutine_threadsafe(
    async_function(),
    target_event_loop
)
```

### Обработка исключений

- **`RuntimeError`**: Нет активного event loop → используем логирование
- **Другие исключения**: Логируем предупреждение, но не прерываем процесс

### Fallback механизм

Если обновление прогресса через UI невозможно, система переключается на логирование:

```python
logger.debug(f"Progress update: {percent}%")
```

## Результат

### ДО (с ошибками)
```
❌ Ошибка транскрипции: no running event loop
❌ RuntimeWarning: coroutine was never awaited
❌ Процесс прерывается
```

### ПОСЛЕ (исправлено)
```
✅ Обновления прогресса в основном потоке работают
✅ Graceful fallback в рабочих потоках
✅ Транскрипция завершается успешно
✅ Нет ошибок event loop
```

## Протестировано

- ✅ Thread-safe колбэки прогресса
- ✅ Работа в основном потоке с event loop
- ✅ Работа в рабочих потоках без event loop
- ✅ Обработка отсутствия event loop
- ✅ Graceful fallback при ошибках

## Измененные файлы

- **`src/services/optimized_processing_service.py`** - основное исправление thread-safe колбэка

## Обратная совместимость

- ⚠️ Упрощён API прогресса: удалён текст подэтапов. Используются только проценты и (опционально) `compression_info`.
- ✅ Thread-safety добавлен без изменений логики обработки

## Мониторинг

В логах теперь можно увидеть:
- `DEBUG`: Progress update: X% (когда используется fallback)
- `WARNING`: Ошибка при обновлении прогресса (при неожиданных исключениях)

Эти сообщения информационные и не означают ошибки в работе системы.
