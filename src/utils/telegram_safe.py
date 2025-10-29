"""
Безопасные обертки для работы с Telegram API
"""

from typing import Optional, Any, Union
from loguru import logger

from aiogram.types import Message, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply, FSInputFile
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from src.reliability.telegram_rate_limiter import telegram_rate_limiter


async def safe_answer(
    message: Message,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply]] = None,
    disable_web_page_preview: Optional[bool] = None,
    disable_notification: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасная отправка ответа на сообщение
    
    Args:
        message: Исходное сообщение
        text: Текст ответа
        parse_mode: Режим парсинга (HTML, Markdown)
        reply_markup: Клавиатура
        disable_web_page_preview: Отключить превью ссылок
        disable_notification: Отключить уведомление
        **kwargs: Дополнительные параметры
    
    Returns:
        Отправленное сообщение или None при ошибке
    """
    try:
        result = await telegram_rate_limiter.safe_send_with_retry(
            message.answer,
            text,
            chat_id=message.chat.id,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            **kwargs
        )
        
        if result is None:
            logger.warning(f"Не удалось отправить сообщение в чат {message.chat.id}")
        
        return result
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_answer: {e}")
        return None


async def safe_edit_text(
    message: Message,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасное редактирование текста сообщения
    
    Args:
        message: Сообщение для редактирования
        text: Новый текст
        parse_mode: Режим парсинга
        reply_markup: Клавиатура
        disable_web_page_preview: Отключить превью ссылок
        **kwargs: Дополнительные параметры
    
    Returns:
        Отредактированное сообщение или None при ошибке
    """
    try:
        message_id = message.message_id
        chat_id = message.chat.id
        
        # ПРЕДВАРИТЕЛЬНАЯ проверка flood control до вызова rate limiter
        is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked(chat_id)
        if is_blocked:
            logger.debug(
                f"safe_edit_text: Редактирование блокировано flood control "
                f"(msg_id={message_id}, chat_id={chat_id}, осталось {remaining:.0f}с)"
            )
            return None
        
        result = await telegram_rate_limiter.safe_send_with_retry(
            message.edit_text,
            text,
            chat_id=chat_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            **kwargs
        )
        
        if result is None:
            logger.warning(
                f"Не удалось отредактировать сообщение "
                f"(msg_id={message_id}, chat_id={chat_id})"
            )
        return result
    
    except TelegramBadRequest as e:
        # Игнорируем ошибку "message is not modified" - это нормально
        if "message is not modified" in str(e).lower():
            logger.debug(f"Сообщение не изменилось, пропускаем редактирование (msg_id={message.message_id})")
            return message
        
        logger.error(f"Ошибка при редактировании сообщения (msg_id={message.message_id}): {e}")
        return None
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_edit_text (msg_id={message.message_id}): {e}")
        return None


async def safe_delete(
    message: Message,
    **kwargs
) -> bool:
    """
    Безопасное удаление сообщения
    
    Args:
        message: Сообщение для удаления
        **kwargs: Дополнительные параметры
    
    Returns:
        True если успешно удалено, False при ошибке
    """
    try:
        result = await telegram_rate_limiter.safe_send_with_retry(
            message.delete,
            chat_id=message.chat.id,
            **kwargs
        )
        
        return result is not None
    
    except TelegramBadRequest as e:
        # Игнорируем ошибку если сообщение уже удалено
        if "message to delete not found" in str(e).lower():
            logger.debug("Сообщение уже удалено")
            return True
        
        logger.error(f"Ошибка при удалении сообщения: {e}")
        return False
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_delete: {e}")
        return False


async def safe_send_message(
    bot,
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply]] = None,
    disable_web_page_preview: Optional[bool] = None,
    disable_notification: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасная отправка сообщения через bot
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        text: Текст сообщения
        parse_mode: Режим парсинга
        reply_markup: Клавиатура
        disable_web_page_preview: Отключить превью ссылок
        disable_notification: Отключить уведомление
        **kwargs: Дополнительные параметры
    
    Returns:
        Отправленное сообщение или None при ошибке
    """
    try:
        result = await telegram_rate_limiter.safe_send_with_retry(
            bot.send_message,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            **kwargs
        )
        
        if result is None:
            logger.warning(f"Не удалось отправить сообщение в чат {chat_id}")
        
        return result
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_send_message: {e}")
        return None


async def try_send_or_log(
    message: Message,
    text: str,
    log_prefix: str = "Информация",
    **kwargs
) -> Optional[Message]:
    """
    Попытаться отправить сообщение, при ошибке только залогировать
    
    Полезно для некритичных сообщений, которые не должны падать при flood control
    
    Args:
        message: Исходное сообщение
        text: Текст для отправки
        log_prefix: Префикс для лога
        **kwargs: Параметры для safe_answer
    
    Returns:
        Отправленное сообщение или None
    """
    result = await safe_answer(message, text, **kwargs)
    
    if result is None:
        logger.info(f"{log_prefix}: {text}")
    
    return result


async def safe_send_document(
    bot,
    chat_id: int,
    document: Union[str, FSInputFile],
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_notification: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасная отправка документа через bot
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        document: Путь к файлу или FSInputFile
        caption: Подпись к документу
        parse_mode: Режим парсинга
        disable_notification: Отключить уведомление
        **kwargs: Дополнительные параметры
    
    Returns:
        Отправленное сообщение или None при ошибке
    """
    try:
        result = await telegram_rate_limiter.safe_send_with_retry(
            bot.send_document,
            chat_id=chat_id,
            document=document,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            **kwargs
        )
        
        if result is None:
            logger.warning(f"Не удалось отправить документ в чат {chat_id}")
        
        return result
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_send_document: {e}")
        return None


async def safe_bot_edit_message(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасное редактирование текста сообщения через bot
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        message_id: ID сообщения для редактирования
        text: Новый текст
        parse_mode: Режим парсинга
        reply_markup: Клавиатура
        disable_web_page_preview: Отключить превью ссылок
        **kwargs: Дополнительные параметры
    
    Returns:
        Отредактированное сообщение или None при ошибке
    """
    try:
        # ПРЕДВАРИТЕЛЬНАЯ проверка flood control
        is_blocked, remaining = await telegram_rate_limiter.flood_control.is_blocked(chat_id)
        if is_blocked:
            logger.debug(
                f"safe_bot_edit_message: Редактирование блокировано flood control "
                f"(msg_id={message_id}, chat_id={chat_id}, осталось {remaining:.0f}с)"
            )
            return None
        
        result = await telegram_rate_limiter.safe_send_with_retry(
            bot.edit_message_text,
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            **kwargs
        )
        
        if result is None:
            logger.warning(f"Не удалось отредактировать сообщение {message_id} в чате {chat_id}")
        else:
            logger.debug(f"Сообщение успешно отредактировано (msg_id={message_id}, chat_id={chat_id})")
        
        return result
    
    except TelegramBadRequest as e:
        # Игнорируем ошибку "message is not modified" - это нормально
        if "message is not modified" in str(e).lower():
            logger.debug(f"Сообщение не изменилось, пропускаем редактирование (msg_id={message_id})")
            return None
        
        logger.error(f"Ошибка при редактировании сообщения (msg_id={message_id}): {e}")
        return None
    
    except Exception as e:
        logger.error(f"Критическая ошибка в safe_bot_edit_message (msg_id={message_id}): {e}")
        return None

