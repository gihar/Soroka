"""
Кастомные исключения для бота
"""

from .base import BotException
from .configuration import ActivePresetDeletionError, AdminConfigurationError
from .file import FileError, FileSizeError, FileTypeError
from .processing import LLMError, LLMInsufficientCreditsError, ProcessingError, TranscriptionError
from .template import TemplateNotFoundError, TemplateValidationError
from .user import UserCreationError, UserNotFoundError

__all__ = [
    "BotException",
    "UserNotFoundError", "UserCreationError",
    "TemplateNotFoundError", "TemplateValidationError",
    "ProcessingError", "TranscriptionError", "LLMError", "LLMInsufficientCreditsError",
    "FileError", "FileSizeError", "FileTypeError",
    "AdminConfigurationError", "ActivePresetDeletionError"
]
