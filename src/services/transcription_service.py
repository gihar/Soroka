"""
Обновленный сервис транскрипции с защитой от OOM
"""

import asyncio
import os
import shutil
from pathlib import Path

import httpx
from loguru import logger

from src.config import settings
from src.exceptions.processing import (
    TranscriptionError,
)
from src.models.processing import TranscriptionResult
from src.performance.oom_protection import get_oom_protection, oom_protected
from src.services.transcription_backends import build_backends

# Leopard (Picovoice) STT — lazy import for faster startup
LEOPARD_AVAILABLE = None  # resolved on first use


def _check_leopard_available():
    global LEOPARD_AVAILABLE
    if LEOPARD_AVAILABLE is None:
        try:
            import pvleopard  # noqa: F401
            LEOPARD_AVAILABLE = True
        except ImportError:
            LEOPARD_AVAILABLE = False
            logger.warning("pvleopard (Leopard STT) недоступен")
    return LEOPARD_AVAILABLE

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logger.warning("Groq SDK недоступен")

try:
    from src.services.diarization_service import diarization_service
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

        # Реестр адаптеров бэкендов транскрипции
        self._backends = build_backends(self)
    
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
                import whisper
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
    
    async def _preprocess_audio(
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

            # Конвертируем в MP3 с параметрами через асинхронный subprocess
            cmd = [
                "ffmpeg",
                "-i", file_path,
                *ffmpeg_args,
                "-y",  # Перезаписать существующий файл
                str(temp_file)
            ]

            # Используем асинхронный subprocess для корректной обработки сигналов
            logger.info(f"Начинаем конвертацию файла для {target_description}: {file_path}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                # Таймаут 30 минут для длинных файлов
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=1800
                )
            except asyncio.TimeoutError:
                logger.error(f"Превышен таймаут конвертации файла для {target_description}")
                process.kill()
                await process.wait()
                return file_path, compression_info

            if process.returncode == 0:
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
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.warning(
                    f"Ошибка предобработки файла для {target_description}: {stderr_text}"
                )
                return file_path, compression_info
                
        except Exception as e:
            logger.warning(f"Не удалось предобработать файл для {target_description}: {e}")
            return file_path, compression_info

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
        
        # Дефолтная информация о сжатии (если адаптер её не заполнил)
        compression_info = {
            "compressed": False,
            "original_size_mb": 0,
            "compressed_size_mb": 0,
            "compression_ratio": 0,
            "compression_saved_mb": 0
        }
        
        try:
            backend = self._backends.get(settings.transcription_mode) or self._backends["local"]
            result = await self._run_with_fallback(backend, file_path, language)
            result = await self._ensure_diarization(result, file_path, language)

            if result.compression_info is None:
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

    async def _run_with_fallback(self, backend, file_path: str, language: str) -> TranscriptionResult:
        """Единая политика: недоступен или типизированная ошибка → локальный Whisper."""
        whisper = self._backends["local"]

        if backend is not whisper and not backend.is_available():
            logger.warning(f"Бэкенд '{backend.name}' недоступен — используем локальный Whisper")
            return await whisper.transcribe(file_path, language)

        try:
            return await backend.transcribe(file_path, language)
        except TranscriptionError as e:
            if backend is whisper:
                raise
            logger.warning(f"Ошибка бэкенда '{backend.name}', переключаемся на локальную транскрипцию: {e}")
            return await whisper.transcribe(file_path, language)

    async def _ensure_diarization(self, result: TranscriptionResult, file_path: str,
                                  language: str) -> TranscriptionResult:
        """Применить локальную диаризацию ровно один раз, если бэкенд её не дал."""
        if not (DIARIZATION_AVAILABLE and settings.enable_diarization):
            return result
        if result.diarization:
            return result

        try:
            logger.info("Применение локальной диаризации к транскрипции...")
            diarization_result = await diarization_service.diarize_file(file_path, language)
            if diarization_result:
                result.diarization = diarization_result
                logger.info(f"Диаризация применена. Найдено говорящих: {len(diarization_result.speakers)}")
        except Exception as e:
            logger.warning(f"Ошибка при применении диаризации: {e}")
            # Продолжаем без диаризации

        return result

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
