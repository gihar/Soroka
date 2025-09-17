"""
Конфигурация приложения
"""

from pydantic_settings import BaseSettings
from pydantic import Field, validator, BaseModel
from typing import Optional, List


class OpenAIModelPreset(BaseModel):
    key: str = Field(..., description="Уникальный ключ пресета (slug)")
    name: str = Field(..., description="Отображаемое имя в меню")
    model: str = Field(..., description="ID модели для API")
    base_url: Optional[str] = Field(None, description="Базовый URL для этого пресета")


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram Bot
    telegram_token: str = Field(..., description="Токен Telegram бота")
    
    # OpenAI
    openai_api_key: Optional[str] = Field(None, description="API ключ OpenAI")
    openai_base_url: Optional[str] = Field(None, description="Базовый URL для OpenAI API")
    openai_model: str = Field("gpt-3.5-turbo", description="Модель OpenAI для генерации")
    
    # Наборы моделей OpenAI с собственными базовыми URL (по одному API ключу)
    # Формат переменной окружения OPENAI_MODELS: JSON-массив объектов вида
    # [
    #   {"key": "openai_gpt4o", "name": "OpenAI: gpt-4o", "model": "gpt-4o", "base_url": "https://api.openai.com/v1"},
    #   {"key": "local_oq", "name": "OpenRouter: llama3.1:70b", "model": "meta-llama/llama-3.1-70b-instruct", "base_url": "https://openrouter.ai/api/v1"}
    # ]
    # Если не задано, автоматически формируется 1 пресет из OPENAI_MODEL и OPENAI_BASE_URL
    
    openai_models: List[OpenAIModelPreset] = Field(default_factory=list, description="Список пресетов моделей OpenAI")
    
    # Anthropic Claude
    anthropic_api_key: Optional[str] = Field(None, description="API ключ Anthropic")
    
    # Yandex GPT
    yandex_api_key: Optional[str] = Field(None, description="API ключ Yandex GPT")
    yandex_folder_id: Optional[str] = Field(None, description="ID папки Yandex Cloud")
    
    # LLM Таймауты
    llm_timeout_seconds: float = Field(30.0, description="Общий таймаут ожидания ответа от LLM (в секундах)")
    
    # База данных
    database_url: str = Field("sqlite:///bot.db", description="URL базы данных")
    
    # Настройки файлов
    max_file_size: int = Field(20 * 1024 * 1024, description="Максимальный размер файла в байтах")
    telegram_max_file_size: int = Field(20 * 1024 * 1024, description="Максимальный размер файла для Telegram Bot API в байтах")
    max_external_file_size: int = Field(50 * 1024 * 1024, description="Максимальный размер файла из внешних источников (Google Drive, Яндекс.Диск) в байтах")
    oom_max_file_size_mb: Optional[float] = Field(
        None,
        description="Максимальный размер файла для стадии транскрипции (MB). По умолчанию берётся из MAX_FILE_SIZE"
    )
    temp_dir: str = Field("temp", description="Директория для временных файлов")
    
    # Логирование
    log_level: str = Field("INFO", description="Уровень логирования")
    
    # SSL настройки
    ssl_verify: bool = Field(False, description="Проверка SSL сертификатов")
    
    # Транскрипция
    transcription_mode: str = Field("local", description="Режим транскрипции: local (локально), cloud (облако), hybrid (гибридный), speechmatics или leopard")
    groq_api_key: Optional[str] = Field(None, description="API ключ Groq для облачной транскрипции")
    groq_model: str = Field("whisper-large-v3-turbo", description="Модель Groq для транскрипции")
    
    # Speechmatics
    speechmatics_api_key: Optional[str] = Field(None, description="API ключ Speechmatics для транскрипции и диаризации")
    speechmatics_language: str = Field("ru", description="Язык для Speechmatics API")
    speechmatics_domain: Optional[str] = Field(None, description="Домен для Speechmatics (finance, medical и т.д.)")
    speechmatics_operating_point: str = Field("standard", description="Операционная точка Speechmatics: standard или enhanced")
    
    @validator('speechmatics_operating_point')
    def validate_speechmatics_operating_point(cls, v):
        """Валидация operating_point для Speechmatics"""
        valid_points = ['standard', 'enhanced']
        if v not in valid_points:
            raise ValueError(f"speechmatics_operating_point должен быть одним из: {', '.join(valid_points)}")
        return v
    
    # Диаризация
    enable_diarization: bool = Field(False, description="Включить диаризацию (разделение говорящих). По умолчанию отключено для стабильности.")
    diarization_provider: str = Field("whisperx", description="Провайдер диаризации: whisperx, pyannote, picovoice")
    huggingface_token: Optional[str] = Field(None, description="Токен Hugging Face для моделей диаризации")
    picovoice_access_key: Optional[str] = Field(None, description="Access Key для Picovoice API")
    leopard_model_path: Optional[str] = Field(None, description="Путь к .pv модели Picovoice Leopard (для выбора языка, например русский)")
    diarization_device: str = Field("auto", description="Устройство для диаризации: auto, cpu, mps, cuda")
    compute_type: str = Field("auto", description="Тип вычислений: auto, int8, float16, float32")
    max_speakers: int = Field(10, description="Максимальное количество говорящих")
    min_speakers: int = Field(1, description="Минимальное количество говорящих")
    
    # Очистка файлов
    enable_cleanup: bool = Field(True, description="Включить автоматическую очистку временных файлов")
    cleanup_interval_minutes: int = Field(30, description="Интервал очистки файлов в минутах")
    temp_file_max_age_hours: int = Field(2, description="Максимальный возраст временных файлов в часах")
    cache_max_age_hours: int = Field(24, description="Максимальный возраст кэш файлов в часах")
    
    @validator('openai_models', pre=True, always=True)
    def ensure_openai_models(cls, v, values):
        """Гарантируем наличие хотя бы одного пресета OpenAI.
        Если OPENAI_MODELS не задан, используем одиночные OPENAI_MODEL/OPENAI_BASE_URL.
        """
        try:
            # Если явно передан список пресетов
            if isinstance(v, list) and len(v) > 0:
                # Приведение к целевой схеме произойдёт автоматически
                return v
        except Exception:
            pass

        # Формируем одиночный дефолтный пресет из старых настроек
        model = values.get('openai_model', 'gpt-3.5-turbo')
        base_url = values.get('openai_base_url')
        default_preset = {
            "key": "default",
            "name": f"OpenAI: {model}",
            "model": model,
            "base_url": base_url
        }
        return [default_preset]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
