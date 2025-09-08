#!/usr/bin/env python3
"""
Enhanced Telegram Bot - Точка входа в приложение
"""

import asyncio
import ssl
import shutil
import os
import sys
from loguru import logger
from config import settings

# Добавляем src в путь для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Импортируем финальную оптимизированную версию бота
from src.bot import main_enhanced as main
from src.utils.logging_utils import setup_logging

try:
    import urllib3
except ImportError:
    urllib3 = None

# Глобальное отключение SSL verification, если настроено
if not settings.ssl_verify:
    if urllib3:
        try:
            # Отключаем SSL verification для urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass  # Игнорируем ошибки отключения предупреждений
    
    # Отключаем SSL verification глобально
    ssl._create_default_https_context = ssl._create_unverified_context


def check_ffmpeg():
    """Проверка наличия ffmpeg в системе"""
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg не найден в системе!")
        logger.error("Для транскрипции аудио и видео файлов требуется ffmpeg.")
        logger.error("Установите ffmpeg:")
        logger.error("  macOS: brew install ffmpeg")
        logger.error("  Ubuntu/Debian: sudo apt-get install ffmpeg")
        logger.error("  CentOS/RHEL: sudo yum install ffmpeg")
        logger.error("Или запустите: ./install.sh для автоматической установки")
        return False
    logger.info("✅ ffmpeg найден в системе")
    return True


if __name__ == "__main__":
    # Настраиваем логирование
    setup_logging()
    
    # Проверяем наличие токена
    if not settings.telegram_token:
        logger.error("TELEGRAM_TOKEN не установлен. Проверьте файл .env")
        exit(1)
    
    # Проверяем наличие хотя бы одного API ключа для LLM
    if not any([settings.openai_api_key, settings.anthropic_api_key, 
                settings.yandex_api_key]):
        logger.warning("Не установлены API ключи для LLM провайдеров")
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        logger.warning("ffmpeg не найден. Транс делакрипция аудио/видео может не работать.")
        logger.warning("Рекомендуется установить ffmpeg для полной функциональности.")
    
    logger.info("🚀 Запуск Soroka Telegram Bot...")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        exit(1)