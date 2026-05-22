"""
Утилиты для работы с сообщениями
"""

from typing import Optional

from aiogram import Bot
from loguru import logger

from src.exceptions import BotException


def escape_markdown_v2(text: str) -> str:
    """
    Экранировать специальные символы Markdown для безопасной отправки в Telegram
    
    Args:
        text: Текст для экранирования
        
    Returns:
        Экранированный текст
    """
    if not text:
        return text
    
    # Символы, которые нужно экранировать в Markdown
    escape_chars = ['*', '_', '`', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    result = str(text)
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    
    return result


def escape_markdown(text: str) -> str:
    """
    Экранировать специальные символы для старого режима Markdown (parse_mode="Markdown")
    
    В старом Markdown нужно экранировать только: * _ ` [
    
    Args:
        text: Текст для экранирования
        
    Returns:
        Экранированный текст
    """
    if not text:
        return text
    
    # Символы для старого Markdown режима
    escape_chars = ['*', '_', '`', '[']
    
    result = str(text)
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    
    return result


async def send_long_message(bot: Bot, chat_id: int, text: str, 
                          parse_mode: Optional[str] = "Markdown", 
                          max_length: int = 4096) -> None:
    """Отправить длинное сообщение по частям"""
    try:
        if len(text) <= max_length:
            await bot.send_message(chat_id, text, parse_mode=parse_mode)
            return
        
        # Разбиваем текст на части
        parts = []
        current_part = ""
        
        for line in text.split('\n'):
            if len(current_part) + len(line) + 1 <= max_length:
                current_part += line + '\n'
            else:
                if current_part:
                    parts.append(current_part.strip())
                current_part = line + '\n'
        
        if current_part:
            parts.append(current_part.strip())
        
        # Отправляем части
        for i, part in enumerate(parts):
            try:
                if i == 0:
                    await bot.send_message(
                        chat_id, 
                        f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n{part}",
                        parse_mode=parse_mode
                    )
                else:
                    await bot.send_message(
                        chat_id,
                        f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n{part}",
                        parse_mode=parse_mode
                    )
            except Exception as e:
                logger.error(f"Ошибка при отправке части {i+1}/{len(parts)}: {e}")
                # Продолжаем отправлять остальные части
                continue
                
    except Exception as e:
        logger.error(f"Ошибка при отправке длинного сообщения: {e}")
        # Отправляем сообщение об ошибке
        try:
            await bot.send_message(
                chat_id, 
                "❌ Произошла ошибка при отправке протокола. Попробуйте еще раз."
            )
        except Exception:
            pass  # Игнорируем ошибки при отправке сообщения об ошибке


def format_error_message(exception: Exception) -> str:
    """Форматировать сообщение об ошибке для пользователя"""
    if isinstance(exception, BotException):
        return f"❌ {exception.message}"
    
    # Для разных типов ошибок возвращаем понятные сообщения
    error_str = str(exception).lower()
    
    if "connection" in error_str or "timeout" in error_str:
        return "❌ Проблемы с сетевым соединением. Попробуйте еще раз."
    
    if "file not found" in error_str:
        return "❌ Файл не найден. Попробуйте отправить файл заново."
    
    if "permission" in error_str:
        return "❌ Недостаточно прав для выполнения операции."
    
    if "memory" in error_str or "space" in error_str:
        return "❌ Недостаточно ресурсов для обработки файла. Попробуйте файл меньшего размера."
    
    # Общее сообщение для неизвестных ошибок
    return "❌ Произошла неожиданная ошибка. Попробуйте еще раз или обратитесь в поддержку."


def format_file_info(file_name: str, file_size: int, duration: Optional[float] = None) -> str:
    """Форматировать информацию о файле"""
    size_mb = file_size / (1024 * 1024)
    info = f"📁 **{file_name}**\n📏 Размер: {size_mb:.1f} MB"
    
    if duration:
        info += f"\n⏱ Длительность: {duration:.1f} сек"
    
    return info


def format_processing_progress(stage: str, details: str = "") -> str:
    """Форматировать сообщение о прогрессе обработки"""
    stage_emojis = {
        "download": "⬇️",
        "transcription": "🎤", 
        "diarization": "👥",
        "llm": "🧠",
        "template": "📝",
        "complete": "✅"
    }
    
    emoji = stage_emojis.get(stage, "⏳")
    message = f"{emoji} **Обработка файла...**\n\n"
    
    if details:
        message += details
    
    return message


def safe_send_message(bot, chat_id: int, text: str, parse_mode: str = "Markdown", max_length: int = 4096):
    """
    Безопасная отправка сообщения с автоматической обработкой длинных сообщений
    
    Args:
        bot: Telegram bot instance
        chat_id: ID чата
        text: Текст сообщения
        parse_mode: Режим парсинга (Markdown или HTML)
        max_length: Максимальная длина сообщения
    """
    import asyncio

    from loguru import logger
    
    async def _safe_send():
        try:
            # Проверяем длину сообщения
            if len(text) <= max_length:
                await bot.send_message(chat_id, text, parse_mode=parse_mode)
                return
            
            # Если сообщение слишком длинное, разбиваем на части
            parts = []
            current_part = ""
            
            for line in text.split('\n'):
                if len(current_part) + len(line) + 1 <= max_length:
                    current_part += line + '\n'
                else:
                    if current_part:
                        parts.append(current_part.strip())
                    current_part = line + '\n'
            
            if current_part:
                parts.append(current_part.strip())
            
            # Отправляем части
            for i, part in enumerate(parts):
                try:
                    header = f"📄 Часть {i+1}/{len(parts)}\n\n"
                    full_message = header + part
                    
                    if len(full_message) <= max_length:
                        await bot.send_message(chat_id, full_message, parse_mode=parse_mode)
                    else:
                        # Если с заголовком не помещается, отправляем без него
                        await bot.send_message(chat_id, part, parse_mode=parse_mode)
                        
                except Exception as e:
                    logger.error(f"Ошибка отправки части {i+1}: {e}")
                    # Пробуем отправить без форматирования
                    try:
                        await bot.send_message(chat_id, part)
                    except Exception as e2:
                        logger.error(f"Критическая ошибка отправки части {i+1}: {e2}")
                        # Отправляем обрезанную версию
                        await bot.send_message(chat_id, part[:max_length])
                        
        except Exception as e:
            logger.error(f"Ошибка в safe_send_message: {e}")
            # Пробуем отправить без форматирования
            try:
                await bot.send_message(chat_id, text[:max_length])
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки сообщения: {e2}")
                raise e2
    
    # Запускаем асинхронную функцию
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Если мы уже в асинхронном контексте, создаем задачу
            return asyncio.create_task(_safe_send())
        else:
            # Если нет активного цикла, запускаем новый
            return asyncio.run(_safe_send())
    except RuntimeError:
        # Если нет активного цикла событий, создаем новый
        return asyncio.run(_safe_send())
