"""
Кастомные исключения для бота
"""

from .base import BotException
from .user import UserNotFoundError, UserCreationError
from .template import TemplateNotFoundError, TemplateValidationError
from .processing import ProcessingError, TranscriptionError, LLMError, LLMInsufficientCreditsError
from .file import FileError, FileSizeError, FileTypeError
from .configuration import AdminConfigurationError, ActivePresetDeletionError

__all__ = [
    "BotException",
    "UserNotFoundError", "UserCreationError",
    "TemplateNotFoundError", "TemplateValidationError",
    "ProcessingError", "TranscriptionError", "LLMError", "LLMInsufficientCreditsError",
    "FileError", "FileSizeError", "FileTypeError",
    "AdminConfigurationError", "ActivePresetDeletionError"
]
