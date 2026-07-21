"""Отправитель карточек — единый шов доставки интерактивных экранов (ADR-0005).

Один контракт и для первичной отправки (``send_card``), и для перерисовки
(``edit_card``): в норме экран уходит одним Telegram HTML-сообщением, при неудаче
— ЕДИНСТВЕННЫЙ фолбэк на plain-страховку (то же семантическое содержимое без
тегов). Разметку и экранирование знает содержимое (``card_content``); отправитель
лишь выбирает канал и страхует.

Обёртки Telegram зовём через модуль ``telegram_safe`` (а не импортом имени),
чтобы monkeypatch в тестах бил по одному объекту (ADR-0004).
"""

from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message
from loguru import logger

from src.utils import telegram_safe
from src.ux.card_content import CardContent


async def send_card(
    bot: Bot,
    chat_id: int,
    content: CardContent,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """Отправить экран новым сообщением: HTML, при неудаче — plain-страховка."""
    message = await telegram_safe.safe_send_message(
        bot=bot,
        chat_id=chat_id,
        text=content.to_html(),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    if message is not None:
        return message

    logger.warning(
        f"Карточка не ушла в HTML (chat_id={chat_id}), страхую plain-версией"
    )
    return await telegram_safe.safe_send_message(
        bot=bot,
        chat_id=chat_id,
        text=content.to_plain(),
        parse_mode=None,
        reply_markup=keyboard,
    )


async def edit_card(
    message: Message,
    content: CardContent,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """Перерисовать экран на месте: HTML, при неудаче — plain-страховка."""
    edited = await telegram_safe.safe_edit_text(
        message,
        content.to_html(),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    if edited is not None:
        return edited

    logger.warning("Перерисовка карточки не удалась в HTML, страхую plain-версией")
    return await telegram_safe.safe_edit_text(
        message,
        content.to_plain(),
        parse_mode=None,
        reply_markup=keyboard,
    )
