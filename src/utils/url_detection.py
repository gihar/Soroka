"""Единый детектор ссылки в тексте сообщения.

Одно определение «в сообщении есть ссылка» на весь бот. И общий обработчик
записи (``text_handler``), и фильтр ловца имени в Карточке сопоставления
сходятся на нём: текст, который фильтр пропустил как «это ссылка, а не имя»,
обязан опознаться обработчиком записи как ссылка — иначе он получил бы отказ
«пришлите файл или ссылку» вместо обработки. Общий предикат исключает расхождение.
"""

import re
from typing import Optional

_URL_PATTERN = re.compile(r"https?://[^\s]+")


def contains_url(text: Optional[str]) -> bool:
    """Есть ли в тексте ссылка (http/https)."""
    return bool(text and _URL_PATTERN.search(text))


def extract_url(text: Optional[str]) -> str:
    """Первая ссылка из текста (пустая строка, если ссылки нет)."""
    if not text:
        return ""
    match = _URL_PATTERN.search(text)
    return match.group(0) if match else ""
