"""Канальный рендер протокола.

Канонический формат протокола — Markdown (его создают Jinja-шаблоны, системные
и пользовательские). Этот пакет отвечает за представление под канал доставки:

- чат Telegram: `render_protocol_messages` / `markdown_to_telegram_html`;
- файл .md: канонический текст без преобразований;
- PDF: `src.utils.pdf_converter` (стили поверх того же Markdown).
"""

from src.services.protocol_render.splitter import render_protocol_messages
from src.services.protocol_render.telegram_html import markdown_to_telegram_html

__all__ = ["markdown_to_telegram_html", "render_protocol_messages"]
