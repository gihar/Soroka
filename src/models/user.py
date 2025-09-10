"""
Модели пользователей
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Базовая модель пользователя"""
    telegram_id: int = Field(..., description="ID пользователя в Telegram")
    username: Optional[str] = Field(None, description="Имя пользователя в Telegram")
    first_name: Optional[str] = Field(None, description="Имя пользователя")
    last_name: Optional[str] = Field(None, description="Фамилия пользователя")
    preferred_llm: Optional[str] = Field(None, description="Предпочитаемый LLM провайдер")
    preferred_openai_model_key: Optional[str] = Field(None, description="Ключ выбранной модели OpenAI")
    default_template_id: Optional[int] = Field(None, description="ID шаблона по умолчанию")


class UserCreate(UserBase):
    """Модель для создания пользователя"""
    pass


class UserUpdate(BaseModel):
    """Модель для обновления пользователя"""
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    preferred_llm: Optional[str] = None


class User(UserBase):
    """Полная модель пользователя"""
    id: int = Field(..., description="ID пользователя в БД")
    created_at: datetime = Field(..., description="Дата создания")
    updated_at: datetime = Field(..., description="Дата обновления")

    class Config:
        from_attributes = True
