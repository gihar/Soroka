"""
Утилиты для работы с сообщениями
"""

from aiogram import Bot
from typing import Optional
from loguru import logger

from exceptions import BotException


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
