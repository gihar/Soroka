"""
Модели для работы с LLM
"""

from typing import Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


class LLMProviderType(str, Enum):
    """Типы LLM провайдеров"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    YANDEX = "yandex"


class LLMRequest(BaseModel):
    """Запрос к LLM"""
    transcription: str = Field(..., description="Текст транскрипции")
    template_variables: Dict[str, str] = Field(..., description="Переменные шаблона")
    diarization_data: Optional[Dict[str, Any]] = Field(None, description="Данные диаризации")
    provider: LLMProviderType = Field(..., description="Тип провайдера")
    model: Optional[str] = Field(None, description="Название модели")
    temperature: float = Field(0.3, description="Температура генерации", ge=0.0, le=2.0)


class LLMResponse(BaseModel):
    """Ответ от LLM"""
    extracted_data: Dict[str, Any] = Field(..., description="Извлеченные данные")
    provider_used: str = Field(..., description="Использованный провайдер")
    llm_model_used: Optional[str] = Field(None, description="Использованная модель")
    tokens_used: Optional[int] = Field(None, description="Количество использованных токенов")
    processing_time: Optional[float] = Field(None, description="Время обработки")
    
    class Config:
        protected_namespaces = ()


class LLMProvider(BaseModel):
    """Информация о LLM провайдере"""
    key: str = Field(..., description="Ключ провайдера")
    name: str = Field(..., description="Название провайдера")
    is_available: bool = Field(..., description="Доступность провайдера")
    models: list[str] = Field(default_factory=list, description="Доступные модели")
    
    class Config:
        from_attributes = True
