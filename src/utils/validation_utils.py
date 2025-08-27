"""
Утилиты для валидации
"""

import os
from typing import List


def validate_file_type(file_name: str, allowed_extensions: List[str]) -> bool:
    """Валидация типа файла по расширению"""
    if not file_name:
        return False
    
    file_ext = os.path.splitext(file_name.lower())[1]
    return file_ext in [ext.lower() for ext in allowed_extensions]


def validate_file_size(file_size: int, max_size: int) -> bool:
    """Валидация размера файла"""
    return file_size <= max_size


def get_file_extension(file_name: str) -> str:
    """Получить расширение файла"""
    if not file_name:
        return ""
    return os.path.splitext(file_name.lower())[1]


def is_audio_file(file_name: str) -> bool:
    """Проверить, является ли файл аудио"""
    audio_extensions = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac']
    return validate_file_type(file_name, audio_extensions)


def is_video_file(file_name: str) -> bool:
    """Проверить, является ли файл видео"""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v']
    return validate_file_type(file_name, video_extensions)
