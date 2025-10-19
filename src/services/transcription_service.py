"""
Обновленный сервис транскрипции с защитой от OOM
"""

import os
import asyncio
import tempfile
import whisper
import httpx
import shutil
import psutil
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger

from src.models.processing import TranscriptionResult, DiarizationData
from src.exceptions.processing import TranscriptionError, CloudTranscriptionError, GroqAPIError, SpeechmaticsAPIError, DeepgramAPIError
from src.performance.oom_protection import oom_protected, get_oom_protection, memory_safe_operation
from config import settings

# Leopard (Picovoice) STT
try:
    import pvleopard
    LEOPARD_AVAILABLE = True
except ImportError:
    LEOPARD_AVAILABLE = False
    logger.warning("pvleopard (Leopard STT) недоступен")

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

try:
    from .deepgram_service import deepgram_service
    DEEPGRAM_AVAILABLE = True
except ImportError:
    DEEPGRAM_AVAILABLE = False
    logger.warning("Deepgram сервис недоступен")


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
        
        # Инициализация Deepgram сервиса
        if DEEPGRAM_AVAILABLE and deepgram_service.is_available():
            logger.info("Deepgram сервис доступен")
        else:
            logger.warning("Deepgram сервис недоступен")
        
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
    
    def _preprocess_audio(
        self,
        file_path: str,
        suffix: str,
        ffmpeg_args: list[str],
        target_description: str,
    ) -> tuple[str, dict]:
        """Универсальная предобработка аудио через ffmpeg с расчетом информации о сжатии."""
        compression_info = {
            "compressed": False,
            "original_size_mb": 0,
            "compressed_size_mb": 0,
            "compression_ratio": 0,
            "compression_saved_mb": 0
        }

        try:
            if not self._check_ffmpeg():
                logger.warning(f"ffmpeg не найден, пропускаем предобработку для {target_description}")
                return file_path, compression_info

            # Создаем временный файл для предобработки
            temp_file = self.temp_dir / f"{Path(file_path).stem}_{suffix}"

            # Конвертируем в MP3 с параметрами для Groq API
            import subprocess
            cmd = [
                "ffmpeg",
                "-i", file_path,
                *ffmpeg_args,
                "-y",  # Перезаписать существующий файл
                str(temp_file)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                original_size = os.path.getsize(file_path)
                processed_size = os.path.getsize(temp_file)
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

                logger.info(
                    f"Файл предобработан для {target_description}: {processed_mb:.1f}MB "
                    f"(было: {original_mb:.1f}MB, сжатие: {compression_info['compression_ratio']:.1f}%)"
                )
                return str(temp_file), compression_info
            else:
                logger.warning(
                    f"Ошибка предобработки файла для {target_description}: {result.stderr}"
                )
                return file_path, compression_info
                
        except Exception as e:
            logger.warning(f"Не удалось предобработать файл для {target_description}: {e}")
            return file_path, compression_info

    def _preprocess_for_groq(self, file_path: str) -> tuple[str, dict]:
        """Предобработать файл для Groq API: конвертировать в 16KHz моно MP3"""
        ffmpeg_args = [
            "-ar", "16000",  # Частота дискретизации 16KHz
            "-ac", "1",      # Моно
            "-map", "0:a",   # Только аудио поток
            "-c:a", "mp3",   # MP3 кодек
            "-b:a", "64k",   # Низкий битрейт для максимального сжатия
        ]

        return self._preprocess_audio(
            file_path=file_path,
            suffix="preprocessed.mp3",
            ffmpeg_args=ffmpeg_args,
            target_description="Groq API"
        )

    def _preprocess_for_speechmatics(self, file_path: str) -> tuple[str, dict]:
        """Предобработать файл для Speechmatics API аналогично Groq (16KHz моно MP3)."""
        ffmpeg_args = [
            "-ar", "16000",
            "-ac", "1",
            "-map", "0:a",
            "-c:a", "mp3",
            "-b:a", "64k",
        ]

        return self._preprocess_audio(
            file_path=file_path,
            suffix="speechmatics.mp3",
            ffmpeg_args=ffmpeg_args,
            target_description="Speechmatics API"
        )
    
    def _preprocess_for_deepgram(self, file_path: str) -> tuple[str, dict]:
        """Предобработать файл для Deepgram API (16KHz моно MP3)."""
        ffmpeg_args = [
            "-ar", "16000",
            "-ac", "1",
            "-map", "0:a",
            "-c:a", "mp3",
            "-b:a", "64k",
        ]

        return self._preprocess_audio(
            file_path=file_path,
            suffix="deepgram.mp3",
            ffmpeg_args=ffmpeg_args,
            target_description="Deepgram API"
        )
    
    async def _transcribe_with_groq(self, file_path: str) -> tuple[str, dict]:
        """Транскрибация через Groq API"""
        if not self.groq_client:
            raise CloudTranscriptionError("Groq клиент не инициализирован", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        try:
            logger.info(f"Начало облачной транскрипции файла: {file_path}")
            
            # Предобрабатываем файл для Groq API
            logger.info(f"Начинаем предобработку файла: {file_path}")
            
            processed_file, compression_info = self._preprocess_for_groq(file_path)
            logger.info(f"Предобработка завершена. Результат: {compression_info}")
            
            # Логируем информацию о сжатии (если есть)
            if compression_info and compression_info.get("compressed", False):
                logger.info(f"Файл был сжат перед отправкой: {compression_info}")
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
            
            # Читаем предобработанный файл и отправляем в Groq (в отдельном потоке, чтобы не блокировать event loop)

            def _groq_call_sync(path: str):
                with open(path, "rb") as f:
                    data = f.read()
                return self.groq_client.audio.transcriptions.create(
                    file=(os.path.basename(path), data),
                    model=settings.groq_model,
                    response_format="verbose_json",
                )

            transcription = await asyncio.to_thread(_groq_call_sync, processed_file)

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
                                          enable_diarization: bool = False) -> tuple[str, dict]:
        """Транскрипция через Speechmatics API"""
        if not SPEECHMATICS_AVAILABLE or not speechmatics_service.is_available():
            raise CloudTranscriptionError("Speechmatics сервис недоступен", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        try:
            logger.info(f"Начало транскрипции через Speechmatics: {file_path}")

            processed_file, compression_info = self._preprocess_for_speechmatics(file_path)

            # Выполняем транскрипцию через Speechmatics
            result = await speechmatics_service.transcribe_file(
                file_path=processed_file,
                language=language,
                enable_diarization=enable_diarization
            )

            # Возвращаем текст и информацию о сжатии (Speechmatics не сжимает файлы)
            if not compression_info.get("compressed"):
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

    async def _transcribe_with_deepgram(self, file_path: str, language: str = "ru", 
                                       enable_diarization: bool = False) -> tuple[str, dict]:
        """Транскрипция через Deepgram API"""
        if not DEEPGRAM_AVAILABLE or not deepgram_service.is_available():
            raise CloudTranscriptionError("Deepgram сервис недоступен", file_path)
        
        if not os.path.exists(file_path):
            raise CloudTranscriptionError(f"Файл не найден: {file_path}", file_path)
        
        try:
            logger.info(f"Начало транскрипции через Deepgram: {file_path}")

            processed_file, compression_info = self._preprocess_for_deepgram(file_path)

            # Выполняем транскрипцию через Deepgram
            result = await deepgram_service.transcribe_file(
                file_path=processed_file,
                language=language,
                enable_diarization=enable_diarization
            )

            # Возвращаем текст и информацию о сжатии
            if not compression_info.get("compressed"):
                compression_info = {
                    "compressed": False,
                    "original_size_mb": 0,
                    "compressed_size_mb": 0,
                    "compression_ratio": 0,
                    "compression_saved_mb": 0
                }

            return result.transcription, compression_info
            
        except Exception as e:
            logger.error(f"Ошибка при транскрипции через Deepgram {file_path}: {e}")
            raise CloudTranscriptionError(str(e), file_path)

    def _preprocess_for_leopard(self, file_path: str) -> str:
        """Подготовить аудио для Leopard: конвертировать в 16kHz mono WAV PCM s16le"""
        try:
            if not self._check_ffmpeg():
                logger.info("ffmpeg не найден — передаем исходный файл в Leopard")
                return file_path

            temp_wav = self.temp_dir / f"{Path(file_path).stem}_leopard.wav"
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
            else:
                logger.warning(f"Не удалось подготовить файл для Leopard: {result.stderr}")
                return file_path
        except Exception as e:
            logger.warning(f"Ошибка подготовки файла для Leopard: {e}")
            return file_path

    async def _transcribe_with_leopard(self, file_path: str) -> tuple[str, dict]:
        """Транскрипция через Picovoice Leopard (локально)"""
        if not LEOPARD_AVAILABLE:
            raise TranscriptionError("pvleopard не установлен", file_path)
        if not settings.picovoice_access_key:
            raise TranscriptionError("PICOVOICE_ACCESS_KEY не задан", file_path)

        # Подготовка формата для Leopard
        prepared_file = self._preprocess_for_leopard(file_path)

        def _run_leopard_sync(path: str) -> str:
            leopard = None
            try:
                # Если указан путь к языковой модели, используем его (например, русский)
                create_kwargs = {"access_key": settings.picovoice_access_key}
                if getattr(settings, "leopard_model_path", None):
                    create_kwargs["model_path"] = settings.leopard_model_path

                leopard = pvleopard.create(**create_kwargs)
                transcript, _words = leopard.process_file(path)
                return transcript.strip()
            finally:
                if leopard is not None:
                    try:
                        leopard.delete()
                    except Exception:
                        pass

        try:
            logger.info(f"Начало транскрипции через Leopard: {prepared_file}")
            transcript = await asyncio.to_thread(_run_leopard_sync, prepared_file)
            logger.info(f"Leopard транскрипция завершена. Длина: {len(transcript)} символов")
        except Exception as e:
            logger.error(f"Ошибка Leopard транскрипции {file_path}: {e}")
            raise TranscriptionError(str(e), file_path)

        compression_info = {
            "compressed": False,
            "original_size_mb": 0,
            "compressed_size_mb": 0,
            "compression_ratio": 0,
            "compression_saved_mb": 0
        }

        return transcript, compression_info

    async def transcribe_with_diarization(self, file_path: str, language: str = "ru") -> TranscriptionResult:
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
            # Выбираем метод транскрипции в зависимости от настроек
            if settings.transcription_mode == "leopard":
                # Локальная транскрипция через Picovoice Leopard
                transcription, compression_info = await self._transcribe_with_leopard(file_path)

                # Применяем диаризацию при необходимости
                if DIARIZATION_AVAILABLE and settings.enable_diarization:
                    try:
                        logger.info("Применение диаризации к результатам Leopard транскрипции...")
                        diarization_result = await diarization_service.diarize_file(
                            file_path, language
                        )
                        if diarization_result:
                            result.diarization = diarization_result.to_dict()
                            result.speakers_text = diarization_result.get_speakers_text()
                            result.formatted_transcript = diarization_result.get_formatted_transcript()
                            result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                            logger.info(f"Диаризация применена. Найдено говорящих: {len(diarization_result.speakers)}")
                    except Exception as e:
                        logger.warning(f"Ошибка диаризации после Leopard: {e}")

                result.transcription = transcription
                if not result.formatted_transcript:
                    result.formatted_transcript = transcription
                result.compression_info = compression_info
                
                return result
            
            if settings.transcription_mode == "deepgram" and DEEPGRAM_AVAILABLE and deepgram_service.is_available():
                # Транскрипция через Deepgram API
                try:
                    logger.info("Выполнение транскрипции через Deepgram...")
                    
                    processed_file, compression_info = self._preprocess_for_deepgram(file_path)

                    # Выполняем транскрипцию через Deepgram (с диаризацией если включена)
                    result = await deepgram_service.transcribe_file(
                        file_path=processed_file,
                        language=language,
                        enable_diarization=settings.enable_diarization
                    )

                    # Сохраняем информацию о сжатии в результате
                    if result:
                        result.compression_info = compression_info
                    
                    logger.info(f"Транскрипция через Deepgram завершена. Длина текста: {len(result.transcription)} символов")
                    if settings.enable_diarization and result.diarization:
                        logger.info(f"Диаризация выполнена через Deepgram. Найдено говорящих: {len(result.speakers_text) if result.speakers_text else 0}")
                    
                    return result
                    
                except (CloudTranscriptionError, DeepgramAPIError) as e:
                    # При ошибке Deepgram переключаемся на локальную транскрипцию
                    logger.warning(f"Ошибка транскрипции через Deepgram, переключаемся на локальную: {e}")
                    self._load_whisper_model()
                    
                    whisper_result = await self._transcribe_with_progress(
                        file_path, language
                    )
                    
                    transcription = whisper_result["text"].strip()
                    
                    logger.info(f"Локальная транскрибация завершена после fallback. Длина текста: {len(transcription)} символов")
                    
                    # Применяем диаризацию к результатам fallback транскрипции
                    if DIARIZATION_AVAILABLE and settings.enable_diarization:
                        try:
                            logger.info("Применение диаризации к результатам fallback транскрипции...")
                            diarization_result = await diarization_service.diarize_file(
                                file_path, language
                            )
                            
                            if diarization_result:
                                result.diarization = diarization_result.to_dict()
                                result.speakers_text = diarization_result.get_speakers_text()
                                result.formatted_transcript = diarization_result.get_formatted_transcript()
                                result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                                
                                logger.info(f"Диаризация применена к fallback транскрипции. Найдено говорящих: {len(diarization_result.speakers)}")
                                
                        except Exception as e:
                            logger.warning(f"Ошибка при применении диаризации к fallback транскрипции: {e}")
                    
                    result.transcription = transcription
                    if not result.formatted_transcript:
                        result.formatted_transcript = transcription
                    result.compression_info = compression_info
                    
                    return result
            
            if settings.transcription_mode == "speechmatics" and SPEECHMATICS_AVAILABLE and speechmatics_service.is_available():
                # Транскрипция через Speechmatics API
                try:
                    logger.info("Выполнение транскрипции через Speechmatics...")
                    
                    processed_file, compression_info = self._preprocess_for_speechmatics(file_path)

                    # Выполняем транскрипцию через Speechmatics (с диаризацией если включена)
                    result = await speechmatics_service.transcribe_file(
                        file_path=processed_file,
                        language=language,
                        enable_diarization=settings.enable_diarization
                    )

                    # Сохраняем информацию о сжатии в результате
                    if result:
                        result.compression_info = compression_info
                    
                    logger.info(f"Транскрипция через Speechmatics завершена. Длина текста: {len(result.transcription)} символов")
                    if settings.enable_diarization and result.diarization:
                        logger.info(f"Диаризация выполнена через Speechmatics. Найдено говорящих: {len(result.speakers_text) if result.speakers_text else 0}")
                    
                    return result
                    
                except (CloudTranscriptionError, SpeechmaticsAPIError) as e:
                    # При ошибке Speechmatics переключаемся на локальную транскрипцию
                    logger.warning(f"Ошибка транскрипции через Speechmatics, переключаемся на локальную: {e}")
                    self._load_whisper_model()
                    
                    whisper_result = await self._transcribe_with_progress(
                        file_path, language
                    )
                    
                    transcription = whisper_result["text"].strip()
                    
                    logger.info(f"Локальная транскрибация завершена после fallback. Длина текста: {len(transcription)} символов")
                    
                    # Применяем диаризацию к результатам fallback транскрипции
                    if DIARIZATION_AVAILABLE and settings.enable_diarization:
                        try:
                            logger.info("Применение диаризации к результатам fallback транскрипции...")
                            diarization_result = await diarization_service.diarize_file(
                                file_path, language
                            )
                            
                            if diarization_result:
                                result.diarization = diarization_result.to_dict()
                                result.speakers_text = diarization_result.get_speakers_text()
                                result.formatted_transcript = diarization_result.get_formatted_transcript()
                                result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                                
                                logger.info(f"Диаризация применена к fallback транскрипции. Найдено говорящих: {len(diarization_result.speakers)}")
                                
                        except Exception as e:
                            logger.warning(f"Ошибка при применении диаризации к fallback транскрипции: {e}")
                    
                    result.transcription = transcription
                    if not result.formatted_transcript:
                        result.formatted_transcript = transcription
                    result.compression_info = compression_info
                    
                    return result
                    
            elif settings.transcription_mode == "cloud" and self.groq_client:
                # Пробуем облачную транскрипцию с автоматическим fallback
                try:
                    # Облачная транскрипция через Groq (проверка размера происходит внутри)
                    logger.info("Выполнение облачной транскрипции через Groq...")
                    transcription, compression_info = await self._transcribe_with_groq(file_path)
                
                except (CloudTranscriptionError, GroqAPIError) as e:
                    # При ошибке облачной транскрипции автоматически переключаемся на локальную
                    logger.warning(f"Ошибка облачной транскрипции, переключаемся на локальную: {e}")
                    self._load_whisper_model()
                    
                    whisper_result = await self._transcribe_with_progress(
                        file_path, language
                    )
                    
                    transcription = whisper_result["text"].strip()
                    
                    logger.info(f"Локальная транскрибация завершена после fallback. Длина текста: {len(transcription)} символов")
                    
                    # Применяем диаризацию к результатам fallback транскрипции
                    if DIARIZATION_AVAILABLE and settings.enable_diarization:
                        try:
                            logger.info("Применение диаризации к результатам fallback транскрипции...")
                            diarization_result = await diarization_service.diarize_file(
                                file_path, language
                            )
                            
                            if diarization_result:
                                result.diarization = diarization_result.to_dict()
                                result.speakers_text = diarization_result.get_speakers_text()
                                result.formatted_transcript = diarization_result.get_formatted_transcript()
                                result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                                
                                logger.info(f"Диаризация применена к fallback транскрипции. Найдено говорящих: {len(diarization_result.speakers)}")
                                
                        except Exception as e:
                            logger.warning(f"Ошибка при применении диаризации к fallback транскрипции: {e}")
                    
                    result.transcription = transcription
                    if not result.formatted_transcript:
                        result.formatted_transcript = transcription
                    result.compression_info = compression_info
                    
                    return result
                    
            elif settings.transcription_mode == "hybrid" and self.groq_client:
                # Гибридный подход: облачная транскрипция + локальная диаризация
                
                logger.info("Выполнение гибридной транскрипции: облачная + диаризация...")
                
                # Пробуем облачную транскрипцию с fallback на локальную
                try:
                    # Сначала выполняем облачную транскрипцию (проверка размера происходит внутри)
                    
                    transcription, compression_info = await self._transcribe_with_groq(file_path)
                
                except (CloudTranscriptionError, GroqAPIError) as e:
                    # При ошибке облачной транскрипции автоматически переключаемся на локальную
                    logger.warning(f"Ошибка облачной транскрипции в гибридном режиме, переключаемся на локальную: {e}")
                    
                    self._load_whisper_model()
                    
                    whisper_result = await self._transcribe_with_progress(
                        file_path, language
                    )
                    
                    transcription = whisper_result["text"].strip()
                
                # Затем применяем диаризацию к уже полученному тексту
                if DIARIZATION_AVAILABLE and settings.enable_diarization:
                    logger.info("Применение диаризации к тексту...")
                    
                    try:
                        # Используем диаризацию для разделения говорящих
                        diarization_result = await diarization_service.diarize_file(
                            file_path, language
                        )
                        
                        if diarization_result:
                            # Обновляем результат с диаризацией
                            result.diarization = diarization_result.to_dict()
                            result.speakers_text = diarization_result.get_speakers_text()
                            result.formatted_transcript = diarization_result.get_formatted_transcript()
                            result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                            
                            logger.info(f"Гибридная обработка завершена. Найдено говорящих: {len(diarization_result.speakers)}")
                            result.transcription = transcription
                            return result
                            
                    except Exception as e:
                        logger.warning(f"Ошибка при диаризации в гибридном режиме: {e}")
                        # Продолжаем без диаризации
                
                
                logger.info(f"Гибридная транскрибация завершена. Длина текста: {len(transcription)} символов")
                
            else:
                # Fallback к обычной транскрипции через Whisper
                self._load_whisper_model()
                
                logger.info("Выполнение стандартной транскрипции...")
                
                # Создаем обертку для отслеживания прогресса
                whisper_result = await self._transcribe_with_progress(
                    file_path, language
                )
                
                transcription = whisper_result["text"].strip()
                
                logger.info(f"Стандартная транскрибация завершена. Длина текста: {len(transcription)} символов")
            
            # Применяем диаризацию к результатам локальной транскрипции, если включена
            # (для Speechmatics диаризация уже включена в сам сервис)
            if DIARIZATION_AVAILABLE and settings.enable_diarization and settings.transcription_mode != "speechmatics":
                try:
                    logger.info("Применение диаризации к результатам локальной транскрипции...")
                    diarization_result = await diarization_service.diarize_file(
                        file_path, language
                    )
                    
                    if diarization_result:
                        # Обновляем результат с диаризацией
                        result.diarization = diarization_result.to_dict()
                        result.speakers_text = diarization_result.get_speakers_text()
                        result.formatted_transcript = diarization_result.get_formatted_transcript()
                        result.speakers_summary = diarization_service.get_speakers_summary(diarization_result)
                        
                        logger.info(f"Диаризация применена к локальной транскрипции. Найдено говорящих: {len(diarization_result.speakers)}")
                        
                except Exception as e:
                    logger.warning(f"Ошибка при применении диаризации: {e}")
                    # Продолжаем без диаризации
            
            result.transcription = transcription
            if not result.formatted_transcript:  # Если диаризация не сработала
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
    
    async def _transcribe_with_progress(self, file_path: str, language: str):
        """Транскрипция (не блокирует event loop)"""
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
        
        # Ожидаем выполнение, не блокируя event loop
        while thread.is_alive():
            await asyncio.sleep(0.1)
        
        # Ждем завершения в отдельном потоке, чтобы не блокировать event loop
        await asyncio.to_thread(thread.join)
        
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
