"""
Исключения для обработки файлов
"""

from src.exceptions.base import BotException


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


class CloudTranscriptionError(TranscriptionError):
    """Ошибка облачной транскрипции"""
    
    def __init__(self, message: str, file_path: str = None, provider: str = "groq"):
        super().__init__(
            message=f"Ошибка облачной транскрипции ({provider}): {message}",
            file_path=file_path
        )
        self.error_code = "CLOUD_TRANSCRIPTION_ERROR"
        self.details.update({"provider": provider})


class GroqAPIError(CloudTranscriptionError):
    """Ошибка Groq API"""
    
    def __init__(self, message: str, file_path: str = None, api_error: str = None):
        super().__init__(message, file_path, "groq")
        self.error_code = "GROQ_API_ERROR"
        self.details.update({"api_error": api_error})


class SpeechmaticsAPIError(CloudTranscriptionError):
    """Ошибка Speechmatics API"""
    
    def __init__(self, message: str, file_path: str = None, api_error: str = None):
        super().__init__(message, file_path, "speechmatics")
        self.error_code = "SPEECHMATICS_API_ERROR"
        self.details.update({"api_error": api_error})


class LLMError(BotException):
    """Ошибка работы с LLM"""
    
    def __init__(self, message: str, provider: str = None, model: str = None):
        super().__init__(
            message=f"Ошибка LLM: {message}",
            error_code="LLM_ERROR",
            details={"provider": provider, "model": model}
        )
