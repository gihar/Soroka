"""
Обработчики сообщений Telegram бота
"""

from .command_handlers import setup_command_handlers
from .callback_handlers import setup_callback_handlers
from .message_handlers import setup_message_handlers
from .template_handlers import setup_template_handlers

__all__ = [
    "setup_command_handlers",
    "setup_callback_handlers", 
    "setup_message_handlers",
    "setup_template_handlers"
]
