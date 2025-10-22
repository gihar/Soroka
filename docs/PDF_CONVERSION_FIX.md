# Исправление ошибки конвертации в PDF

## Проблема

При попытке конвертировать протоколы встреч в PDF возникала ошибка:

```
ERROR | src.services.task_queue_manager:_send_result_to_user:383 - Ошибка конвертации в PDF: 
cannot load library 'libgobject-2.0-0': dlopen(libgobject-2.0-0, 0x0002): tried: 'libgobject-2.0-0' 
(no such file)...
```

WeasyPrint требовал системных библиотек (libgobject-2.0-0, cairo, pango, gdk-pixbuf), которые не были установлены на macOS.

## Решение

### 1. Создан общий модуль для конвертации PDF

Создан модуль `src/utils/pdf_converter.py` с функцией `convert_markdown_to_pdf()`, которая использует **ReportLab** вместо WeasyPrint.

**Преимущества ReportLab:**
- Чистый Python, без системных зависимостей
- Работает из коробки на всех платформах (macOS, Linux, Windows)
- Поддержка кириллицы через системные шрифты
- Более легковесный

### 2. Обновлены файлы

**Измененные файлы:**
- `src/services/task_queue_manager.py` - заменен WeasyPrint на ReportLab
- `src/handlers/callback_handlers.py` - удалена дублирующаяся функция, добавлен импорт
- `src/handlers/message_handlers.py` - удалена дублирующаяся функция, добавлен импорт
- `requirements.txt` - удалены `weasyprint>=63.1` и `markdown>=3.7`

### 3. Особенности реализации

Функция `convert_markdown_to_pdf()`:
- Автоматически определяет доступные системные шрифты для macOS и Linux
- Парсит markdown напрямую (заголовки, списки, жирный текст, курсив)
- Создает красиво отформатированные PDF с поддержкой кириллицы
- Использует цветовую схему для заголовков
- Fallback на стандартный шрифт Helvetica, если системные шрифты не найдены

### 4. Обработка ошибок

В `task_queue_manager.py` добавлен fallback: если конвертация в PDF не удалась, протокол сохраняется как Markdown файл.

## Использование

```python
from src.utils.pdf_converter import convert_markdown_to_pdf

# Конвертация markdown в PDF
markdown_text = "# Заголовок\n\n**Жирный текст**"
convert_markdown_to_pdf(markdown_text, "output.pdf")
```

## Результат

✅ PDF конвертация теперь работает на всех платформах без установки системных библиотек
✅ Устранено дублирование кода между модулями
✅ Упрощены зависимости проекта

