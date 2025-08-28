"""
Исключения для работы с пользователями
"""

from src.exceptions.base import BotException


class UserNotFoundError(BotException):
    """Пользователь не найден"""
    
    def __init__(self, user_id: int):
        super().__init__(
            message=f"Пользователь с ID {user_id} не найден",
            error_code="USER_NOT_FOUND",
            details={"user_id": user_id}
        )


class UserCreationError(BotException):
    """Ошибка создания пользователя"""
    
    def __init__(self, telegram_id: int, reason: str = None):
        message = f"Не удалось создать пользователя с Telegram ID {telegram_id}"
        if reason:
            message += f": {reason}"
        
        super().__init__(
            message=message,
            error_code="USER_CREATION_ERROR",
            details={"telegram_id": telegram_id, "reason": reason}
        )
