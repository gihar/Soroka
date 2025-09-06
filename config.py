"""
Конфигурация приложения
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram Bot
    telegram_token: str = Field(..., description="Токен Telegram бота")
    
    # OpenAI
    openai_api_key: Optional[str] = Field(None, description="API ключ OpenAI")
    openai_base_url: Optional[str] = Field(None, description="Базовый URL для OpenAI API")
    openai_model: str = Field("gpt-3.5-turbo", description="Модель OpenAI для генерации")
    
    # Anthropic Claude
    anthropic_api_key: Optional[str] = Field(None, description="API ключ Anthropic")
    
    # Yandex GPT
    yandex_api_key: Optional[str] = Field(None, description="API ключ Yandex GPT")
    yandex_folder_id: Optional[str] = Field(None, description="ID папки Yandex Cloud")
    
    # База данных
    database_url: str = Field("sqlite:///bot.db", description="URL базы данных")
    
    # Настройки файлов
    max_file_size: int = Field(20 * 1024 * 1024, description="Максимальный размер файла в байтах")
    telegram_max_file_size: int = Field(20 * 1024 * 1024, description="Максимальный размер файла для Telegram Bot API в байтах")
    max_external_file_size: int = Field(50 * 1024 * 1024, description="Максимальный размер файла из внешних источников (Google Drive, Яндекс.Диск) в байтах")
    temp_dir: str = Field("temp", description="Директория для временных файлов")
    
    # Логирование
    log_level: str = Field("INFO", description="Уровень логирования")
    
    # SSL настройки
    ssl_verify: bool = Field(False, description="Проверка SSL сертификатов")
    
    # Транскрипция
    transcription_mode: str = Field("local", description="Режим транскрипции: local (локально), cloud (облако), hybrid (гибридный) или speechmatics")
    groq_api_key: Optional[str] = Field(None, description="API ключ Groq для облачной транскрипции")
    groq_model: str = Field("whisper-large-v3-turbo", description="Модель Groq для транскрипции")
    
    # Speechmatics
    speechmatics_api_key: Optional[str] = Field(None, description="API ключ Speechmatics для транскрипции и диаризации")
    speechmatics_language: str = Field("ru", description="Язык для Speechmatics API")
    speechmatics_domain: Optional[str] = Field(None, description="Домен для Speechmatics (finance, medical и т.д.)")
    speechmatics_operating_point: str = Field("standard", description="Операционная точка Speechmatics: standard или enhanced")
    
    # Диаризация
    enable_diarization: bool = Field(False, description="Включить диаризацию (разделение говорящих). По умолчанию отключено для стабильности.")
    diarization_provider: str = Field("whisperx", description="Провайдер диаризации: whisperx, pyannote, picovoice")
    huggingface_token: Optional[str] = Field(None, description="Токен Hugging Face для моделей диаризации")
    picovoice_access_key: Optional[str] = Field(None, description="Access Key для Picovoice API")
    diarization_device: str = Field("auto", description="Устройство для диаризации: auto, cpu, mps, cuda")
    compute_type: str = Field("auto", description="Тип вычислений: auto, int8, float16, float32")
    max_speakers: int = Field(10, description="Максимальное количество говорящих")
    min_speakers: int = Field(1, description="Минимальное количество говорящих")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
