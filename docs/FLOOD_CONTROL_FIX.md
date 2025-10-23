# Исправление Flood Control и Error Handler

## Обзор

Документ описывает исправления критических ошибок связанных с Telegram Flood Control и глобальным error handler'ом.

## Проблемы, которые были решены

### 1. Неправильная сигнатура error handler

**Проблема:** 
```
TypeError: EnhancedTelegramBot._setup_error_handling.<locals>.error_handler() missing 1 required positional argument: 'exception'
```

**Причина:** В aiogram 3.x error handler должен принимать `ErrorEvent`, а не отдельные аргументы `update` и `exception`.

**Решение:** Обновлена сигнатура в `src/bot.py:204-221`:
```python
from aiogram.types import ErrorEvent

@self.dp.error()
async def error_handler(event: ErrorEvent):
    update = event.update
    exception = event.exception
    # ...
```

### 2. Каскадные ошибки flood control

**Проблема:** При получении `TelegramRetryAfter` middleware пытался отправить сообщение об ошибке пользователю, что вызывало новый flood control, создавая бесконечный цикл ошибок.

**Решение:** 
- Добавлена специальная обработка `TelegramRetryAfter` в `ErrorHandlingMiddleware`
- При flood control **не отправляются** сообщения пользователю
- Ошибка только логируется для администратора
- Блокировка регистрируется в `TelegramFloodControl` для мониторинга

### 3. Отсутствие превентивного rate limiting

**Проблема:** Бот не ограничивал скорость отправки сообщений до получения ошибки от Telegram API.

**Решение:** Создана система `TelegramRateLimiter` с:
- Превентивным ограничением: 20 сообщений/сек (консервативно)
- Burst protection: максимум 3 сообщения подряд
- Автоматическим retry с экспоненциальной задержкой
- Очередью сообщений для отправки после снятия блокировки

## Новые компоненты

### 1. `src/reliability/telegram_rate_limiter.py`

Специализированная система для работы с Telegram API:

**Классы:**
- `TelegramFloodControl` - управление состоянием flood control
- `TelegramMessageQueue` - очередь отложенных сообщений
- `TelegramRateLimiter` - главный менеджер с превентивным rate limiting

**Ключевые функции:**
- `register_flood_control()` - регистрация блокировки от Telegram
- `is_blocked()` - проверка активной блокировки
- `check_rate_limit()` - превентивная проверка лимита
- `safe_send_with_retry()` - безопасная отправка с retry логикой
- `get_stats()` - статистика flood control и rate limiting

**Особенности:**
```python
# Автоматическая обработка TelegramRetryAfter
result = await telegram_rate_limiter.safe_send_with_retry(
    message.answer,
    "Текст сообщения",
    chat_id=message.chat.id
)

# Если flood control активен - сообщение не отправляется
# Логируется для администратора
```

### 2. `src/utils/telegram_safe.py`

Безопасные обертки для всех Telegram операций:

**Функции:**
- `safe_answer()` - безопасный ответ на сообщение
- `safe_edit_text()` - безопасное редактирование
- `safe_delete()` - безопасное удаление
- `safe_send_message()` - безопасная отправка через bot
- `try_send_or_log()` - попытка отправить или залогировать

**Использование:**
```python
from src.utils.telegram_safe import safe_answer, safe_edit_text

# Вместо message.answer()
await safe_answer(message, "Текст")

# Вместо message.edit_text()
await safe_edit_text(status_message, "Обновленный текст")
```

**Преимущества:**
- Автоматическая проверка flood control
- Автоматический rate limiting
- Retry логика при временных ошибках
- Graceful handling - не падает при ошибках
- Подробное логирование проблем

## Обновления существующих компонентов

### 1. `src/bot.py`

**Изменения:**
- Исправлена сигнатура error handler (строки 204-221)
- Добавлен мониторинг flood control в `_perform_startup_checks()` (строки 328-346)

**Новый функционал:**
```python
# При запуске проверяется статус flood control
if flood_stats['flood_control']['is_active']:
    logger.warning(
        f"⚠️ АКТИВНЫЙ FLOOD CONTROL обнаружен при запуске! "
        f"Осталось: {flood_stats['flood_control']['time_remaining']:.0f}с"
    )
```

### 2. `src/reliability/middleware.py`

**Изменения:**
- Добавлен импорт `TelegramRetryAfter` (строка 11)
- Добавлена обработка `TelegramRetryAfter` в `ErrorHandlingMiddleware` (строки 31-47)
- Обновлена обработка других ошибок с использованием `safe_answer` (строки 62-86)

**Поведение при flood control:**
```python
except TelegramRetryAfter as e:
    # Регистрируем блокировку
    await telegram_rate_limiter.flood_control.register_flood_control(
        e.retry_after, 
        chat_id
    )
    
    # НЕ отправляем сообщение пользователю!
    logger.error(f"Telegram Flood Control: заблокировано на {e.retry_after}с")
    return
```

### 3. `src/reliability/rate_limiter.py`

**Изменения:**
- Обновлен `TELEGRAM_API_LIMIT` до реальных значений (строки 207-211)

**Новые значения:**
```python
TELEGRAM_API_LIMIT = RateLimitConfig(
    requests_per_window=20,  # 20 сообщений (консервативно)
    window_size=1.0,         # за секунду
    burst_limit=3            # максимум 3 подряд
)
```

