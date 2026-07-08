"""Адаптеры бэкендов транскрипции.

Один шов — пять адаптеров: whisper (локальный, он же цель fallback), groq
(режимы cloud и hybrid), leopard, speechmatics, deepgram. Адаптер владеет
своей предобработкой и родной диаризацией, если бэкенд её умеет
(Deepgram/Speechmatics); остальные возвращают текст + compression_info,
локальную диаризацию применяет сервис — ровно один раз.
"""
from typing import Dict, Protocol

from loguru import logger

from config import settings
from src.models.processing import TranscriptionResult

try:
    from src.services.speechmatics_service import speechmatics_service
    SPEECHMATICS_AVAILABLE = True
except ImportError:
    SPEECHMATICS_AVAILABLE = False

try:
    from src.services.deepgram_service import deepgram_service
    DEEPGRAM_AVAILABLE = True
except ImportError:
    DEEPGRAM_AVAILABLE = False

_EMPTY_COMPRESSION = {
    "compressed": False,
    "original_size_mb": 0,
    "compressed_size_mb": 0,
    "compression_ratio": 0,
    "compression_saved_mb": 0,
}


def _text_result(transcription: str, compression_info: dict) -> TranscriptionResult:
    """Частичный результат: только текст, диаризацию применит сервис."""
    return TranscriptionResult(
        transcription=transcription,
        diarization=None,
        speakers_text={},
        formatted_transcript="",
        speakers_summary="",
        compression_info=compression_info or dict(_EMPTY_COMPRESSION),
    )


class TranscriptionBackend(Protocol):
    """Интерфейс адаптера: доступность + транскрипция файла."""

    name: str

    def is_available(self) -> bool: ...

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult: ...


class WhisperBackend:
    """Локальный Whisper — базовый бэкенд и цель fallback."""

    name = "whisper"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return True

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        self._service._load_whisper_model()
        whisper_result = await self._service._transcribe_with_progress(file_path, language)
        transcription = whisper_result["text"].strip()
        logger.info(f"Локальная транскрибация завершена. Длина текста: {len(transcription)} символов")
        return _text_result(transcription, dict(_EMPTY_COMPRESSION))


class GroqBackend:
    """Облачная транскрипция через Groq (режимы cloud и hybrid)."""

    name = "groq"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return self._service.groq_client is not None

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        transcription, compression_info = await self._service._transcribe_with_groq(file_path)
        return _text_result(transcription, compression_info)


class LeopardBackend:
    """Локальная транскрипция через Picovoice Leopard."""

    name = "leopard"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        from src.services.transcription_service import _check_leopard_available
        return bool(_check_leopard_available() and settings.picovoice_access_key)

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        transcription, compression_info = await self._service._transcribe_with_leopard(file_path)
        return _text_result(transcription, compression_info)


class SpeechmaticsBackend:
    """Speechmatics API — транскрипция с родной диаризацией."""

    name = "speechmatics"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return SPEECHMATICS_AVAILABLE and speechmatics_service.is_available()

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        processed_file, compression_info = await self._service._preprocess_for_speechmatics(file_path)
        result = await speechmatics_service.transcribe_file(
            file_path=processed_file,
            language=language,
            enable_diarization=settings.enable_diarization,
        )
        if result:
            result.compression_info = compression_info
        return result


class DeepgramBackend:
    """Deepgram API — транскрипция с родной диаризацией."""

    name = "deepgram"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return DEEPGRAM_AVAILABLE and deepgram_service.is_available()

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        processed_file, compression_info = await self._service._preprocess_for_deepgram(file_path)
        result = await deepgram_service.transcribe_file(
            file_path=processed_file,
            language=language,
            enable_diarization=settings.enable_diarization,
        )
        if result:
            result.compression_info = compression_info
        return result


def build_backends(service) -> Dict[str, TranscriptionBackend]:
    """Реестр {режим транскрипции: адаптер}. cloud и hybrid — один groq-адаптер."""
    whisper = WhisperBackend(service)
    groq = GroqBackend(service)
    return {
        "local": whisper,
        "cloud": groq,
        "hybrid": groq,
        "leopard": LeopardBackend(service),
        "speechmatics": SpeechmaticsBackend(service),
        "deepgram": DeepgramBackend(service),
    }
