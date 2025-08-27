"""
Базовый сервис обработки файлов
"""

import time
from typing import Dict, Any
from loguru import logger

from models.processing import ProcessingRequest, ProcessingResult
from services.transcription_service import TranscriptionService
from services.enhanced_llm_service import EnhancedLLMService
from services.user_service import UserService
from services.template_service import TemplateService
from services.file_service import FileService
from exceptions.processing import ProcessingError
from reliability import (
    global_rate_limiter, USER_REQUEST_LIMIT,
    get_circuit_breaker, get_fallback_manager
)


class BaseProcessingService:
    """Базовый сервис для обработки файлов"""
    
    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.llm_service = EnhancedLLMService()
        self.user_service = UserService()
        self.template_service = TemplateService()
        self.file_service = FileService()
        
        # Компоненты надежности
        self.processing_circuit_breaker = get_circuit_breaker("file_processing")
        self.processing_fallback = get_fallback_manager("file_processing")
    
    async def process_file(self, request: ProcessingRequest) -> ProcessingResult:
        """Базовая обработка файла - должна быть переопределена"""
        raise NotImplementedError("Метод должен быть переопределен в наследнике")
    
    def _get_template_variables(self) -> Dict[str, Any]:
        """Получить переменные для шаблона"""
        return {
            "participants": [],
            "decisions": [],
            "action_items": [],
            "topics": [],
            "next_meeting": "",
            "summary": ""
        }
