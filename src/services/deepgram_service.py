"""
Сервис для работы с Deepgram API (SDK v5.x)
"""

from __future__ import annotations

import os
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger
from config import settings

from src.models.processing import TranscriptionResult
from src.exceptions.processing import TranscriptionError, CloudTranscriptionError, DeepgramAPIError

try:
    from deepgram import DeepgramClient
    DEEPGRAM_AVAILABLE = True
except ImportError:
    DEEPGRAM_AVAILABLE = False
    DeepgramClient = None
    logger.warning("Deepgram SDK недоступен")


class DeepgramService:
    """Сервис для работы с Deepgram API"""
    
    def __init__(self):
        self.client = None
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
        
        # Инициализация клиента (SDK v5.x)
        if DEEPGRAM_AVAILABLE and settings.deepgram_api_key:
            try:
                # В SDK v5.x используется keyword argument
                self.client = DeepgramClient(api_key=settings.deepgram_api_key)
                logger.info("Deepgram клиент инициализирован (SDK v5.x)")
            except Exception as e:
                logger.warning(f"Ошибка при инициализации Deepgram клиента: {e}")
        else:
            logger.warning("Deepgram API ключ не настроен или SDK недоступен")
    
    def _check_file_size(self, file_path: str) -> bool:
        """Проверить размер файла для Deepgram API"""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Используем лимиты из настроек
            max_size_mb = settings.max_file_size / (1024 * 1024)
            
            # Если установлен oom_max_file_size_mb, используем его
            if settings.oom_max_file_size_mb:
                max_size_mb = settings.oom_max_file_size_mb
            
            if file_size_mb > max_size_mb:
                logger.warning(f"Файл слишком большой для Deepgram API: {file_size_mb:.1f}MB (максимум: {max_size_mb}MB)")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при проверке размера файла {file_path}: {e}")
            return False
    
    def _prepare_transcription_options(self, language: str = None, enable_diarization: bool = False) -> Dict[str, Any]:
        """Подготовить опции для транскрипции (SDK v5.x)"""
        options = {
            "model": settings.deepgram_model,
            "language": language or settings.deepgram_language,
            "smart_format": True,
            "punctuate": True,
            "utterances": True,
        }
        
        # Добавляем диаризацию если включена
        if enable_diarization:
            options["diarize"] = True
        
        return options
    
    async def transcribe_file(self, file_path: str, language: str = None, 
                            enable_diarization: bool = False) -> TranscriptionResult:
        """Транскрибировать файл через Deepgram API"""
        
        if not self.client:
            raise CloudTranscriptionError("Deepgram клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        if not self._check_file_size(file_path):
            raise CloudTranscriptionError("Файл слишком большой для Deepgram API", file_path)
        
        try:
            logger.info(f"Начало транскрипции через Deepgram: {file_path}")
            
            # Подготавливаем опции
            options = self._prepare_transcription_options(language, enable_diarization)
            
            # Выполняем транскрипцию в отдельном потоке (SDK v5.x)
            def _deepgram_transcribe_sync():
                with open(file_path, "rb") as audio_file:
                    buffer_data = audio_file.read()
                
                # SDK v5.x API: используем client.listen.v1().transcribe_file
                # Передаем данные как {"buffer": buffer_data}
                response = self.client.listen.v1().transcribe_file(
                    {"buffer": buffer_data},
                    options
                )
                
                return response
            
            try:
                response = await asyncio.to_thread(_deepgram_transcribe_sync)
                result = self._process_transcript_result(response, enable_diarization)
                logger.info(f"Транскрипция через Deepgram завершена. Длина текста: {len(result.transcription)} символов")
                return result
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise DeepgramAPIError("Неверный API ключ Deepgram", file_path, str(e))
                elif e.response.status_code == 400:
                    error_detail = str(e)
                    try:
                        error_json = e.response.json()
                        error_detail = error_json.get("err_msg", str(e))
                    except:
                        pass
                    raise DeepgramAPIError(f"Ошибка запроса Deepgram: {error_detail}", file_path, str(e))
                elif e.response.status_code == 413:
                    raise DeepgramAPIError("Файл слишком большой для Deepgram API", file_path, str(e))
                elif e.response.status_code == 429:
                    raise DeepgramAPIError("Превышен лимит запросов Deepgram API", file_path, str(e))
                else:
                    raise DeepgramAPIError(f"Ошибка Deepgram API: {e}", file_path, str(e))
            except Exception as e:
                # Проверяем, является ли это SSL ошибкой
                if "SSL" in str(e) or "certificate" in str(e).lower():
                    logger.warning("Обнаружена SSL ошибка. Попробуйте установить SSL_VERIFY=false в настройках")
                    raise DeepgramAPIError(
                        f"SSL ошибка при подключении к Deepgram API. "
                        f"Установите SSL_VERIFY=false в настройках для отключения проверки сертификатов: {e}",
                        file_path, str(e)
                    )
                raise
                        
        except DeepgramAPIError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при транскрипции через Deepgram {file_path}: {e}")
            raise CloudTranscriptionError(str(e), file_path)
    
    def _process_transcript_result(self, response: Any, enable_diarization: bool = False) -> TranscriptionResult:
        """Обработать результат транскрипции от Deepgram"""
        
        # Извлекаем основной текст
        transcription_text = ""
        speakers_text = {}
        formatted_transcript = ""
        speakers_summary = ""
        
        try:
            # Получаем результаты
            results = response.results
            
            # Извлекаем транскрипцию из первого канала
            if results.channels and len(results.channels) > 0:
                channel = results.channels[0]
                if channel.alternatives and len(channel.alternatives) > 0:
                    transcription_text = channel.alternatives[0].transcript
            
            # Если включена диаризация, обрабатываем utterances (высказывания)
            if enable_diarization and results.utterances:
                for utterance in results.utterances:
                    speaker_id = f"Speaker {utterance.speaker}"
                    utterance_text = utterance.transcript
                    
                    if speaker_id not in speakers_text:
                        speakers_text[speaker_id] = ""
                    
                    # Добавляем текст говорящего
                    if speakers_text[speaker_id]:
                        speakers_text[speaker_id] += " " + utterance_text
                    else:
                        speakers_text[speaker_id] = utterance_text
                
                # Создаем форматированную транскрипцию
                formatted_lines = []
                for speaker, text in speakers_text.items():
                    formatted_lines.append(f"{speaker}: {text}")
                formatted_transcript = "\n\n".join(formatted_lines)
                
                # Создаем сводку о говорящих
                speakers_list = list(speakers_text.keys())
                speakers_summary = f"Общее количество говорящих: {len(speakers_list)}\n\n"
                for speaker in speakers_list:
                    word_count = len(speakers_text[speaker].split())
                    speakers_summary += f"{speaker}: {word_count} слов\n"
            else:
                formatted_transcript = transcription_text
        
        except Exception as e:
            logger.error(f"Ошибка при обработке результата Deepgram: {e}")
            # Если не удалось обработать результат, возвращаем пустую транскрипцию
            if not transcription_text:
                transcription_text = ""
            formatted_transcript = transcription_text
        
        # Создаем объект результата
        result = TranscriptionResult(
            transcription=transcription_text,
            diarization=None,  # Deepgram не возвращает отдельные данные диаризации в том же формате
            speakers_text=speakers_text,
            formatted_transcript=formatted_transcript,
            speakers_summary=speakers_summary,
            compression_info=None  # Информация о сжатии будет добавлена в transcription_service
        )
        
        return result
    
    async def transcribe_with_diarization(self, file_path: str, language: str = None) -> TranscriptionResult:
        """Транскрибировать файл с диаризацией через Deepgram"""
        return await self.transcribe_file(
            file_path=file_path,
            language=language,
            enable_diarization=True
        )
    
    def is_available(self) -> bool:
        """Проверить, доступен ли сервис Deepgram"""
        return DEEPGRAM_AVAILABLE and self.client is not None


# Глобальный экземпляр сервиса
deepgram_service = DeepgramService()

