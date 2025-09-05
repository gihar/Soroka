"""
Исключения для работы с файлами
"""

from src.exceptions.base import BotException


class FileError(BotException):
    """Общая ошибка работы с файлом"""
    
    def __init__(self, message: str, file_name: str = None, file_id: str = None):
        super().__init__(
            message=message,
            error_code="FILE_ERROR",
            details={"file_name": file_name, "file_id": file_id}
        )


class FileSizeError(BotException):
    """Ошибка размера файла"""
    
    def __init__(self, file_size: int, max_size: int, file_name: str = None):
        message = f"Файл слишком большой: {file_size} байт (максимум: {max_size} байт)"
        super().__init__(
            message=message,
            error_code="FILE_SIZE_ERROR",
            details={
                "file_size": file_size,
                "max_size": max_size,
                "file_name": file_name
            }
        )


class FileTypeError(BotException):
    """Ошибка типа файла"""
    
    def __init__(self, file_type: str, allowed_types: list, file_name: str = None):
        message = f"Неподдерживаемый тип файла: {file_type}. Разрешены: {', '.join(allowed_types)}"
        super().__init__(
            message=message,
            error_code="FILE_TYPE_ERROR",
            details={
                "file_type": file_type,
                "allowed_types": allowed_types,
                "file_name": file_name
            }
        )
