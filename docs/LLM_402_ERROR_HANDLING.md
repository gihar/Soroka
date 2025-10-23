# Обработка ошибки 402 (Недостаточно кредитов) от LLM API

**Дата:** 23 октября 2025  
**Статус:** ✅ Реализовано

## Проблема

При недостатке кредитов на OpenRouter API возникает ошибка HTTP 402 ("Payment Required"), которая:
- Логируется множество раз (по одному разу на каждый сегмент при параллельной обработке)
- Не прерывает обработку немедленно
- Не предоставляет пользователю понятного сообщения об ошибке
- Тратит время на бесполезные повторные попытки

### Пример ошибки из логов

```
ERROR | src.reliability.retry:execute_with_retry:84 - Неповторяемое исключение в _call_openai_api: Error code: 402 - {'error': {'message': 'Insufficient credits. Add more using https://openrouter.ai/settings/credits', 'code': 402}}
ERROR | llm_providers:generate_protocol_chain_of_thought:1344 - Ошибка при обработке сегмента: Error code: 402 - {'error': {'message': 'Insufficient credits. Add more using https://openrouter.ai/settings/credits', 'code': 402}}
```

## Решение

### 1. Создано специализированное исключение

**Файл:** `src/exceptions/processing.py`

```python
class LLMInsufficientCreditsError(LLMError):
    """Ошибка недостатка кредитов на LLM API"""
    
    def __init__(self, message: str, provider: str = None, model: str = None):
        # Форматируем сообщение для пользователя
        user_message = f"Недостаточно кредитов на токены для LLM: {message}"
        super().__init__(
            message=user_message,
            provider=provider,
            model=model
        )
        self.error_code = "LLM_INSUFFICIENT_CREDITS"
```

**Особенности:**
- Наследуется от `LLMError`, который наследуется от `BotException`
- Автоматически форматирует сообщение для пользователя
- Содержит подробности об ошибке (провайдер, модель)
- Имеет специальный код ошибки для логирования

### 2. Добавлена обработка в RetryManager

**Файл:** `src/reliability/retry.py`

```python
def is_retryable_exception(self, exception: Exception) -> bool:
    """Проверить, стоит ли повторять при данном исключении"""
    # Никогда не повторяем при недостатке кредитов
    if isinstance(exception, LLMInsufficientCreditsError):
        return False
    return any(isinstance(exception, exc_type) for exc_type in self.config.retryable_exceptions)
```

Это предотвращает бесполезные повторные попытки при недостатке кредитов.

### 3. Обработка ошибки 402 в вызовах OpenAI API

**Файл:** `llm_providers.py`

Добавлена обработка ошибки 402 в **пяти местах**:

#### a) В функции `OpenAIProvider.generate_protocol()` (строка ~411)
Обработка для стандартной генерации протокола

#### b) В функции `generate_protocol_two_stage()` - Этап 1 (строка ~975)
Обработка для первого этапа двухэтапной генерации

#### c) В функции `generate_protocol_two_stage()` - Этап 2 (строка ~1031)
Обработка для второго этапа двухэтапной генерации

#### d) В функции `_process_single_segment()` (строка ~1204)
Обработка для параллельной обработки сегментов в Chain-of-Thought

#### e) В функции `generate_protocol_chain_of_thought()` - Синтез (строка ~1413)
Обработка для этапа синтеза в Chain-of-Thought

**Пример обработки:**

```python
try:
    response = await retry_manager.execute_with_retry(_call_openai_api)
except openai.APIStatusError as e:
    # Проверяем на ошибку 402 - недостаточно кредитов
    if e.status_code == 402:
        error_message = e.message
        # Пытаемся извлечь более подробное сообщение из тела ответа
        if hasattr(e, 'response') and e.response:
            try:
                error_body = e.response.json()
                if 'error' in error_body and 'message' in error_body['error']:
                    error_message = error_body['error']['message']
            except:
                pass
        logger.error(f"Недостаточно кредитов для LLM: {error_message}")
        raise LLMInsufficientCreditsError(
            message=error_message,
            provider="openai",
            model=selected_model
        )
    # Другие ошибки API пробрасываем дальше
    raise
```

### 4. Немедленное прерывание при обнаружении ошибки в сегментах

**Файл:** `llm_providers.py`, функция `generate_protocol_chain_of_thought()` (строка ~1367)

```python
for result in results:
    if isinstance(result, Exception):
        # Если это ошибка недостатка кредитов - немедленно прерываем
        if isinstance(result, LLMInsufficientCreditsError):
            logger.error(f"Обнаружена ошибка недостатка кредитов, прерываем обработку")
            raise result
        
        failed_count += 1
        logger.error(f"Ошибка при обработке сегмента: {result}")
        # Добавляем пустой результат для других ошибок
        segment_results.append({...})
```

Это гарантирует, что при параллельной обработке сегментов ошибка 402 немедленно прерывает всю обработку.

### 5. Автоматическая отправка сообщения пользователю

**Файл:** `src/reliability/middleware.py`

Middleware уже обрабатывает `BotException` (строки 38-42):

```python
except BotException as e:
    logger.error(f"Bot exception: {e.to_dict()}")
    if isinstance(event, Message):
        await event.answer(f"❌ {e.message}")
    return
```

Поскольку `LLMInsufficientCreditsError` наследуется от `BotException`, сообщение автоматически отправляется пользователю.

## Результат

### Сообщение для пользователя

Когда возникает ошибка 402, пользователь получает сообщение:

```
❌ Ошибка LLM: Недостаточно кредитов на токены для LLM: Insufficient credits. Add more using https://openrouter.ai/settings/credits
```

### Преимущества

1. **Быстрое прерывание** - обработка немедленно останавливается при первой ошибке 402
2. **Нет бесполезных повторов** - RetryManager не пытается повторить запрос
3. **Понятное сообщение** - пользователь знает, в чём проблема и что делать
4. **Чистые логи** - только одна запись об ошибке вместо множества
5. **Экономия ресурсов** - не тратится время на обработку остальных сегментов

## Тестирование

Создан и выполнен тестовый скрипт, который проверяет:
- ✅ Создание исключения `LLMInsufficientCreditsError`
- ✅ Правильное форматирование сообщения
- ✅ Корректное наследование от `BotException` и `LLMError`
- ✅ Правильное поведение `RetryManager` (ошибка не повторяется)

Все тесты пройдены успешно.

## Файлы изменены

1. `src/exceptions/processing.py` - добавлен класс `LLMInsufficientCreditsError`
2. `src/exceptions/__init__.py` - добавлен экспорт нового исключения
3. `src/reliability/retry.py` - добавлена проверка на неповторяемость ошибки 402
4. `llm_providers.py` - добавлена обработка ошибки 402 в 5 местах:
   - `OpenAIProvider.generate_protocol()`
   - `generate_protocol_two_stage()` - этап 1
   - `generate_protocol_two_stage()` - этап 2
   - `_process_single_segment()`
   - `generate_protocol_chain_of_thought()` - синтез

## Совместимость

- ✅ Обратная совместимость полностью сохранена
- ✅ Не требует изменений в конфигурации
- ✅ Не влияет на обработку других типов ошибок
- ✅ Работает с middleware автоматически

