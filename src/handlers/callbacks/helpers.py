"""
Вспомогательные функции для callback обработчиков.
"""

from aiogram.types import CallbackQuery
from loguru import logger


async def _safe_callback_answer(callback: CallbackQuery, text: str = None):
    """Безопасный ответ на callback query с обработкой устаревших запросов"""
    try:
        await callback.answer(text=text)
    except Exception as e:
        error_str = str(e).lower()
        # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
        error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
        if "query is too old" in error_str or "query id is invalid" in error_str:
            logger.debug(f"Callback query устарел: {error_msg_safe}")
        else:
            logger.warning(f"Ошибка ответа на callback: {error_msg_safe}")


def _fix_markdown_tags(text: str) -> str:
    """Исправить незакрытые Markdown-теги в тексте"""
    # Подсчитываем количество открытых/закрытых тегов
    bold_count = text.count('**')
    italic_count = text.count('_')
    code_count = text.count('`')

    # Закрываем незакрытые теги
    if bold_count % 2 != 0:
        text = text + '**'
    if italic_count % 2 != 0:
        text = text + '_'
    if code_count % 2 != 0:
        text = text + '`'

    return text


async def _send_long_message(chat_id: int, text: str, bot, max_length: int = 4096):
    """Отправить длинное сообщение по частям"""
    # Учитываем заголовок при расчете максимальной длины части
    header_template = "📄 **Протокол встречи** (часть {}/{})\n\n"
    max_header_length = len(header_template.format(999, 999))  # Максимальная длина заголовка
    max_part_length = max_length - max_header_length

    if len(text) <= max_length:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
            return
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            # Если не удалось отправить с Markdown, пробуем без него
            await bot.send_message(chat_id, text)
            return

    # Разбиваем текст на части
    parts = []
    current_part = ""

    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 <= max_part_length:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'

    if current_part:
        parts.append(current_part.strip())

    # Отправляем части с обработкой ошибок
    for i, part in enumerate(parts):
        try:
            header = f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n"
            full_message = header + part

            # Исправляем незакрытые Markdown-теги
            full_message = _fix_markdown_tags(full_message)

            # Проверяем, что сообщение не превышает лимит
            if len(full_message) > max_length:
                # Если превышает, отправляем без Markdown
                await bot.send_message(chat_id, full_message)
            else:
                await bot.send_message(chat_id, full_message, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Ошибка отправки части {i+1}: {e}")
            # Пробуем отправить без Markdown
            try:
                header = f"📄 Протокол встречи (часть {i+1}/{len(parts)})\n\n"
                await bot.send_message(chat_id, header + part)
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки части {i+1}: {e2}")
                # Отправляем простой текст без заголовка
                await bot.send_message(chat_id, part[:max_length])
