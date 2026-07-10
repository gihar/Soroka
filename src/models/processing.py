"""
Модели обработки файлов
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProcessingRequest(BaseModel):
    """Запрос на обработку файла"""
    file_id: Optional[str] = Field(None, description="ID файла в Telegram")
    file_path: Optional[str] = Field(None, description="Путь к локальному файлу")
    file_name: str = Field(..., description="Имя файла")
    file_url: Optional[str] = Field(None, description="Оригинальный URL для внешних файлов")
    template_id: Optional[int] = Field(None, description="ID шаблона (None для умного выбора)")
    llm_provider: str = Field(..., description="LLM провайдер")
    user_id: int = Field(..., description="ID пользователя")
    language: str = Field("ru", description="Язык транскрипции")
    is_external_file: bool = Field(False, description="Флаг внешнего файла")
    participants_list: Optional[List[Dict[str, str]]] = Field(None, description="Список участников")
    speaker_mapping: Optional[Dict[str, str]] = Field(None, description="Сопоставление спикеров с участниками")
    meeting_topic: Optional[str] = Field(None, description="Тема встречи")
    meeting_date: Optional[str] = Field(None, description="Дата встречи")
    meeting_time: Optional[str] = Field(None, description="Время встречи")
    # New optional context fields
    meeting_agenda: Optional[str] = Field(None, description="Повестка встречи")
    project_list: Optional[str] = Field(None, description="Список проектов")
    # Feature flag for context usage
    use_context: bool = Field(True, description="Использовать дополнительный контекст")


class TranscriptionResult(BaseModel):
    """Результат транскрипции"""
    transcription: str = Field(..., description="Текст транскрипции")
    diarization: Optional[Dict[str, Any]] = Field(None, description="Данные диаризации")
    speakers_text: Dict[str, str] = Field(default_factory=dict, description="Текст по говорящим")
    formatted_transcript: str = Field("", description="Форматированная транскрипция")
    speakers_summary: str = Field("", description="Резюме говорящих")
    compression_info: Optional[Dict[str, Any]] = Field(None, description="Информация о сжатии файла")


class ProcessingResult(BaseModel):
    """Результат обработки"""
    transcription_result: TranscriptionResult
    protocol_text: str = Field(..., description="Сгенерированный протокол")
    template_used: Dict[str, Any] = Field(..., description="Использованный шаблон")
    llm_provider_used: str = Field(..., description="Использованный LLM провайдер")
    llm_model_used: Optional[str] = Field(None, description="Использованная модель LLM")
    processing_duration: Optional[float] = Field(None, description="Время обработки в секундах")


class ProcessingHistory(BaseModel):
    """История обработки"""
    id: int = Field(..., description="ID записи")
    user_id: int = Field(..., description="ID пользователя")
    file_name: str = Field(..., description="Имя файла")
    template_id: int = Field(..., description="ID шаблона")
    llm_provider: str = Field(..., description="LLM провайдер")
    transcription_text: str = Field(..., description="Текст транскрипции")
    result_text: str = Field(..., description="Результирующий текст")
    created_at: datetime = Field(..., description="Дата создания")

    class Config:
        from_attributes = True
