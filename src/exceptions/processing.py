"""
Исключения для обработки файлов
"""

from exceptions.base import BotException


class ProcessingError(BotException):
    """Общая ошибка обработки"""
    
    def __init__(self, message: str, file_name: str = None, stage: str = None):
        super().__init__(
            message=message,
            error_code="PROCESSING_ERROR",
            details={"file_name": file_name, "stage": stage}
        )


class TranscriptionError(BotException):
    """Ошибка транскрипции"""
    
    def __init__(self, message: str, file_path: str = None):
        super().__init__(
            message=f"Ошибка транскрипции: {message}",
            error_code="TRANSCRIPTION_ERROR",
            details={"file_path": file_path}
        )


class LLMError(BotException):
    """Ошибка работы с LLM"""
    
    def __init__(self, message: str, provider: str = None, model: str = None):
        super().__init__(
            message=f"Ошибка LLM: {message}",
            error_code="LLM_ERROR",
            details={"provider": provider, "model": model}
        )
