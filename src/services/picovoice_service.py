"""
Сервис для диаризации через Picovoice Falcon (локальная библиотека)
"""

import os
import json
import tempfile
import shutil
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from loguru import logger
import asyncio

from config import settings
from src.models.processing import DiarizationData

try:
    import pvfalcon
    FALCON_AVAILABLE = True
except ImportError:
    FALCON_AVAILABLE = False
    logger.warning("pvfalcon не установлен. Picovoice диаризация недоступна.")


class PicovoiceService:
    """Сервис для работы с Picovoice Falcon (локальная библиотека)"""
    
    def __init__(self):
        self.access_key = settings.picovoice_access_key
        self.falcon = None
        
        if not self.access_key:
            logger.warning("Picovoice Access Key не настроен")
        elif not FALCON_AVAILABLE:
            logger.warning("pvfalcon библиотека не установлена")
        else:
            logger.info("Picovoice Falcon сервис инициализирован")
    
    def _get_falcon_instance(self):
        """Получить экземпляр Falcon"""
        if self.falcon is None and FALCON_AVAILABLE:
            try:
                logger.info("Инициализация Picovoice Falcon...")
                if not self.access_key:
                    logger.error("Picovoice Access Key не настроен")
                    return None
                
                self.falcon = pvfalcon.create(access_key=self.access_key)
                logger.info("Picovoice Falcon успешно инициализирован")
                return self.falcon
            except Exception as e:
                logger.error(f"Ошибка при инициализации Falcon: {e}")
                self.falcon = None
                return None
        return self.falcon
    
    async def _convert_audio_for_picovoice(self, file_path: str) -> str:
        """Конвертировать аудио в формат, подходящий для Picovoice"""
        try:
            # Создаем временный файл
            temp_dir = Path(settings.temp_dir)
            temp_dir.mkdir(exist_ok=True)
            
            output_path = temp_dir / f"picovoice_{Path(file_path).stem}.wav"
            
            # Используем ffmpeg для конвертации
            cmd = [
                'ffmpeg', '-i', file_path,
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ac', '1',               # Моно
                '-ar', '16000',           # 16kHz
                '-y',                     # Перезаписать если существует
                str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Аудио конвертировано для Picovoice: {output_path}")
                return str(output_path)
            else:
                logger.error(f"Ошибка конвертации: {stderr.decode()}")
                return file_path
                
        except Exception as e:
            logger.error(f"Ошибка при конвертации аудио: {e}")
            return file_path
    

    
    async def diarize_file(self, file_path: str, progress_callback=None) -> Optional[DiarizationData]:
        """Выполнить диаризацию файла через Picovoice Falcon"""
        if not self.access_key:
            logger.error("Picovoice Access Key не настроен")
            return None
        
        if not FALCON_AVAILABLE:
            logger.error("pvfalcon библиотека не установлена")
            return None
        
        try:
            logger.info(f"Начало диаризации через Picovoice Falcon: {file_path}")
            
            if progress_callback:
                progress_callback(10, "Инициализация Picovoice Falcon...")
            
            # Получаем экземпляр Falcon
            falcon = self._get_falcon_instance()
            if not falcon:
                logger.error("Не удалось инициализировать Picovoice Falcon")
                return None
            
            if progress_callback:
                progress_callback(30, "Подготовка аудио файла...")
            
            # Конвертируем файл если нужно
            converted_path = await self._convert_audio_for_picovoice(file_path)
            
            if progress_callback:
                progress_callback(50, "Выполнение диаризации...")
            
            # Выполняем диаризацию
            logger.info("Запуск диаризации с Picovoice Falcon...")
            segments = falcon.process_file(converted_path)
            
            if progress_callback:
                progress_callback(90, "Обработка результатов...")
            
            # Преобразуем результат в наш формат
            diarization_data = self._parse_falcon_result(segments)
            
            if progress_callback:
                progress_callback(100, "Диаризация Picovoice Falcon завершена!")
            
            logger.info(f"Диаризация Picovoice Falcon успешна. Найдено говорящих: {diarization_data.total_speakers}")
            return diarization_data
            
        except Exception as e:
            logger.error(f"Ошибка при диаризации через Picovoice Falcon: {e}")
            return None
    
    def _parse_falcon_result(self, segments) -> DiarizationData:
        """Парсить результат Falcon в стандартный формат"""
        try:
            diarization_segments = []
            speakers = set()
            
            for segment in segments:
                speaker = f"SPEAKER_{segment.speaker_tag}"
                speakers.add(speaker)
                
                diarization_segments.append({
                    "start": segment.start_sec,
                    "end": segment.end_sec,
                    "speaker": speaker,
                    "text": ""  # Текст будет добавлен отдельно
                })
            
            speakers_list = sorted(list(speakers))
            
            return DiarizationData(
                segments=diarization_segments,
                speakers=speakers_list,
                total_speakers=len(speakers_list)
            )
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге результата Falcon: {e}")
            return DiarizationData(segments=[], speakers=[], total_speakers=0)
    
    def cleanup(self):
        """Очистка ресурсов"""
        if self.falcon:
            try:
                self.falcon.delete()
                self.falcon = None
                logger.info("Picovoice Falcon ресурсы освобождены")
            except Exception as e:
                logger.warning(f"Ошибка при очистке Falcon ресурсов: {e}")


# Глобальный экземпляр сервиса
picovoice_service = PicovoiceService()
