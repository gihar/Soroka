"""
Сервис для работы с Speechmatics API
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from src.config import settings
from src.exceptions.processing import CloudTranscriptionError, SpeechmaticsAPIError
from src.models.diarization import Diarization, Segment
from src.models.processing import TranscriptionResult

try:
    import ssl

    import urllib3
    from httpx import HTTPStatusError
    from speechmatics.batch_client import BatchClient
    from speechmatics.models import ConnectionSettings
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
        # Гарантируем существование атрибута settings даже без API ключа,
        # чтобы is_available() не обращался к неинициализированному полю
        self.settings = None
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
        
        # Инициализация клиента
        if SPEECHMATICS_AVAILABLE and settings.speechmatics_api_key:
            try:
                # Создаем настройки подключения с учетом SSL настроек
                # Базовый URL без /v2, так как SDK сам добавляет нужные пути (/v2/jobs и т.д.)
                connection_kwargs = {
                    "url": "https://asr.api.speechmatics.com",
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
                            enable_diarization: bool = False) -> TranscriptionResult:
        """Транскрибировать файл через Speechmatics API"""
        
        if not self.settings:
            raise CloudTranscriptionError("Speechmatics клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        if not self._check_file_size(file_path):
            raise CloudTranscriptionError("Файл слишком большой для Speechmatics API", file_path)
        
        try:
            logger.info(f"Начало транскрипции через Speechmatics: {file_path}")
            
            # Подготавливаем конфигурацию
            config = self._prepare_transcription_config(language, enable_diarization)
            
            # Выполняем синхронные вызовы Speechmatics в отдельном потоке, чтобы не блокировать event loop
            def _speechmatics_run_sync():
                with BatchClient(self.settings) as client:
                    # Отправляем задачу
                    job_id = client.submit_job(
                        audio=file_path,
                        transcription_config=config,
                    )
                    logger.info(f"Задача отправлена в Speechmatics, ID: {job_id}")
                    # Ждем завершения с форматом json-v2 для получения полной информации
                    transcript = client.wait_for_completion(
                        job_id, 
                        transcription_format="json-v2"
                    )
                    return transcript

            try:
                transcript = await asyncio.to_thread(_speechmatics_run_sync)
                result = self._process_transcript_result(transcript, enable_diarization)
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
            logger.error(f"Тип ошибки: {type(e).__name__}, repr: {repr(e)}")
            if not str(e):
                logger.warning(f"Получено исключение с пустым сообщением: {type(e)}")
            
            # Проверяем, является ли это SSL ошибкой
            if "SSL" in str(e) or "certificate" in str(e).lower():
                logger.warning("Обнаружена SSL ошибка. Попробуйте установить SSL_VERIFY=false в настройках")
                raise SpeechmaticsAPIError(
                    f"SSL ошибка при подключении к Speechmatics API. "
                    f"Установите SSL_VERIFY=false в настройках для отключения проверки сертификатов: {e}",
                    file_path, str(e)
                )
            
            raise CloudTranscriptionError(str(e), file_path, "speechmatics")
    
    def _build_diarization(self, words_with_speakers: list) -> Diarization:
        """Построить «Диаризацию» из пословных данных speechmatics.

        Смена спикера рвёт сегмент; тайминги — нативные speechmatics. Метки
        спикеров РОДНЫЕ (S1, S2) и НЕ нормализуются в SPEAKER_N: они уже
        стабильны и доходят до протоколов как есть. Всё производное (тексты,
        форматирование, сводка) выводит модель.

        ВАЖНО: последовательность реплик сохраняется — сегмент образуют только
        подряд идущие слова одного спикера, чтобы LLM понимал чередование
        участников.
        """
        segments: list[Segment] = []
        current_speaker = None
        current_words: list[str] = []
        current_start = None

        for item in words_with_speakers:
            if item["speaker"] != current_speaker:
                if current_speaker is not None and current_words:
                    segments.append(Segment(
                        speaker=current_speaker,
                        text=" ".join(current_words),
                        start=current_start,
                        end=item["start_time"],
                    ))
                current_speaker = item["speaker"]
                current_words = [item["word"]]
                current_start = item["start_time"]
            else:
                current_words.append(item["word"])

        if current_speaker is not None and current_words:
            segments.append(Segment(
                speaker=current_speaker,
                text=" ".join(current_words),
                start=current_start,
                end=words_with_speakers[-1]["end_time"] if words_with_speakers else 0,
            ))

        return Diarization(segments=segments)

    def _process_transcript_result(self, transcript: Dict[str, Any], enable_diarization: bool = False) -> TranscriptionResult:
        """Обработать результат транскрипции от Speechmatics.

        При включённой диаризации строит «Диаризацию» из своих нативных
        сегментов и кладёт сам объект в поле результата (как deepgram);
        производные читаются из его свойств. Без диаризации — только сырой текст.
        """

        transcription_text = ""
        words_with_speakers = []

        if "results" in transcript:
            for result in transcript["results"]:
                if result.get("type") == "word" and "alternatives" in result:
                    word = result["alternatives"][0]["content"]
                    transcription_text += word + " "

                    if enable_diarization and "speaker" in result["alternatives"][0]:
                        words_with_speakers.append({
                            "word": word,
                            "speaker": result["alternatives"][0]["speaker"],
                            "start_time": result.get("start_time", 0),
                            "end_time": result.get("end_time", 0),
                        })

            transcription_text = transcription_text.strip()

        if enable_diarization and words_with_speakers:
            diarization = self._build_diarization(words_with_speakers)
            return TranscriptionResult(
                transcription=transcription_text,
                diarization=diarization,
                compression_info=None,  # Speechmatics обрабатывает файлы как есть
            )

        # Без диаризации: диаризации нет, форматированный текст выводится из сырого
        return TranscriptionResult(
            transcription=transcription_text,
            diarization=None,
            compression_info=None,  # Speechmatics обрабатывает файлы как есть
        )
    
    async def transcribe_with_diarization(self, file_path: str, language: str = None) -> TranscriptionResult:
        """Транскрибировать файл с диаризацией через Speechmatics"""
        return await self.transcribe_file(
            file_path=file_path,
            language=language,
            enable_diarization=True
        )
    
    def is_available(self) -> bool:
        """Проверить, доступен ли сервис Speechmatics"""
        return SPEECHMATICS_AVAILABLE and self.settings is not None


# Глобальный экземпляр сервиса
speechmatics_service = SpeechmaticsService()
