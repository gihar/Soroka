"""
Исключения для конфигурации и админских операций.
"""

from src.exceptions.base import BotException


class AdminConfigurationError(BotException):
    """Операция невозможна, потому что админ-настройка отсутствует
    или некорректна (например, не выбрана активная модель)."""


class ActivePresetDeletionError(BotException):
    """Попытка удалить или отключить пресет, который сейчас выбран
    как активная модель бота."""
