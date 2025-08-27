"""
Сервис для работы с файлами
"""

import os
from typing import List
from aiogram import Bot
from loguru import logger

from exceptions.file import FileError, FileSizeError, FileTypeError
from config import settings


class FileService:
    """Сервис для работы с файлами"""
    
    SUPPORTED_AUDIO_TYPES = ['audio', 'voice']
    SUPPORTED_VIDEO_TYPES = ['video', 'video_note']
    SUPPORTED_DOCUMENT_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.mp4', '.avi', '.mov', '.mkv']
    
    def __init__(self):
        self.bot = Bot(token=settings.telegram_token)
    
    def validate_file(self, file_obj, content_type: str, file_name: str = None) -> None:
        """Валидация файла"""
        # Проверка размера
        if file_obj.file_size > settings.max_file_size:
            raise FileSizeError(
                file_obj.file_size, 
                settings.max_file_size, 
                file_name
            )
        
        # Проверка размера для Telegram API
        if file_obj.file_size > settings.telegram_max_file_size:
            raise FileSizeError(
                file_obj.file_size,
                settings.telegram_max_file_size,
                file_name
            )
        
        # Проверка типа файла
        if content_type == 'document' and file_name:
            file_ext = os.path.splitext(file_name.lower())[1]
            if file_ext not in self.SUPPORTED_DOCUMENT_EXTENSIONS:
                raise FileTypeError(
                    file_ext,
                    self.SUPPORTED_DOCUMENT_EXTENSIONS,
                    file_name
                )
        elif content_type not in (self.SUPPORTED_AUDIO_TYPES + self.SUPPORTED_VIDEO_TYPES):
            raise FileTypeError(
                content_type,
                self.SUPPORTED_AUDIO_TYPES + self.SUPPORTED_VIDEO_TYPES,
                file_name
            )
    
    async def get_telegram_file_url(self, file_id: str) -> str:
        """Получить URL файла из Telegram"""
        try:
            file_info = await self.bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{settings.telegram_token}/{file_info.file_path}"
            logger.info(f"Получен URL файла: {file_info.file_path}")
            return file_url
        except Exception as e:
            if "file is too big" in str(e).lower():
                raise FileSizeError(0, settings.telegram_max_file_size)
            logger.error(f"Ошибка при получении файла {file_id}: {e}")
            raise FileError(f"Не удалось получить файл: {e}", file_id=file_id)
    
    def get_supported_formats(self) -> List[str]:
        """Получить список поддерживаемых форматов"""
        return {
            "audio": ["MP3", "WAV", "M4A", "OGG"],
            "video": ["MP4", "AVI", "MOV", "MKV"],
            "content_types": ["Аудио сообщения", "Видео сообщения", "Видео заметки", "Документы"]
        }
