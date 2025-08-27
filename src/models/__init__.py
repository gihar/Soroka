"""
Модели данных для бота
"""

from .user import User, UserCreate, UserUpdate
from .template import Template, TemplateCreate, TemplateUpdate
from .processing import ProcessingRequest, ProcessingResult, ProcessingHistory
from .llm import LLMProvider, LLMRequest, LLMResponse

__all__ = [
    "User", "UserCreate", "UserUpdate",
    "Template", "TemplateCreate", "TemplateUpdate", 
    "ProcessingRequest", "ProcessingResult", "ProcessingHistory",
    "LLMProvider", "LLMRequest", "LLMResponse"
]
