# План: Добавление "Умный выбор" в настройки по умолчанию

## Цель
Позволить пользователю установить "🤖 Умный выбор" как шаблон по умолчанию, чтобы ML-селектор автоматически подбирал шаблон при каждой загрузке файла.

## Текущее поведение
- Пользователь может установить конкретный шаблон по умолчанию (template_id)
- При загрузке файла этот шаблон используется автоматически
- "Умный выбор" доступен только при ручном выборе

## Желаемое поведение
```
Настройки → Шаблон по умолчанию:

[🤖 Умный выбор (рекомендуется)]  ← НОВАЯ КНОПКА (первая)
[👔 Управленческие (6)]
[🚀 Продуктовые (6)]
[📋 Общие (4)]
[📝 Все шаблоны]
[🔄 Сбросить шаблон по умолчанию]
```

## Реализация

### Вариант: Использовать специальное значение `template_id = 0`

**Преимущества:**
- Не требует изменений схемы БД
- Минимальные изменения кода
- `template_id = 0` означает "Умный выбор"
- `template_id = NULL` означает "Не установлен"
- `template_id > 0` означает конкретный шаблон

### Шаги реализации

#### 1. Обновить меню настроек (callback_handlers.py)

**Файл:** `src/handlers/callback_handlers.py`
**Функция:** `settings_default_template_callback` (строка ~660)

**Добавить кнопку "Умный выбор" ПЕРВОЙ:**
```python
keyboard_buttons = []

# НОВАЯ кнопка - Умный выбор (первая!)
keyboard_buttons.append([InlineKeyboardButton(
    text="🤖 Умный выбор (рекомендуется)",
    callback_data="set_default_template_0"  # 0 = умный выбор
)])

# Далее категории...
for category, templates in sorted(categories.items()):
    ...
```

#### 2. Обновить обработчик установки шаблона

**Файл:** `src/handlers/callback_handlers.py`
**Функция:** Найти обработчик `set_default_template_{id}`

**Добавить обработку template_id = 0:**
```python
@router.callback_query(F.data.startswith("set_default_template_"))
async def set_default_template_callback(callback: CallbackQuery):
    template_id = int(callback.data.replace("set_default_template_", ""))
    
    if template_id == 0:
        # Умный выбор
        await template_service.set_user_default_template(
            callback.from_user.id, 
            0  # Специальное значение
        )
        await callback.message.edit_text(
            "✅ **Установлен режим: Умный выбор**\n\n"
            "🤖 ИИ будет автоматически подбирать подходящий шаблон "
            "на основе содержания каждой встречи.\n\n"
            "Это рекомендуемый режим для большинства пользователей.",
            ...
        )
    else:
        # Обычный шаблон
        ...
```

#### 3. Обновить логику использования шаблона по умолчанию

**Файл:** `src/handlers/message_handlers.py`
**Функция:** `_show_template_selection` (строка ~714)

**Изменить проверку:**
```python
if user and user.default_template_id:
    if user.default_template_id == 0:
        # Умный выбор установлен по умолчанию
        await state.update_data(template_id=None, use_smart_selection=True)
        
        await message.answer(
            "🤖 **Используется Умный выбор шаблона**\n\n"
            "ИИ автоматически подберёт подходящий шаблон после транскрипции.",
            parse_mode="Markdown"
        )
        
        # Переходим к выбору LLM
        await _show_llm_selection_for_file(message, state, llm_service, processing_service)
        return
    else:
        # Обычный шаблон (существующий код)
        default_template = await template_service.get_template_by_id(user.default_template_id)
        ...
```

#### 4. Обновить отображение текущей настройки

**Файл:** `src/handlers/command_handlers.py` или где показываются настройки

**При показе текущих настроек:**
```python
if user.default_template_id == 0:
    template_text = "🤖 Умный выбор (автоматический подбор)"
elif user.default_template_id:
    template = await template_service.get_template_by_id(user.default_template_id)
    template_text = f"📝 {template.name}"
else:
    template_text = "❌ Не установлен"
```

#### 5. Обновить сообщение о сбросе настроек

**Файл:** `src/handlers/callback_handlers.py`
**Функция:** `reset_default_template`

**Текст сообщения:**
```python
"🔄 Шаблон по умолчанию сброшен\n\n"
"Теперь вам нужно будет выбирать шаблон вручную при каждой загрузке файла.\n\n"
"💡 Рекомендуем установить '🤖 Умный выбор' для автоматического подбора."
```

## Изменяемые файлы

1. `src/handlers/callback_handlers.py` - основная логика
   - settings_default_template_callback (~660)
   - set_default_template_callback (найти)
   - reset_default_template (найти)

2. `src/handlers/message_handlers.py`
   - _show_template_selection (~714)

3. `src/handlers/command_handlers.py` (опционально)
   - settings_handler - показ текущих настроек

## Преимущества для пользователя

1. **Удобство:** Один раз установил - всегда работает
2. **Автоматизация:** Не нужно выбирать шаблон каждый раз
3. **Интеллектуальность:** ML подбирает лучший шаблон для каждой встречи
4. **Гибкость:** Можно в любой момент изменить на конкретный шаблон

## Тестирование

1. ✅ Зайти в Настройки → Шаблон по умолчанию
2. ✅ Увидеть кнопку "🤖 Умный выбор (рекомендуется)" первой
3. ✅ Нажать - увидеть подтверждение установки
4. ✅ Загрузить файл - автоматически активируется умный выбор
5. ✅ Проверить сброс настроек
6. ✅ Проверить переключение на обычный шаблон

## UX Flow

### Сценарий 1: Новый пользователь
```
1. Загружает файл → видит все опции выбора
2. Выбирает вручную или "Умный выбор"
3. Бот предлагает: "Хотите установить это по умолчанию?"
```

### Сценарий 2: Опытный пользователь
```
1. Настройки → Шаблон по умолчанию → Умный выбор
2. Загружает файлы → всё работает автоматически
3. При необходимости может изменить в настройках
```

## Приоритет
🟡 **Средний** - улучшает UX, но не критично

## Время реализации
~30 минут

## Зависимости
- Использует существующий SmartTemplateSelector
- Не требует изменений БД
- Совместимо с текущей логикой

