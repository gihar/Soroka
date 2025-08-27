"""
Утилиты для логирования
"""

from loguru import logger
from config import settings


def setup_logging():
    """Настройка логирования"""
    logger.remove()  # Удаляем стандартный обработчик
    
    # Добавляем обработчик для консоли
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True
    )
    
    # Добавляем обработчик для файла
    logger.add(
        "logs/bot.log",
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="1 week",
        compression="zip"
    )


def log_processing_start(file_name: str, user_id: int, template_id: int, llm_provider: str):
    """Логирование начала обработки"""
    logger.info(
        f"Начало обработки: файл={file_name}, пользователь={user_id}, "
        f"шаблон={template_id}, LLM={llm_provider}"
    )


def log_processing_success(file_name: str, duration: float, transcription_length: int):
    """Логирование успешной обработки"""
    logger.info(
        f"Обработка завершена: файл={file_name}, длительность={duration:.2f}с, "
        f"длина_транскрипции={transcription_length}"
    )


def log_processing_error(file_name: str, error: str, stage: str = None):
    """Логирование ошибки обработки"""
    stage_info = f", стадия={stage}" if stage else ""
    logger.error(f"Ошибка обработки: файл={file_name}{stage_info}, ошибка={error}")
