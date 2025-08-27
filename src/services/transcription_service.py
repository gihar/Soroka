"""
Обновленный сервис транскрипции
"""

import os
import tempfile
import whisper
import httpx
import shutil
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger

from models.processing import TranscriptionResult, DiarizationData
from exceptions.processing import TranscriptionError
from config import settings

try:
    from diarization import diarization_service, DiarizationResult
    DIARIZATION_AVAILABLE = True
except ImportError:
    DIARIZATION_AVAILABLE = False
    logger.warning("Модуль диаризации недоступен")


class TranscriptionService:
    """Обновленный сервис транскрипции"""
    
    def __init__(self):
        self.whisper_model = None
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
    
    def _load_whisper_model(self, model_size: str = "base"):
        """Загрузить модель Whisper"""
        if self.whisper_model is None:
            logger.info(f"Загрузка модели Whisper: {model_size}")
            try:
                self.whisper_model = whisper.load_model(model_size)
                logger.info("Модель Whisper загружена")
            except Exception as e:
                logger.error(f"Ошибка при загрузке модели Whisper: {e}")
                raise TranscriptionError(f"Не удалось загрузить модель Whisper: {e}")
    
    async def download_file(self, file_url: str, file_name: str) -> str:
        """Скачать файл по URL"""
        try:
            file_path = self.temp_dir / file_name
            
            async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
                response = await client.get(file_url, timeout=300.0)
                response.raise_for_status()
                
                with open(file_path, 'wb') as f:
                    f.write(response.content)
            
            logger.info(f"Файл скачан: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла {file_url}: {e}")
            raise TranscriptionError(f"Не удалось скачать файл: {e}")
    
    def _check_ffmpeg(self) -> bool:
        """Проверить наличие ffmpeg"""
        return shutil.which("ffmpeg") is not None
    
    def transcribe_with_diarization(self, file_path: str, language: str = "ru") -> TranscriptionResult:
        """Транскрибировать файл с диаризацией"""
        # Проверяем наличие ffmpeg
        if not self._check_ffmpeg():
            raise TranscriptionError(
                "ffmpeg не найден в системе. "
                "Установите ffmpeg для транскрипции аудио/видео файлов.",
                file_path
            )
        
        # Проверяем существование файла
        if not os.path.exists(file_path):
            raise TranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        logger.info(f"Начало транскрибации с диаризацией файла: {file_path}")
        
        result = TranscriptionResult(
            transcription="",
            diarization=None,
            speakers_text={},
            formatted_transcript="",
            speakers_summary=""
        )
        
        try:
            # Пробуем диаризацию с WhisperX (если доступна)
            if DIARIZATION_AVAILABLE and settings.enable_diarization:
                try:
                    logger.info("Выполнение диаризации...")
                    diarization_result = diarization_service.diarize_file(file_path, language)
                    
                    if diarization_result:
                        # Извлекаем текст из результатов диаризации
                        transcription = ""
                        for segment in diarization_result.segments:
                            if segment.get("text"):
                                transcription += segment["text"] + " "
                        
                        result.transcription = transcription.strip()
                        result.diarization = diarization_result.to_dict()
                        result.speakers_text = diarization_result.get_speakers_text()
                        result.formatted_transcript = diarization_result.get_formatted_transcript()
                        result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                        
                        logger.info(f"Диаризация успешна. Найдено говорящих: {len(diarization_result.speakers)}")
                        return result
                        
                except Exception as e:
                    logger.warning(f"Ошибка при диаризации, переходим к обычной транскрипции: {e}")
            
            # Fallback к обычной транскрипции через Whisper
            self._load_whisper_model()
            
            logger.info("Выполнение стандартной транскрипции...")
            whisper_result = self.whisper_model.transcribe(
                file_path, 
                language=language,
                word_timestamps=False
            )
            
            transcription = whisper_result["text"].strip()
            result.transcription = transcription
            result.formatted_transcript = transcription  # Без разделения говорящих
            
            logger.info(f"Стандартная транскрибация завершена. Длина текста: {len(transcription)} символов")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при транскрибации файла {file_path}: {e}")
            if "ffmpeg" in str(e).lower():
                raise TranscriptionError(
                    "ffmpeg не найден. Установите ffmpeg для обработки аудио/видео файлов",
                    file_path
                )
            raise TranscriptionError(str(e), file_path)
    
    def cleanup_file(self, file_path: str):
        """Удалить временный файл"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Временный файл удален: {file_path}")
        except Exception as e:
            logger.warning(f"Не удалось удалить файл {file_path}: {e}")
    
    async def transcribe_telegram_file_with_diarization(self, file_url: str, file_name: str, 
                                                       language: str = "ru") -> TranscriptionResult:
        """Полный цикл с диаризацией: скачать, транскрибировать, удалить"""
        file_path = None
        try:
            # Скачиваем файл
            file_path = await self.download_file(file_url, file_name)
            
            # Транскрибируем с диаризацией
            result = self.transcribe_with_diarization(file_path, language)
            
            return result
            
        finally:
            # Удаляем временный файл
            if file_path:
                self.cleanup_file(file_path)
