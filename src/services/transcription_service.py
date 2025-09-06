"""
Обновленный сервис транскрипции с защитой от OOM
"""

import os
import tempfile
import whisper
import httpx
import shutil
import psutil
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger

from src.models.processing import TranscriptionResult, DiarizationData
from src.exceptions.processing import TranscriptionError, CloudTranscriptionError, GroqAPIError, SpeechmaticsAPIError
from src.performance.oom_protection import oom_protected, get_oom_protection, memory_safe_operation
from config import settings

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logger.warning("Groq SDK недоступен")

try:
    from diarization import diarization_service, DiarizationResult
    DIARIZATION_AVAILABLE = True
except ImportError:
    DIARIZATION_AVAILABLE = False
    logger.warning("Модуль диаризации недоступен")

try:
    from .speechmatics_service import speechmatics_service
    SPEECHMATICS_AVAILABLE = True
except ImportError:
    SPEECHMATICS_AVAILABLE = False
    logger.warning("Speechmatics сервис недоступен")


class TranscriptionService:
    """Обновленный сервис транскрипции с защитой от OOM"""
    
    # Максимальный размер файла для Groq API (25 MB)
    GROQ_MAX_FILE_SIZE = 25 * 1024 * 1024
    
    def __init__(self):
        self.whisper_model = None
        self.groq_client = None
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
        
        # OOM защита
        self.oom_protection = get_oom_protection()
        
        # Инициализация Groq клиента
        if GROQ_AVAILABLE and settings.groq_api_key:
            try:
                self.groq_client = Groq(api_key=settings.groq_api_key)
                logger.info("Groq клиент инициализирован")
            except Exception as e:
                logger.warning(f"Ошибка при инициализации Groq клиента: {e}")
        
        # Инициализация Speechmatics сервиса
        if SPEECHMATICS_AVAILABLE and speechmatics_service.is_available():
            logger.info("Speechmatics сервис доступен")
        else:
            logger.warning("Speechmatics сервис недоступен")
        
        # Настраиваем callbacks для очистки памяти
        self.oom_protection.add_cleanup_callback(self._cleanup_models)
    
    @oom_protected(estimated_memory_mb=200)  # Whisper модели занимают ~200MB
    def _load_whisper_model(self, model_size: str = "base"):
        """Загрузить модель Whisper с защитой от OOM"""
        if self.whisper_model is None:
            logger.info(f"Загрузка модели Whisper: {model_size}")
            
            # Проверяем доступную память перед загрузкой
            memory_status = self.oom_protection.get_memory_status()
            if memory_status["system"]["percent"] > 80:
                logger.warning(f"Высокое использование памяти при загрузке модели: {memory_status['system']['percent']:.1f}%")
            
            try:
                self.whisper_model = whisper.load_model(model_size)
                logger.info("Модель Whisper загружена")
            except Exception as e:
                logger.error(f"Ошибка при загрузке модели Whisper: {e}")
                raise TranscriptionError(f"Не удалось загрузить модель Whisper: {e}")
    
    def _cleanup_models(self, cleanup_type: str = "soft"):
        """Очистка моделей для освобождения памяти"""
        if cleanup_type == "aggressive" and self.whisper_model is not None:
            logger.info("Принудительная очистка модели Whisper")
            self.whisper_model = None
            import gc
            gc.collect()
    
    def _check_file_size_for_groq(self, file_path: str) -> bool:
        """Проверить, подходит ли файл для облачной транскрипции по размеру"""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Проверяем лимит Groq API
            is_suitable = file_size <= self.GROQ_MAX_FILE_SIZE
            
            if not is_suitable:
                max_size_mb = self.GROQ_MAX_FILE_SIZE / (1024 * 1024)
                logger.warning(f"Файл слишком большой для облачной транскрипции: {file_size_mb:.1f}MB (максимум: {max_size_mb}MB)")
                return False
            
            # Дополнительная проверка с учетом доступной памяти
            can_process, reason = self.oom_protection.can_process_file(file_size_mb)
            if not can_process:
                logger.warning(f"Файл не может быть обработан из-за нехватки памяти: {reason}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при проверке размера файла {file_path}: {e}")
            return False
    
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
    
    def _preprocess_for_groq(self, file_path: str) -> tuple[str, dict]:
        """Предобработать файл для Groq API: конвертировать в 16KHz моно MP3"""
        compression_info = {
            "compressed": False,
            "original_size_mb": 0,
            "compressed_size_mb": 0,
            "compression_ratio": 0,
            "compression_saved_mb": 0
        }
        
        try:
            if not self._check_ffmpeg():
                logger.warning("ffmpeg не найден, пропускаем предобработку")
                return file_path, compression_info
            
            # Создаем временный файл для предобработки
            temp_mp3 = self.temp_dir / f"{Path(file_path).stem}_preprocessed.mp3"
            
            # Конвертируем в MP3 с параметрами для Groq API
            import subprocess
            cmd = [
                "ffmpeg",
                "-i", file_path,
                "-ar", "16000",  # Частота дискретизации 16KHz
                "-ac", "1",      # Моно
                "-map", "0:a",   # Только аудио поток
                "-c:a", "mp3",   # MP3 кодек
                "-b:a", "64k",   # Низкий битрейт для максимального сжатия
                "-y",            # Перезаписать существующий файл
                str(temp_mp3)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                original_size = os.path.getsize(file_path)
                processed_size = os.path.getsize(temp_mp3)
                original_mb = original_size / (1024 * 1024)
                processed_mb = processed_size / (1024 * 1024)
                
                # Рассчитываем информацию о сжатии
                compression_info = {
                    "compressed": True,
                    "original_size_mb": original_mb,
                    "compressed_size_mb": processed_mb,
                    "compression_ratio": (1 - processed_mb / original_mb) * 100 if original_mb > 0 else 0,
                    "compression_saved_mb": original_mb - processed_mb
                }
                
                logger.info(f"Файл предобработан для Groq API: {processed_mb:.1f}MB (было: {original_mb:.1f}MB, сжатие: {compression_info['compression_ratio']:.1f}%)")
                return str(temp_mp3), compression_info
            else:
                logger.warning(f"Ошибка предобработки файла: {result.stderr}")
                return file_path, compression_info
                
        except Exception as e:
            logger.warning(f"Не удалось предобработать файл: {e}")
            return file_path, compression_info
    
    async def _transcribe_with_groq(self, file_path: str, progress_callback=None) -> tuple[str, dict]:
        """Транскрибация через Groq API"""
        if not self.groq_client:
            raise CloudTranscriptionError("Groq клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        try:
            if progress_callback:
                progress_callback(20, "Подготовка файла для облачной транскрипции...")
            
            logger.info(f"Начало облачной транскрипции файла: {file_path}")
            
            # Предобрабатываем файл для Groq API
            logger.info(f"Начинаем предобработку файла: {file_path}")
            if progress_callback:
                progress_callback(25, "Сжатие файла для ускорения обработки...")
            
            processed_file, compression_info = self._preprocess_for_groq(file_path)
            logger.info(f"Предобработка завершена. Результат: {compression_info}")
            
            # Если есть информация о сжатии, передаем её через callback
            if compression_info and compression_info.get("compressed", False):
                logger.info(f"Передаем информацию о сжатии через callback: {compression_info}")
                if progress_callback:
                    # Вызываем callback с информацией о сжатии
                    try:
                        progress_callback(100, "compression_complete", compression_info)
                        # Помечаем как показанную
                        compression_info["shown_during_processing"] = True
                        logger.info("Callback сжатия успешно вызван")
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить о сжатии: {e}")
            else:
                logger.info("Информация о сжатии не найдена или файл не сжат")
            
            # Проверяем размер предобработанного файла
            if not self._check_file_size_for_groq(processed_file):
                raise CloudTranscriptionError(
                    f"Предобработанный файл слишком большой для облачной транскрипции. Максимальный размер: {self.GROQ_MAX_FILE_SIZE / (1024 * 1024)}MB", 
                    processed_file
                )
            
            # Дополнительная диагностика предобработанного файла
            try:
                file_size = os.path.getsize(processed_file)
                file_size_mb = file_size / (1024 * 1024)
                logger.info(f"Отправка предобработанного файла в Groq API: {processed_file} (размер: {file_size_mb:.1f}MB)")
            except Exception as e:
                logger.warning(f"Не удалось получить размер предобработанного файла: {e}")
            
            # Читаем предобработанный файл и отправляем в Groq
            with open(processed_file, "rb") as file:
                if progress_callback:
                    progress_callback(40, "Отправка файла в облако...")
                
                transcription = self.groq_client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), file.read()),
                    model=settings.groq_model,
                    response_format="verbose_json",
                )
                
                if progress_callback:
                    progress_callback(90, "Получение результатов...")
                
                result_text = transcription.text
                logger.info(f"Облачная транскрипция завершена. Длина текста: {len(result_text)} символов")
                
                return result_text, compression_info
                
        except Exception as e:
            logger.error(f"Ошибка при облачной транскрипции файла {file_path}: {e}")
            
            # Проверяем тип ошибки для более точной диагностики
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
    
    async def _transcribe_with_speechmatics(self, file_path: str, language: str = "ru", 
                                          enable_diarization: bool = False,
                                          progress_callback=None) -> tuple[str, dict]:
        """Транскрипция через Speechmatics API"""
        if not SPEECHMATICS_AVAILABLE or not speechmatics_service.is_available():
            raise CloudTranscriptionError("Speechmatics сервис недоступен", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        try:
            if progress_callback:
                progress_callback(20, "Подготовка к транскрипции через Speechmatics...")
            
            logger.info(f"Начало транскрипции через Speechmatics: {file_path}")
            
            # Выполняем транскрипцию через Speechmatics
            result = await speechmatics_service.transcribe_file(
                file_path=file_path,
                language=language,
                enable_diarization=enable_diarization,
                progress_callback=progress_callback
            )
            
            # Возвращаем текст и информацию о сжатии (Speechmatics не сжимает файлы)
            compression_info = {
                "compressed": False,
                "original_size_mb": 0,
                "compressed_size_mb": 0,
                "compression_ratio": 0,
                "compression_saved_mb": 0
            }
            
            return result.transcription, compression_info
            
        except Exception as e:
            logger.error(f"Ошибка при транскрипции через Speechmatics {file_path}: {e}")
            raise CloudTranscriptionError(str(e), file_path)
    
    async def transcribe_with_diarization(self, file_path: str, language: str = "ru", 
                                   progress_callback=None) -> TranscriptionResult:
        """Транскрибировать файл с диаризацией и защитой от OOM"""
        
        # Проверяем размер файла и доступную память
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # Проверяем, можно ли обработать файл
            can_process, reason = self.oom_protection.can_process_file(file_size_mb)
            if not can_process:
                raise TranscriptionError(f"Файл не может быть обработан: {reason}", file_path)
            
            logger.info(f"Обработка файла {file_path} размером {file_size_mb:.1f}MB")
            
        except Exception as e:
            logger.error(f"Ошибка при проверке файла {file_path}: {e}")
            raise TranscriptionError(f"Не удалось проверить файл: {e}", file_path)
        
        # Для облачной транскрипции ffmpeg не нужен
        if settings.transcription_mode == "local" and not self._check_ffmpeg():
            raise TranscriptionError(
                "ffmpeg не найден в системе. "
                "Установите ffmpeg для транскрипции аудио/видео файлов.",
                file_path
            )
        
        # Проверяем существование файла
        if not os.path.exists(file_path):
            raise TranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        # Логируем информацию о файле
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"Начало транскрибации с диаризацией файла: {file_path} (размер: {file_size_mb:.1f}MB)")
        
        result = TranscriptionResult(
            transcription="",
            diarization=None,
            speakers_text={},
            formatted_transcript="",
            speakers_summary="",
            compression_info=None
        )
        
        # Инициализируем информацию о сжатии
        compression_info = {
            "compressed": False,
            "original_size_mb": 0,
            "compressed_size_mb": 0,
            "compression_ratio": 0,
            "compression_saved_mb": 0
        }
        
        try:
            # Пробуем диаризацию с WhisperX (если доступна)
            if DIARIZATION_AVAILABLE and settings.enable_diarization:
                try:
                    logger.info("Выполнение диаризации...")
                    if progress_callback:
                        progress_callback(10, "Инициализация диаризации...")
                    
                    diarization_result = await diarization_service.diarize_file(
                        file_path, language, progress_callback
                    )
                    
                    if diarization_result:
                        if progress_callback:
                            progress_callback(90, "Обработка результатов диаризации...")
                        
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
                        result.compression_info = compression_info
                        
                        if progress_callback:
                            progress_callback(100, "Диаризация завершена!")
                        
                        logger.info(f"Диаризация успешна. Найдено говорящих: {len(diarization_result.speakers)}")
                        return result
                        
                except Exception as e:
                    logger.warning(f"Ошибка при диаризации, переходим к обычной транскрипции: {e}")
            
            # Выбираем метод транскрипции в зависимости от настроек
            if settings.transcription_mode == "speechmatics" and SPEECHMATICS_AVAILABLE and speechmatics_service.is_available():
                # Транскрипция через Speechmatics API
                try:
                    if progress_callback:
                        progress_callback(20, "Подготовка к транскрипции через Speechmatics...")
                    
                    logger.info("Выполнение транскрипции через Speechmatics...")
                    
                    # Выполняем транскрипцию через Speechmatics
                    result = await speechmatics_service.transcribe_file(
                        file_path=file_path,
                        language=language,
                        enable_diarization=settings.enable_diarization,
                        progress_callback=progress_callback
                    )
                    
                    if progress_callback:
                        progress_callback(100, "Транскрипция через Speechmatics завершена!")
                    
                    logger.info(f"Транскрипция через Speechmatics завершена. Длина текста: {len(result.transcription)} символов")
                    return result
                    
                except (CloudTranscriptionError, SpeechmaticsAPIError) as e:
                    # При ошибке Speechmatics переключаемся на локальную транскрипцию
                    logger.warning(f"Ошибка транскрипции через Speechmatics, переключаемся на локальную: {e}")
                    if progress_callback:
                        progress_callback(20, "Speechmatics недоступен, используем локальную транскрипцию...")
                    
                    self._load_whisper_model()
                    
                    if progress_callback:
                        progress_callback(40, "Выполнение локальной транскрипции...")
                    
                    whisper_result = self._transcribe_with_progress(
                        file_path, language, progress_callback
                    )
                    
                    if progress_callback:
                        progress_callback(90, "Обработка результатов...")
                    
                    transcription = whisper_result["text"].strip()
                    
                    if progress_callback:
                        progress_callback(100, "Локальная транскрипция завершена!")
                    
                    logger.info(f"Локальная транскрибация завершена после fallback. Длина текста: {len(transcription)} символов")
                    
            elif settings.transcription_mode == "cloud" and self.groq_client:
                # Пробуем облачную транскрипцию с автоматическим fallback
                try:
                    # Облачная транскрипция через Groq (проверка размера происходит внутри)
                    if progress_callback:
                        progress_callback(20, "Подготовка к облачной транскрипции...")
                    
                    logger.info("Выполнение облачной транскрипции через Groq...")
                    transcription, compression_info = await self._transcribe_with_groq(file_path, progress_callback)
                    
                    if progress_callback:
                        progress_callback(100, "Облачная транскрипция завершена!")
                
                except (CloudTranscriptionError, GroqAPIError) as e:
                    # При ошибке облачной транскрипции автоматически переключаемся на локальную
                    logger.warning(f"Ошибка облачной транскрипции, переключаемся на локальную: {e}")
                    if progress_callback:
                        progress_callback(20, "Облачная транскрипция недоступна, используем локальную...")
                    
                    self._load_whisper_model()
                    
                    if progress_callback:
                        progress_callback(40, "Выполнение локальной транскрипции...")
                    
                    whisper_result = self._transcribe_with_progress(
                        file_path, language, progress_callback
                    )
                    
                    if progress_callback:
                        progress_callback(90, "Обработка результатов...")
                    
                    transcription = whisper_result["text"].strip()
                    
                    if progress_callback:
                        progress_callback(100, "Локальная транскрипция завершена!")
                    
                    logger.info(f"Локальная транскрибация завершена после fallback. Длина текста: {len(transcription)} символов")
                    
            elif settings.transcription_mode == "hybrid" and self.groq_client:
                # Гибридный подход: облачная транскрипция + локальная диаризация
                if progress_callback:
                    progress_callback(20, "Подготовка к гибридной обработке...")
                
                logger.info("Выполнение гибридной транскрипции: облачная + диаризация...")
                
                # Пробуем облачную транскрипцию с fallback на локальную
                try:
                    # Сначала выполняем облачную транскрипцию (проверка размера происходит внутри)
                    if progress_callback:
                        progress_callback(30, "Облачная транскрипция...")
                    
                    transcription, compression_info = await self._transcribe_with_groq(file_path, progress_callback)
                
                except (CloudTranscriptionError, GroqAPIError) as e:
                    # При ошибке облачной транскрипции автоматически переключаемся на локальную
                    logger.warning(f"Ошибка облачной транскрипции в гибридном режиме, переключаемся на локальную: {e}")
                    if progress_callback:
                        progress_callback(30, "Облачная транскрипция недоступна, используем локальную...")
                    
                    self._load_whisper_model()
                    
                    whisper_result = self._transcribe_with_progress(
                        file_path, language, progress_callback
                    )
                    
                    transcription = whisper_result["text"].strip()
                
                # Затем применяем диаризацию к уже полученному тексту
                if DIARIZATION_AVAILABLE and settings.enable_diarization:
                    if progress_callback:
                        progress_callback(70, "Применение диаризации к тексту...")
                    
                    logger.info("Применение диаризации к тексту...")
                    
                    try:
                        # Используем диаризацию для разделения говорящих
                        diarization_result = await diarization_service.diarize_file(
                            file_path, language, progress_callback
                        )
                        
                        if diarization_result:
                            if progress_callback:
                                progress_callback(90, "Обработка результатов диаризации...")
                            
                            # Обновляем результат с диаризацией
                            result.diarization = diarization_result.to_dict()
                            result.speakers_text = diarization_result.get_speakers_text()
                            result.formatted_transcript = diarization_result.get_formatted_transcript()
                            result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                            
                            logger.info(f"Гибридная обработка завершена. Найдено говорящих: {len(diarization_result.speakers)}")
                            
                            if progress_callback:
                                progress_callback(100, "Гибридная обработка завершена!")
                            
                            result.transcription = transcription
                            return result
                            
                    except Exception as e:
                        logger.warning(f"Ошибка при диаризации в гибридном режиме: {e}")
                        # Продолжаем без диаризации
                
                if progress_callback:
                    progress_callback(100, "Гибридная обработка завершена!")
                
                logger.info(f"Гибридная транскрибация завершена. Длина текста: {len(transcription)} символов")
                
            else:
                # Fallback к обычной транскрипции через Whisper
                if progress_callback:
                    progress_callback(20, "Загрузка модели Whisper...")
                
                self._load_whisper_model()
                
                if progress_callback:
                    progress_callback(40, "Выполнение транскрипции...")
                
                logger.info("Выполнение стандартной транскрипции...")
                
                # Создаем обертку для отслеживания прогресса
                whisper_result = self._transcribe_with_progress(
                    file_path, language, progress_callback
                )
                
                if progress_callback:
                    progress_callback(90, "Обработка результатов...")
                
                transcription = whisper_result["text"].strip()
                
                if progress_callback:
                    progress_callback(100, "Транскрипция завершена!")
                
                logger.info(f"Стандартная транскрибация завершена. Длина текста: {len(transcription)} символов")
            
            result.transcription = transcription
            result.formatted_transcript = transcription  # Без разделения говорящих
            result.compression_info = compression_info
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при транскрибации файла {file_path}: {e}")
            if "ffmpeg" in str(e).lower():
                raise TranscriptionError(
                    "ffmpeg не найден. Установите ffmpeg для обработки аудио/видео файлов",
                    file_path
                )
            raise TranscriptionError(str(e), file_path)
    
    def _transcribe_with_progress(self, file_path: str, language: str, progress_callback=None):
        """Транскрипция с имитацией прогресса"""
        import time
        import threading
        
        # Создаем результат для хранения
        result_container = {"result": None, "error": None}
        
        def whisper_worker():
            """Выполнить транскрипцию в отдельном потоке"""
            try:
                result_container["result"] = self.whisper_model.transcribe(
                    file_path, 
                    language=language,
                    word_timestamps=False
                )
            except Exception as e:
                result_container["error"] = e
        
        # Запускаем транскрипцию в отдельном потоке
        thread = threading.Thread(target=whisper_worker)
        thread.start()
        
        # Имитируем прогресс во время выполнения
        if progress_callback:
            current_progress = 40
            while thread.is_alive() and current_progress < 85:
                time.sleep(2)  # Обновляем каждые 2 секунды
                current_progress += 5
                progress_callback(current_progress, "Транскрибация в процессе...")
        
        # Ждем завершения
        thread.join()
        
        if result_container["error"]:
            raise result_container["error"]
            
        return result_container["result"]
    
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
            result = await self.transcribe_with_diarization(file_path, language)
            
            return result
            
        finally:
            # Удаляем временный файл
            if file_path:
                self.cleanup_file(file_path)
