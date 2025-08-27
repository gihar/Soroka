"""
Исключения для работы с шаблонами
"""

from exceptions.base import BotException


class TemplateNotFoundError(BotException):
    """Шаблон не найден"""
    
    def __init__(self, template_id: int):
        super().__init__(
            message=f"Шаблон с ID {template_id} не найден",
            error_code="TEMPLATE_NOT_FOUND",
            details={"template_id": template_id}
        )


class TemplateValidationError(BotException):
    """Ошибка валидации шаблона"""
    
    def __init__(self, message: str, template_content: str = None):
        super().__init__(
            message=f"Ошибка валидации шаблона: {message}",
            error_code="TEMPLATE_VALIDATION_ERROR",
            details={"template_content": template_content}
        )
