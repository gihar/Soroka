"""Утилиты для работы с текстом сообщений.

Отправка сообщений живёт в src.utils.telegram_safe (safe-обёртки с rate
limiting и рендером канонического Markdown в HTML на границе). Здесь —
только экранирование для MarkdownV2 (используется в speaker_mapping_ui).
"""


def escape_markdown_v2(text: str) -> str:
    """Экранировать специальные символы MarkdownV2 для безопасной отправки."""
    if not text:
        return text

    escape_chars = [
        '*', '_', '`', '[', ']', '(', ')', '~', '>', '#',
        '+', '-', '=', '|', '{', '}', '.', '!',
    ]

    result = str(text)
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')

    return result
