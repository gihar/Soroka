"""
Модели данных для бота
"""

from .processing import ProcessingHistory, ProcessingRequest, ProcessingResult
from .template import Template, TemplateCreate, TemplateUpdate
from .user import User, UserCreate, UserUpdate

__all__ = [
    "User", "UserCreate", "UserUpdate",
    "Template", "TemplateCreate", "TemplateUpdate", 
    "ProcessingRequest", "ProcessingResult", "ProcessingHistory",
]
