"""
Модели данных для бота
"""

from .llm import LLMProvider, LLMRequest, LLMResponse
from .processing import ProcessingHistory, ProcessingRequest, ProcessingResult
from .template import Template, TemplateCreate, TemplateUpdate
from .user import User, UserCreate, UserUpdate

__all__ = [
    "User", "UserCreate", "UserUpdate",
    "Template", "TemplateCreate", "TemplateUpdate", 
    "ProcessingRequest", "ProcessingResult", "ProcessingHistory",
    "LLMProvider", "LLMRequest", "LLMResponse"
]
