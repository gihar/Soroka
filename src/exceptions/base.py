"""
Базовые исключения
"""


class BotException(Exception):
    """Базовое исключение для бота"""
    
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self):
        return f"{self.message}"
    
    def to_dict(self):
        """Преобразовать исключение в словарь"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details
        }
