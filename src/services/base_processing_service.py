"""
Базовый сервис обработки файлов
"""

from src.models.processing import ProcessingRequest, ProcessingResult
from src.reliability import get_circuit_breaker, get_fallback_manager
from src.services.file_service import FileService
from src.services.template_service import TemplateService
from src.services.transcription_service import TranscriptionService
from src.services.user_service import UserService


class BaseProcessingService:
    """Базовый сервис для обработки файлов"""
    
    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.user_service = UserService()
        self.template_service = TemplateService()
        self.file_service = FileService()
        
        # Компоненты надежности
        self.processing_circuit_breaker = get_circuit_breaker("file_processing")
        self.processing_fallback = get_fallback_manager("file_processing")
    
    async def process_file(self, request: ProcessingRequest) -> ProcessingResult:
        """Базовая обработка файла - должна быть переопределена"""
        raise NotImplementedError("Метод должен быть переопределен в наследнике")
