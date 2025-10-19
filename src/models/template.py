"""
Модели шаблонов
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class TemplateBase(BaseModel):
    """Базовая модель шаблона"""
    name: str = Field(..., description="Название шаблона", min_length=3, max_length=100)
    description: Optional[str] = Field(None, description="Описание шаблона", max_length=500)
    content: str = Field(..., description="Содержимое шаблона", min_length=10)
    is_default: bool = Field(False, description="Является ли шаблон по умолчанию")
    category: Optional[str] = Field(None, description="Категория шаблона (management, product, technical, sales)")
    tags: Optional[List[str]] = Field(None, description="Теги для классификации")
    keywords: Optional[List[str]] = Field(None, description="Ключевые слова для ML-классификации")


class TemplateCreate(TemplateBase):
    """Модель для создания шаблона"""
    created_by: Optional[int] = Field(None, description="ID создателя шаблона")


class TemplateUpdate(BaseModel):
    """Модель для обновления шаблона"""
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, min_length=10)
    is_default: Optional[bool] = None


class Template(TemplateBase):
    """Полная модель шаблона"""
    id: int = Field(..., description="ID шаблона")
    created_by: Optional[int] = Field(None, description="ID создателя")
    created_at: datetime = Field(..., description="Дата создания")

    class Config:
        from_attributes = True
