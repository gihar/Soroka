"""
Сервис для работы с Deepgram API (прямой HTTP API для избежания Pydantic validation errors)
"""

from __future__ import annotations

import os
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger
import httpx
from config import settings

from src.models.processing import TranscriptionResult
from src.exceptions.processing import TranscriptionError, CloudTranscriptionError, DeepgramAPIError

# Используем прямой HTTP API вместо SDK для избежания проблем с Pydantic валидацией
DEEPGRAM_AVAILABLE = True


class DeepgramService:
    """Сервис для работы с Deepgram API через прямой HTTP API"""
    
    DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
    
    def __init__(self):
        self.api_key = settings.deepgram_api_key
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
        
        # Инициализация HTTP клиента
        if self.api_key:
            # Создаем httpx клиент с настройками SSL
            verify_ssl = getattr(settings, 'ssl_verify', True)
            self.http_client = httpx.AsyncClient(
                timeout=300.0,  # 5 минут таймаут для больших файлов
                verify=verify_ssl,
                headers={
                    "Authorization": f"Token {self.api_key}",
                }
            )
            logger.info("Deepgram HTTP клиент инициализирован (прямой API)")
        else:
            self.http_client = None
            logger.warning("Deepgram API ключ не настроен")
    
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
    
    async def transcribe_file(self, file_path: str, language: str = None, 
                            enable_diarization: bool = False) -> TranscriptionResult:
        """Транскрибировать файл через Deepgram API"""
        
        if not self.http_client:
            raise CloudTranscriptionError("Deepgram HTTP клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        if not self._check_file_size(file_path):
            raise CloudTranscriptionError("Файл слишком большой для Deepgram API", file_path)
        
        try:
            logger.info(f"Начало транскрипции через Deepgram: {file_path}")
            
            # Подготавливаем параметры запроса
            params = {
                "model": settings.deepgram_model,
                "language": language or settings.deepgram_language,
                "smart_format": "true",
                "punctuate": "true",
                "utterances": "true",
            }
            
            if enable_diarization:
                params["diarize"] = "true"
            
            # Читаем файл
            with open(file_path, "rb") as audio_file:
                audio_data = audio_file.read()
            
            # Определяем mime type
            mime_type = "audio/mpeg"
            if file_path.endswith(".wav"):
                mime_type = "audio/wav"
            elif file_path.endswith(".m4a"):
                mime_type = "audio/mp4"
            elif file_path.endswith(".ogg"):
                mime_type = "audio/ogg"
            
            # Отправляем запрос
            try:
                response = await self.http_client.post(
                    self.DEEPGRAM_API_URL,
                    params=params,
                    content=audio_data,
                    headers={"Content-Type": mime_type}
                )
                response.raise_for_status()
                
                # Получаем JSON ответ
                response_data = response.json()
                
                # Обрабатываем результат
                result = self._process_transcript_result(response_data, enable_diarization)
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
            logger.error(f"Тип ошибки: {type(e).__name__}, repr: {repr(e)}")
            if not str(e):
                logger.warning(f"Получено исключение с пустым сообщением: {type(e)}")
            raise CloudTranscriptionError(str(e), file_path, "deepgram")
    
    def _process_transcript_result(self, response_data: Dict[str, Any], enable_diarization: bool = False) -> TranscriptionResult:
        """Обработать результат транскрипции от Deepgram (работа с сырым JSON)"""
        
        # Извлекаем основной текст
        transcription_text = ""
        speakers_text = {}
        formatted_transcript = ""
        speakers_summary = ""
        diarization_data: Optional[Dict[str, Any]] = None
        
        try:
            # Получаем результаты
            results = response_data.get("results", {})
            
            # Извлекаем транскрипцию из первого канала
            channels = results.get("channels", [])
            if channels and len(channels) > 0:
                channel = channels[0]
                alternatives = channel.get("alternatives", [])
                if alternatives and len(alternatives) > 0:
                    transcription_text = alternatives[0].get("transcript", "")
            
            # Если включена диаризация, обрабатываем utterances (высказывания)
            utterances = results.get("utterances", [])
            if enable_diarization and utterances:
                speaker_labels: Dict[Any, str] = {}
                segments = []
                
                for utterance in utterances:
                    raw_speaker = utterance.get("speaker")
                    # Присваиваем стабильный label вида SPEAKER_N, порядок соответствует появлению
                    if raw_speaker not in speaker_labels:
                        speaker_labels[raw_speaker] = f"SPEAKER_{len(speaker_labels) + 1}"
                    speaker_id = speaker_labels[raw_speaker]
                    
                    utterance_text = (utterance.get("transcript") or "").strip()
                    start_time = utterance.get("start")
                    end_time = utterance.get("end")
                    
                    if speaker_id not in speakers_text:
                        speakers_text[speaker_id] = utterance_text
                    elif utterance_text:
                        speakers_text[speaker_id] = f"{speakers_text[speaker_id]} {utterance_text}".strip()
                    
                    segments.append({
                        "speaker": speaker_id,
                        "start": start_time,
                        "end": end_time,
                        "text": utterance_text,
                    })
                
                speakers_list = list(speaker_labels.values())
                
                # Создаем форматированную транскрипцию
                formatted_lines = []
                for speaker in speakers_list:
                    speaker_text = speakers_text.get(speaker, "").strip()
                    if speaker_text:
                        formatted_lines.append(f"{speaker}: {speaker_text}")
                formatted_transcript = "\n\n".join(formatted_lines)
                
                # Создаем сводку о говорящих
                speakers_summary = f"Общее количество говорящих: {len(speakers_list)}\n\n"
                for speaker in speakers_list:
                    word_count = len(speakers_text.get(speaker, "").split())
                    speakers_summary += f"{speaker}: {word_count} слов\n"
                
                diarization_data = {
                    "segments": segments,
                    "speakers": speakers_list,
                    "total_speakers": len(speakers_list),
                    "formatted_transcript": formatted_transcript,
                    "speakers_text": speakers_text,
                }
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
            diarization=diarization_data,
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
        return DEEPGRAM_AVAILABLE and self.http_client is not None
    
    async def cleanup(self):
        """Очистка ресурсов"""
        if self.http_client:
            await self.http_client.aclose()


# Глобальный экземпляр сервиса
deepgram_service = DeepgramService()