### 4. `src/handlers/message_handlers.py`

**Изменения:**
- Добавлен импорт безопасных оберток (строка 18)
- Обновлен `_process_url()` - использует `safe_answer` и `safe_edit_text` (строки 575-668)
- Обновлен `media_handler()` - использует `safe_answer` (строки 26-89)
- Обновлен `text_handler()` - использует `safe_answer` (строки 92-135)

**Пример изменений:**
```python
# Было:
await message.answer("🔍 Проверяю ссылку...")

# Стало:
status_message = await safe_answer(message, "🔍 Проверяю ссылку...")
if not status_message:
    logger.warning("Не удалось отправить статусное сообщение")
    return
```

## Алгоритм работы

### Превентивный rate limiting

1. Перед отправкой проверяется локальный rate limit (20 msg/sec)
2. Если лимит превышен, автоматически ждет нужное время
3. Регистрирует отправленное сообщение для отслеживания

### Обработка flood control

1. При получении `TelegramRetryAfter`:
   - Регистрируется блокировка с временем
   - Блокируются все чаты (или конкретный чат)
   - Логируется критическое событие
   
2. Все последующие попытки отправки:
   - Проверяют активный flood control
   - Возвращают `None` вместо отправки
   - Логируют предупреждение

3. После истечения времени блокировки:
   - Автоматически снимается
   - Отправка сообщений возобновляется

### Retry логика

При коротких блокировках (≤5 секунд):
1. Ждет указанное время + 0.5с
2. Делает повторную попытку (до 2 раз)
3. При успехе возвращает результат

При длинных блокировках (>5 секунд):
1. Регистрирует блокировку
2. Не делает retry
3. Возвращает `None`

## Мониторинг

### Статистика flood control

```python
from src.reliability.telegram_rate_limiter import telegram_rate_limiter

stats = telegram_rate_limiter.get_stats()
# {
#     'flood_control': {
#         'is_active': False,
#         'retry_after': 0,
#         'time_remaining': 0,
#         'blocked_chats_count': 0,
#         'total_blocks': 3,
#         'last_block_time': 1729665716.5
#     },
#     'queue_size': 0,
#     'messages_sent_last_second': 2,
#     'rate_limit': {
#         'messages_per_second': 20,
#         'burst_limit': 3
#     }
# }
```

### Логирование

**При активации flood control:**
```
CRITICAL | 🚨 FLOOD CONTROL активирован! Блокировка на 9622 секунд (до 11:01:56)
```

**При критической блокировке (>5 минут):**
```
CRITICAL | ⚠️ КРИТИЧЕСКАЯ БЛОКИРОВКА: 160 минут! Требуется проверка причин.
```

**При проверке на старте:**
```
WARNING | ⚠️ АКТИВНЫЙ FLOOD CONTROL обнаружен при запуске! Осталось: 8543с
```

**При попытке отправки во время блокировки:**
```
WARNING | Сообщение заблокировано flood control. Осталось 8542 секунд.
```

## Тестирование

### Проверка rate limiting

```python
# Отправить много сообщений подряд
for i in range(50):
    result = await safe_answer(message, f"Сообщение {i}")
    if not result:
        print(f"Сообщение {i} заблокировано rate limiter")
```

### Проверка flood control

```python
# После получения TelegramRetryAfter
stats = telegram_rate_limiter.get_stats()
assert stats['flood_control']['is_active'] == True

# Попытка отправить сообщение
result = await safe_answer(message, "Тест")
assert result is None  # Должно быть заблокировано
```

### Проверка восстановления

```python
# Ждем истечения блокировки
await asyncio.sleep(retry_after + 1)

# Проверяем статус
is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked()
assert not is_blocked

# Сообщения снова отправляются
result = await safe_answer(message, "Тест")
assert result is not None
```

## Рекомендации

### Для разработчиков

1. **Всегда используйте безопасные обертки:**
   ```python
   # ✅ Правильно
   await safe_answer(message, "Текст")
   
   # ❌ Неправильно
   await message.answer("Текст")
   ```

2. **Обрабатывайте None результаты:**
   ```python
   result = await safe_answer(message, "Текст")
   if not result:
       logger.warning("Не удалось отправить сообщение")
       return
   ```

3. **Для некритичных сообщений используйте try_send_or_log:**
   ```python
   await try_send_or_log(message, "Информация", log_prefix="Info")
   ```

### Для администраторов

1. **Мониторьте логи на CRITICAL события** с упоминанием FLOOD CONTROL

2. **Проверяйте статистику блокировок:**
   ```bash
   # В логах
   grep "FLOOD CONTROL" logs/bot.log
   ```

3. **При частых блокировках:**
   - Проверьте, не отправляет ли бот слишком много сообщений
   - Рассмотрите уменьшение `messages_per_second` в настройках
   - Проверьте, нет ли циклов отправки сообщений

## Совместимость

- ✅ aiogram 3.x
- ✅ Python 3.11+
- ✅ Все существующие обработчики
- ✅ Обратная совместимость с кодом, использующим прямые вызовы

## Дополнительная информация

- Telegram API limits: https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
- aiogram Error Handling: https://docs.aiogram.dev/en/latest/dispatcher/errors.html

