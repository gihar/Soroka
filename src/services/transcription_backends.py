"""Адаптеры бэкендов транскрипции.

Один шов — пять адаптеров: whisper (локальный, он же цель fallback), groq
(режимы cloud и hybrid), leopard, speechmatics, deepgram. Адаптер владеет
своей предобработкой и родной диаризацией, если бэкенд её умеет
(Deepgram/Speechmatics); остальные возвращают текст + compression_info,
локальную диаризацию применяет сервис — ровно один раз.
"""
import asyncio
import os
from pathlib import Path
from typing import Dict, Protocol

from loguru import logger

from src.config import settings
from src.exceptions.processing import (
    CloudTranscriptionError,
    GroqAPIError,
    TranscriptionError,
)
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

# 16KHz моно MP3 — общая подготовка для облачных API
_CLOUD_FFMPEG_ARGS = [
    "-ar", "16000",
    "-ac", "1",
    "-map", "0:a",
    "-c:a", "mp3",
    "-b:a", "64k",
]

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
    """Локальный Whisper — базовый бэкенд и цель fallback.

    Модель и её OOM-жизненный цикл принадлежат сервису (общая память процесса).
    """

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

    # Максимальный размер файла для Groq API (25 MB)
    MAX_FILE_SIZE = 25 * 1024 * 1024

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return self._service.groq_client is not None

    def _check_file_size(self, file_path: str) -> bool:
        """Подходит ли файл для Groq по размеру и доступной памяти."""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)

            if file_size > self.MAX_FILE_SIZE:
                max_size_mb = self.MAX_FILE_SIZE / (1024 * 1024)
                logger.warning(
                    f"Файл слишком большой для облачной транскрипции: {file_size_mb:.1f}MB "
                    f"(максимум: {max_size_mb}MB)"
                )
                return False

            can_process, reason = self._service.oom_protection.can_process_file(file_size_mb)
            if not can_process:
                logger.warning(f"Файл не может быть обработан из-за нехватки памяти: {reason}")
                return False

            return True
        except Exception as e:
            logger.error(f"Ошибка при проверке размера файла {file_path}: {e}")
            return False

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        if not self._service.groq_client:
            raise CloudTranscriptionError("Groq клиент не инициализирован", file_path)

        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)

        try:
            logger.info(f"Начало облачной транскрипции файла: {file_path}")

            processed_file, compression_info = await self._service._preprocess_audio(
                file_path=file_path,
                suffix="preprocessed.mp3",
                ffmpeg_args=_CLOUD_FFMPEG_ARGS,
                target_description="Groq API",
            )

            if not self._check_file_size(processed_file):
                raise CloudTranscriptionError(
                    f"Предобработанный файл слишком большой для облачной транскрипции. "
                    f"Максимальный размер: {self.MAX_FILE_SIZE / (1024 * 1024)}MB",
                    processed_file,
                )

            def _groq_call_sync(path: str):
                with open(path, "rb") as f:
                    data = f.read()
                return self._service.groq_client.audio.transcriptions.create(
                    file=(os.path.basename(path), data),
                    model=settings.groq_model,
                    response_format="verbose_json",
                )

            transcription = await asyncio.to_thread(_groq_call_sync, processed_file)

            result_text = transcription.text
            logger.info(f"Облачная транскрипция завершена. Длина текста: {len(result_text)} символов")

            return _text_result(result_text, compression_info)

        except CloudTranscriptionError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при облачной транскрипции файла {file_path}: {e}")
            if "api" in str(e).lower() or "unauthorized" in str(e).lower():
                raise GroqAPIError(str(e), file_path, str(e))
            elif "rate" in str(e).lower() or "limit" in str(e).lower():
                raise GroqAPIError(f"Превышен лимит запросов: {e}", file_path, str(e))
            elif "file" in str(e).lower() or "format" in str(e).lower():
                raise CloudTranscriptionError(f"Ошибка формата файла: {e}", file_path)
            elif "413" in str(e) or "too large" in str(e).lower():
                raise CloudTranscriptionError(f"Файл слишком большой для облачной транскрипции: {e}", file_path)
            else:
                raise CloudTranscriptionError(str(e), file_path)


class LeopardBackend:
    """Локальная транскрипция через Picovoice Leopard."""

    name = "leopard"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        from src.services.transcription_service import _check_leopard_available
        return bool(_check_leopard_available() and settings.picovoice_access_key)

    def _prepare_file(self, file_path: str) -> str:
        """Подготовить аудио для Leopard: 16kHz mono WAV PCM s16le."""
        try:
            if not self._service._check_ffmpeg():
                logger.info("ffmpeg не найден — передаем исходный файл в Leopard")
                return file_path

            temp_wav = self._service.temp_dir / f"{Path(file_path).stem}_leopard.wav"
            if os.path.exists(temp_wav):
                return str(temp_wav)

            import subprocess
            cmd = [
                "ffmpeg", "-i", file_path,
                "-acodec", "pcm_s16le",
                "-ac", "1",
                "-ar", "16000",
                "-y",
                str(temp_wav)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Файл подготовлен для Leopard: {temp_wav}")
                return str(temp_wav)
            logger.warning(f"Не удалось подготовить файл для Leopard: {result.stderr}")
            return file_path
        except Exception as e:
            logger.warning(f"Ошибка подготовки файла для Leopard: {e}")
            return file_path

    @staticmethod
    def _run_leopard_sync(path: str) -> str:
        leopard = None
        try:
            create_kwargs = {"access_key": settings.picovoice_access_key}
            if getattr(settings, "leopard_model_path", None):
                create_kwargs["model_path"] = settings.leopard_model_path

            import pvleopard
            leopard = pvleopard.create(**create_kwargs)
            transcript, _words = leopard.process_file(path)
            return transcript.strip()
        finally:
            if leopard is not None:
                try:
                    leopard.delete()
                except Exception:
                    pass

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        if not self.is_available():
            raise TranscriptionError("Leopard недоступен (pvleopard/PICOVOICE_ACCESS_KEY)", file_path)

        prepared_file = self._prepare_file(file_path)

        try:
            logger.info(f"Начало транскрипции через Leopard: {prepared_file}")
            transcript = await asyncio.to_thread(self._run_leopard_sync, prepared_file)
            logger.info(f"Leopard транскрипция завершена. Длина: {len(transcript)} символов")
        except Exception as e:
            logger.error(f"Ошибка Leopard транскрипции {file_path}: {e}")
            raise TranscriptionError(str(e), file_path)

        return _text_result(transcript, dict(_EMPTY_COMPRESSION))


class SpeechmaticsBackend:
    """Speechmatics API — транскрипция с родной диаризацией."""

    name = "speechmatics"

    def __init__(self, service):
        self._service = service

    def is_available(self) -> bool:
        return SPEECHMATICS_AVAILABLE and speechmatics_service.is_available()

    async def transcribe(self, file_path: str, language: str) -> TranscriptionResult:
        processed_file, compression_info = await self._service._preprocess_audio(
            file_path=file_path,
            suffix="speechmatics.mp3",
            ffmpeg_args=_CLOUD_FFMPEG_ARGS,
            target_description="Speechmatics API",
        )
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
        processed_file, compression_info = await self._service._preprocess_audio(
            file_path=file_path,
            suffix="deepgram.mp3",
            ffmpeg_args=_CLOUD_FFMPEG_ARGS,
            target_description="Deepgram API",
        )
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
