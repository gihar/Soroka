# Flood Control - Краткое руководство

## Быстрый старт

### Использование безопасных оберток

Вместо прямых вызовов Telegram API используйте безопасные обертки:

```python
from src.utils.telegram_safe import safe_answer, safe_edit_text, safe_delete

# Отправка сообщения
result = await safe_answer(message, "Привет!")
if not result:
    logger.warning("Сообщение не отправлено (возможен flood control)")

# Редактирование сообщения
result = await safe_edit_text(status_message, "Обновленный текст")

# Удаление сообщения
success = await safe_delete(message)
```

### Проверка статуса Flood Control

```python
from src.reliability.telegram_rate_limiter import telegram_rate_limiter

# Проверить, активен ли flood control
is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked()
if is_blocked:
    print(f"Flood control активен. Осталось: {remaining:.0f} секунд")

# Получить полную статистику
stats = telegram_rate_limiter.get_stats()
print(f"Всего блокировок: {stats['flood_control']['total_blocks']}")
print(f"Сообщений за последнюю секунду: {stats['messages_sent_last_second']}")
```

### Обработка ошибок

Безопасные обертки возвращают `None` при ошибках:

```python
# Простая обработка
result = await safe_answer(message, "Текст")
if result:
    # Сообщение отправлено успешно
    logger.info(f"Отправлено сообщение {result.message_id}")
else:
    # Сообщение не отправлено (flood control или другая ошибка)
    logger.warning("Не удалось отправить сообщение")

# Для некритичных сообщений
from src.utils.telegram_safe import try_send_or_log
await try_send_or_log(message, "Информационное сообщение", log_prefix="Info")
```

## Основные возможности

### Автоматический Rate Limiting
- 20 сообщений в секунду (максимум)
- Burst protection: не более 3 подряд
- Автоматическое ожидание при превышении лимита

### Обработка Flood Control
- Автоматическая регистрация блокировок от Telegram
- Блокировка всех отправок во время flood control
- Подробное логирование для администратора

### Retry логика
- Короткие блокировки (≤5 сек): до 2 автоматических retry
- Длинные блокировки (>5 сек): без retry, только регистрация
- Экспоненциальная задержка между попытками

## Мониторинг

### Логи

Ищите в логах ключевые события:

```bash
# Активация flood control
grep "FLOOD CONTROL активирован" logs/bot.log

# Критические блокировки
grep "КРИТИЧЕСКАЯ БЛОКИРОВКА" logs/bot.log

# Заблокированные сообщения
grep "заблокировано flood control" logs/bot.log
```

### Статус при запуске

При старте бота автоматически проверяется статус flood control:

```
INFO | ✅ Flood control: не активен
INFO | 📊 История flood control: 3 блокировок
```

Или при активной блокировке:

```
WARNING | ⚠️ АКТИВНЫЙ FLOOD CONTROL обнаружен при запуске! Осталось: 8543с
```

## Рекомендации

### ✅ Хорошие практики

1. **Всегда используйте safe_answer вместо message.answer:**
   ```python
   await safe_answer(message, "Текст")
   ```

2. **Проверяйте результат для критичных сообщений:**
   ```python
   result = await safe_answer(message, "Важное сообщение")
   if not result:
       # Обработать ситуацию (например, сохранить в БД для повтора)
       pass
   ```

3. **Для информационных сообщений используйте try_send_or_log:**
   ```python
   await try_send_or_log(message, "Инфо", log_prefix="Info")
   ```

4. **Минимизируйте количество сообщений:**
   ```python
   # ❌ Плохо - 3 сообщения
   await safe_answer(message, "Начинаю обработку...")
   await safe_answer(message, "Загружаю файл...")
   await safe_answer(message, "Анализирую...")
   
   # ✅ Хорошо - 1 сообщение с редактированием
   status = await safe_answer(message, "⏳ Начинаю обработку...")
   await safe_edit_text(status, "⏳ Загружаю файл...")
   await safe_edit_text(status, "⏳ Анализирую...")
   ```

### ❌ Анти-паттерны

1. **НЕ используйте прямые вызовы в новом коде:**
   ```python
   # ❌ Избегайте
   await message.answer("Текст")
   
   # ✅ Используйте
   await safe_answer(message, "Текст")
   ```

2. **НЕ игнорируйте None результаты для критичных операций:**
   ```python
   # ❌ Плохо
   await safe_answer(message, "Оплата прошла успешно")
   
   # ✅ Хорошо
   result = await safe_answer(message, "Оплата прошла успешно")
   if not result:
       # Сохранить информацию о неотправленном уведомлении
       await db.save_pending_notification(user_id, "payment_success")
   ```

3. **НЕ отправляйте много сообщений подряд:**
   ```python
   # ❌ Плохо - вызовет rate limiting
   for i in range(50):
       await safe_answer(message, f"Сообщение {i}")
   
   # ✅ Хорошо - группируйте или добавляйте задержки
   text = "\n".join([f"Элемент {i}" for i in range(50)])
   await safe_answer(message, text)
   ```

## Troubleshooting

### Сообщения не отправляются

**Симптомы:** `safe_answer` возвращает `None`

**Причины и решения:**

1. **Активный flood control:**
   ```python
   stats = telegram_rate_limiter.get_stats()
   if stats['flood_control']['is_active']:
       print(f"Ожидайте {stats['flood_control']['time_remaining']:.0f} секунд")
   ```

2. **Rate limit превышен:**
   ```python
   # Слишком много сообщений за секунду
   # Решение: добавить задержку или группировать сообщения
   await asyncio.sleep(0.1)
   ```

3. **Проблемы с сетью/Telegram API:**
   ```python
   # Проверьте логи на ошибки соединения
   grep "ConnectionError\|TimeoutError" logs/bot.log
   ```

### Частые блокировки

**Симптомы:** Регулярное появление "FLOOD CONTROL активирован"

**Решения:**

1. **Уменьшите частоту отправки:**
   ```python
   # В src/reliability/telegram_rate_limiter.py
   self.messages_per_second = 15  # Вместо 20
   ```

2. **Используйте редактирование вместо новых сообщений:**
   ```python
   status = await safe_answer(message, "Шаг 1")
   await safe_edit_text(status, "Шаг 2")  # Вместо нового сообщения
   ```

3. **Группируйте информацию:**
   ```python
   # Вместо 5 сообщений - одно комплексное
   text = f"Статистика:\n{stat1}\n{stat2}\n{stat3}"
   await safe_answer(message, text)
   ```

### Долгая блокировка (>1 час)

**Что делать:**

1. Проверьте логи на причину:
   ```bash
   grep -B5 "КРИТИЧЕСКАЯ БЛОКИРОВКА" logs/bot.log
   ```

2. Дождитесь истечения времени блокировки

3. После восстановления:
   - Проверьте код на циклы отправки сообщений
   - Уменьшите rate limits
   - Добавьте больше группировки сообщений

## Дополнительная информация

- **Полная документация:** `docs/FLOOD_CONTROL_FIX.md`
- **Changelog:** `CHANGELOG_FLOOD_CONTROL_FIX.md`
- **Telegram API Limits:** https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this

## Поддержка

При возникновении проблем:

1. Проверьте логи: `logs/bot.log`
2. Проверьте статистику: `telegram_rate_limiter.get_stats()`
3. Убедитесь, что используете последнюю версию кода
4. Проверьте документацию: `docs/FLOOD_CONTROL_FIX.md`

