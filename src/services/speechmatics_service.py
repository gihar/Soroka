"""
Сервис для работы с Speechmatics API
"""

import os
import tempfile
from typing import Optional, Dict, Any, List
import asyncio
from pathlib import Path
from loguru import logger
from config import settings

from src.models.processing import TranscriptionResult, DiarizationData
from src.exceptions.processing import TranscriptionError, CloudTranscriptionError, SpeechmaticsAPIError

try:
    from speechmatics.models import ConnectionSettings
    from speechmatics.batch_client import BatchClient
    from httpx import HTTPStatusError, Client
    import ssl
    import urllib3
    SPEECHMATICS_AVAILABLE = True
except ImportError:
    SPEECHMATICS_AVAILABLE = False
    logger.warning("Speechmatics SDK недоступен")

# Отключаем предупреждения SSL если SSL_VERIFY=false
if not settings.ssl_verify:
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # Создаем глобальный SSL контекст без верификации
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        # Устанавливаем как контекст по умолчанию
        ssl._create_default_https_context = lambda: ssl_context
        logger.info("Глобальный SSL контекст настроен без верификации")
    except Exception as e:
        logger.warning(f"Не удалось настроить глобальный SSL контекст: {e}")


class SpeechmaticsService:
    """Сервис для работы с Speechmatics API"""
    
    def __init__(self):
        self.client = None
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
        
        # Инициализация клиента
        if SPEECHMATICS_AVAILABLE and settings.speechmatics_api_key:
            try:
                # Создаем настройки подключения с учетом SSL настроек
                connection_kwargs = {
                    "url": "https://asr.api.speechmatics.com/v2",
                    "auth_token": settings.speechmatics_api_key,
                }
                
                # Настраиваем SSL верификацию через переменные окружения
                if not settings.ssl_verify:
                    import os
                    # Отключаем SSL верификацию для httpx (который использует Speechmatics SDK)
                    os.environ["PYTHONHTTPSVERIFY"] = "0"
                    os.environ["CURL_CA_BUNDLE"] = ""
                    # Дополнительные настройки для отключения SSL верификации
                    os.environ["REQUESTS_CA_BUNDLE"] = ""
                    os.environ["SSL_VERIFY"] = "false"
                    
                    # Monkey patch для httpx чтобы отключить SSL верификацию
                    try:
                        import httpx
                        # Сохраняем оригинальный метод
                        if not hasattr(httpx.Client, '_original_init'):
                            httpx.Client._original_init = httpx.Client.__init__
                            
                            def patched_init(self, *args, **kwargs):
                                kwargs['verify'] = False
                                return httpx.Client._original_init(self, *args, **kwargs)
                            
                            httpx.Client.__init__ = patched_init
                            logger.info("SSL верификация отключена через monkey patch для httpx")
                    except Exception as e:
                        logger.warning(f"Не удалось отключить SSL верификацию через monkey patch: {e}")
                    
                    logger.info("Speechmatics клиент инициализирован с отключенной SSL верификацией")
                else:
                    logger.info("Speechmatics клиент инициализирован с включенной SSL верификацией")
                
                # Создаем настройки подключения
                self.settings = ConnectionSettings(**connection_kwargs)
                
            except Exception as e:
                logger.warning(f"Ошибка при инициализации Speechmatics клиента: {e}")
        else:
            logger.warning("Speechmatics API ключ не настроен или SDK недоступен")
    
    def _check_file_size(self, file_path: str) -> bool:
        """Проверить размер файла для Speechmatics API"""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Speechmatics поддерживает файлы до 2GB
            max_size_mb = 2048  # 2GB
            
            if file_size_mb > max_size_mb:
                logger.warning(f"Файл слишком большой для Speechmatics API: {file_size_mb:.1f}MB (максимум: {max_size_mb}MB)")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при проверке размера файла {file_path}: {e}")
            return False
    
    def _prepare_transcription_config(self, language: str = None, enable_diarization: bool = False) -> Dict[str, Any]:
        """Подготовить конфигурацию для транскрипции"""
        config = {
            "type": "transcription",
            "transcription_config": {
                "language": language or settings.speechmatics_language,
                "operating_point": settings.speechmatics_operating_point
            }
        }
        
        # Добавляем домен если указан
        if settings.speechmatics_domain:
            config["transcription_config"]["domain"] = settings.speechmatics_domain
        
        # Добавляем диаризацию если включена
        if enable_diarization:
            config["transcription_config"]["diarization"] = "speaker"
        
        return config
    
    async def transcribe_file(self, file_path: str, language: str = None, 
                            enable_diarization: bool = False, 
                            progress_callback=None) -> TranscriptionResult:
        """Транскрибировать файл через Speechmatics API"""
        
        if not self.settings:
            raise CloudTranscriptionError("Speechmatics клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        if not self._check_file_size(file_path):
            raise CloudTranscriptionError("Файл слишком большой для Speechmatics API", file_path)
        
        try:
            if progress_callback:
                progress_callback(10)
            
            logger.info(f"Начало транскрипции через Speechmatics: {file_path}")
            
            # Подготавливаем конфигурацию
            config = self._prepare_transcription_config(language, enable_diarization)
            
            if progress_callback:
                progress_callback(20)
            
            # Выполняем синхронные вызовы Speechmatics в отдельном потоке, чтобы не блокировать event loop
            def _speechmatics_run_sync():
                with BatchClient(self.settings) as client:
                    # Отправляем задачу
                    job_id = client.submit_job(
                        audio=file_path,
                        transcription_config=config,
                    )
                    if progress_callback:
                        progress_callback(40)
                    logger.info(f"Задача отправлена в Speechmatics, ID: {job_id}")
                    # Ждем завершения с форматом json-v2 для получения полной информации
                    transcript = client.wait_for_completion(
                        job_id, 
                        transcription_format="json-v2"
                    )
                    return transcript

            try:
                transcript = await asyncio.to_thread(_speechmatics_run_sync)
                if progress_callback:
                    progress_callback(90)
                result = self._process_transcript_result(transcript, enable_diarization)
                if progress_callback:
                    progress_callback(100)
                logger.info(f"Транскрипция через Speechmatics завершена. Длина текста: {len(result.transcription)} символов")
                return result
            except HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise SpeechmaticsAPIError("Неверный API ключ Speechmatics", file_path, str(e))
                elif e.response.status_code == 400:
                    error_detail = e.response.json().get("detail", str(e))
                    raise SpeechmaticsAPIError(f"Ошибка запроса Speechmatics: {error_detail}", file_path, str(e))
                elif e.response.status_code == 413:
                    raise SpeechmaticsAPIError("Файл слишком большой для Speechmatics API", file_path, str(e))
                elif e.response.status_code == 429:
                    raise SpeechmaticsAPIError("Превышен лимит запросов Speechmatics API", file_path, str(e))
                else:
                    raise SpeechmaticsAPIError(f"Ошибка Speechmatics API: {e}", file_path, str(e))
                        
        except Exception as e:
            logger.error(f"Ошибка при транскрипции через Speechmatics {file_path}: {e}")
            
            # Проверяем, является ли это SSL ошибкой
            if "SSL" in str(e) or "certificate" in str(e).lower():
                logger.warning("Обнаружена SSL ошибка. Попробуйте установить SSL_VERIFY=false в настройках")
                raise SpeechmaticsAPIError(
                    f"SSL ошибка при подключении к Speechmatics API. "
                    f"Установите SSL_VERIFY=false в настройках для отключения проверки сертификатов: {e}",
                    file_path, str(e)
                )
            
            raise CloudTranscriptionError(str(e), file_path)
    
    def _process_transcript_result(self, transcript: Dict[str, Any], enable_diarization: bool = False) -> TranscriptionResult:
        """Обработать результат транскрипции от Speechmatics"""
        
        # Извлекаем основной текст
        transcription_text = ""
        segments = []
        speakers_text = {}
        formatted_transcript = ""
        speakers_summary = ""
        
        if "results" in transcript:
            # Обрабатываем результаты в формате json-v2
            for result in transcript["results"]:
                if result.get("type") == "word" and "alternatives" in result:
                    word = result["alternatives"][0]["content"]
                    transcription_text += word + " "
                    
                    # Если включена диаризация, собираем информацию о говорящих
                    if enable_diarization and "speaker" in result["alternatives"][0]:
                        speaker = result["alternatives"][0]["speaker"]
                        if speaker not in speakers_text:
                            speakers_text[speaker] = []
                        speakers_text[speaker].append(word)
        
        # Очищаем текст
        transcription_text = transcription_text.strip()
        
        # Если диаризация включена, создаем форматированную транскрипцию
        if enable_diarization and speakers_text:
            formatted_lines = []
            # Преобразуем списки слов в строки
            speakers_text_str = {}
            for speaker, words in speakers_text.items():
                if isinstance(words, list):
                    speaker_text = " ".join(words)
                    speakers_text_str[speaker] = speaker_text
                else:
                    speakers_text_str[speaker] = words
                formatted_lines.append(f"{speaker}: {speakers_text_str[speaker]}")
            formatted_transcript = "\n\n".join(formatted_lines)
            speakers_text = speakers_text_str  # Обновляем на строковый формат
            
            # Создаем сводку о говорящих
            speakers_list = list(speakers_text.keys())
            speakers_summary = f"Общее количество говорящих: {len(speakers_list)}\n\n"
            for speaker in speakers_list:
                word_count = len(speakers_text[speaker].split())
                speakers_summary += f"{speaker}: {word_count} слов\n"
        else:
            formatted_transcript = transcription_text
        
        # Создаем объект результата
        result = TranscriptionResult(
            transcription=transcription_text,
            diarization=None,  # Speechmatics не возвращает отдельные данные диаризации
            speakers_text=speakers_text,
            formatted_transcript=formatted_transcript,
            speakers_summary=speakers_summary,
            compression_info=None  # Speechmatics обрабатывает файлы как есть
        )
        
        return result
    
    async def transcribe_with_diarization(self, file_path: str, language: str = None, 
                                        progress_callback=None) -> TranscriptionResult:
        """Транскрибировать файл с диаризацией через Speechmatics"""
        return await self.transcribe_file(
            file_path=file_path,
            language=language,
            enable_diarization=True,
            progress_callback=progress_callback
        )
    
    def is_available(self) -> bool:
        """Проверить, доступен ли сервис Speechmatics"""
        return SPEECHMATICS_AVAILABLE and self.settings is not None


# Глобальный экземпляр сервиса
speechmatics_service = SpeechmaticsService()
