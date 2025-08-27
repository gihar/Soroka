"""
Кастомные исключения для бота
"""

from .base import BotException
from .user import UserNotFoundError, UserCreationError
from .template import TemplateNotFoundError, TemplateValidationError
from .processing import ProcessingError, TranscriptionError, LLMError
from .file import FileError, FileSizeError, FileTypeError

__all__ = [
    "BotException",
    "UserNotFoundError", "UserCreationError",
    "TemplateNotFoundError", "TemplateValidationError", 
    "ProcessingError", "TranscriptionError", "LLMError",
    "FileError", "FileSizeError", "FileTypeError"
]
