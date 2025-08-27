"""
Модуль диаризации аудио и видео файлов
"""

import os
import warnings
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from loguru import logger
from config import settings

# Подавляем предупреждения для библиотек ML
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import whisperx
    import torch
    WHISPERX_AVAILABLE = True
except ImportError:
    WHISPERX_AVAILABLE = False
    logger.warning("WhisperX не установлен. Диаризация будет недоступна.")

try:
    from pyannote.audio import Pipeline
    PYANNOTE_AVAILABLE = True
except ImportError:
    PYANNOTE_AVAILABLE = False
    logger.warning("Pyannote.audio не установлен. Резервный вариант диаризации недоступен.")


class DiarizationResult:
    """Результат диаризации"""
    
    def __init__(self, segments: List[Dict[str, Any]], speakers: List[str]):
        self.segments = segments  # Список сегментов с информацией о говорящих
        self.speakers = speakers  # Список уникальных говорящих
        
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            "segments": self.segments,
            "speakers": self.speakers,
            "total_speakers": len(self.speakers)
        }
    
    def get_speakers_text(self) -> Dict[str, str]:
        """Получить текст каждого говорящего отдельно"""
        speakers_text = {}
        
        for segment in self.segments:
            speaker = segment.get('speaker', 'SPEAKER_UNKNOWN')
            text = segment.get('text', '').strip()
            
            if speaker not in speakers_text:
                speakers_text[speaker] = []
            
            if text:
                speakers_text[speaker].append(text)
        
        # Объединяем текст каждого говорящего
        return {speaker: ' '.join(texts) for speaker, texts in speakers_text.items()}
    
    def get_formatted_transcript(self) -> str:
        """Получить форматированную транскрипцию с говорящими"""
        formatted_lines = []
        current_speaker = None
        current_text = []
        
        for segment in self.segments:
            speaker = segment.get('speaker', 'SPEAKER_UNKNOWN')
            text = segment.get('text', '').strip()
            
            if not text:
                continue
                
            if speaker != current_speaker:
                # Завершаем предыдущего говорящего
                if current_speaker and current_text:
                    formatted_lines.append(f"{current_speaker}: {' '.join(current_text)}")
                
                # Начинаем нового говорящего
                current_speaker = speaker
                current_text = [text]
            else:
                current_text.append(text)
        
        # Добавляем последнего говорящего
        if current_speaker and current_text:
            formatted_lines.append(f"{current_speaker}: {' '.join(current_text)}")
        
        return '\n\n'.join(formatted_lines)


class DiarizationService:
    """Сервис для диаризации аудио и видео"""
    
    def __init__(self):
        self.whisperx_model = None
        self.align_model = None
        self.align_metadata = None
        self.diarize_model = None
        self.pyannote_pipeline = None
        self.device = self._get_device()
        logger.info(f"DiarizationService инициализирован с устройством: {self.device}")
        
    def _get_device(self) -> str:
        """Определить устройство для вычислений"""
        if settings.diarization_device == "cuda" and torch.cuda.is_available():
            return "cuda"
        elif settings.diarization_device == "mps" and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            # MPS часто имеет проблемы совместимости с WhisperX, поэтому используем CPU
            logger.warning("MPS устройство доступно, но может быть несовместимо с WhisperX. Используем CPU.")
            return "cpu"
        elif settings.diarization_device == "auto":
            # Автоматическое определение лучшего устройства
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                # Для MacOS с Apple Silicon используем CPU для стабильности
                logger.info("Обнаружен Apple Silicon (MPS), используем CPU для совместимости с WhisperX")
                return "cpu"
            else:
                return "cpu"
        return "cpu"
    
    def _get_compute_type(self) -> str:
        """Определить подходящий compute_type для устройства"""
        if settings.compute_type != "auto":
            return settings.compute_type
            
        # Автоматическое определение
        if self.device == "cuda":
            # Для CUDA можем попробовать float16
            return "float16"
        elif self.device == "mps":
            # Для Apple Silicon MPS используем float32 (int8 может работать нестабильно)
            return "float32"
        else:
            # Для CPU используем int8 для производительности
            return "int8"
    
    def _load_whisperx_models(self, language: str = "ru"):
        """Загрузить модели WhisperX"""
        if not WHISPERX_AVAILABLE:
            raise RuntimeError("WhisperX не установлен")
        
        try:
            # Загружаем модель транскрипции
            if self.whisperx_model is None:
                logger.info("Загрузка модели WhisperX для транскрипции...")
                # Определяем подходящий compute_type для устройства
                compute_type = self._get_compute_type()
                logger.info(f"Используется compute_type: {compute_type} для устройства: {self.device}")
                
                # Список fallback стратегий для загрузки модели
                strategies = [
                    (self.device, compute_type),
                    ("cpu", "int8"),  # Fallback на CPU с int8
                    ("cpu", "float32"),  # Fallback на CPU с float32
                ]
                
                model_loaded = False
                for device, comp_type in strategies:
                    try:
                        logger.info(f"Попытка загрузки модели с устройством: {device}, compute_type: {comp_type}")
                        self.whisperx_model = whisperx.load_model("large-v2", device, compute_type=comp_type)
                        if device != self.device:
                            logger.warning(f"Модель загружена с fallback устройством: {device}")
                            self.device = device  # Обновляем устройство для остальных компонентов
                        model_loaded = True
                        break
                    except Exception as e:
                        logger.warning(f"Ошибка загрузки с {device}/{comp_type}: {e}")
                        continue
                
                if not model_loaded:
                    raise RuntimeError("Не удалось загрузить модель WhisperX ни с одной конфигурацией")
            
            # Загружаем модель выравнивания
            if self.align_model is None:
                logger.info(f"Загрузка модели выравнивания для языка: {language}")
                try:
                    self.align_model, self.align_metadata = whisperx.load_align_model(
                        language_code=language, device=self.device
                    )
                except Exception as e:
                    logger.warning(f"Ошибка загрузки модели выравнивания: {e}")
                    # Пробуем с CPU
                    if self.device != "cpu":
                        logger.info("Попытка загрузки модели выравнивания на CPU...")
                        self.align_model, self.align_metadata = whisperx.load_align_model(
                            language_code=language, device="cpu"
                        )
                        self.device = "cpu"
                    else:
                        raise
            
            # В WhisperX 3.4.2+ DiarizationPipeline удален, используем pyannote.audio напрямую
            logger.info("WhisperX 3.4.2+ обнаружен. Диаризация будет выполняться через pyannote.audio")
                    
        except Exception as e:
            logger.error(f"Ошибка при загрузке моделей WhisperX: {e}")
            raise
    
    def _load_pyannote_pipeline(self):
        """Загрузить pipeline pyannote.audio (резервный вариант)"""
        if not PYANNOTE_AVAILABLE:
            raise RuntimeError("Pyannote.audio не установлен")
        
        try:
            if self.pyannote_pipeline is None:
                logger.info("Загрузка pipeline pyannote.audio...")
                if settings.huggingface_token:
                    self.pyannote_pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=settings.huggingface_token
                    )
                    
                    # Проверяем, что pipeline загружен правильно
                    if self.pyannote_pipeline is None:
                        raise RuntimeError("Pipeline не был загружен (None)")
                        
                    logger.info("Pipeline pyannote.audio успешно загружен")
                else:
                    logger.warning("Токен Hugging Face не настроен для pyannote.audio")
                    logger.info("Для получения токена посетите: https://huggingface.co/settings/tokens")
                    logger.info("Добавьте токен в переменную окружения HUGGINGFACE_TOKEN")
                    raise RuntimeError("Требуется токен Hugging Face для pyannote.audio. См. инструкции выше.")
                    
        except Exception as e:
            logger.error(f"Ошибка при загрузке pyannote.audio: {e}")
            # Сбрасываем pipeline при ошибке
            self.pyannote_pipeline = None
            raise
    
    def diarize_with_whisperx(self, file_path: str, language: str = "ru") -> DiarizationResult:
        """Транскрипция с WhisperX + диаризация с pyannote.audio"""
        try:
            # Загружаем модели WhisperX (только для транскрипции)
            self._load_whisperx_models(language)
            
            # Загружаем аудио
            logger.info(f"Загрузка аудио файла: {file_path}")
            audio = whisperx.load_audio(file_path)
            
            # Транскрибация
            logger.info("Выполнение транскрипции с WhisperX...")
            result = self.whisperx_model.transcribe(audio, batch_size=16)
            
            # Выравнивание (alignment)
            logger.info("Выполнение выравнивания...")
            result = whisperx.align(
                result["segments"], 
                self.align_model, 
                self.align_metadata, 
                audio, 
                self.device,
                return_char_alignments=False
            )
            
            # Диаризация с pyannote.audio
            logger.info("Выполнение диаризации с pyannote.audio...")
            self._load_pyannote_pipeline()
            
            # Дополнительная проверка, что pipeline загружен
            if self.pyannote_pipeline is None:
                raise RuntimeError("Pipeline pyannote.audio не был загружен")
            
            # Выполняем диаризацию
            diarization = self.pyannote_pipeline(file_path)
            
            # Проверяем результат диаризации
            if diarization is None:
                raise RuntimeError("Диаризация вернула None")
            
            # Привязываем результаты диаризации к транскрипции
            logger.info("Привязка говорящих к тексту...")
            
            # Создаем список диаризационных сегментов
            diarization_segments = []
            for segment, _, speaker in diarization.itertracks(yield_label=True):
                diarization_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": speaker
                })
            
            # Применяем диаризацию к сегментам транскрипции
            speakers = set()
            for segment in result.get("segments", []):
                segment_start = segment.get("start", 0)
                segment_end = segment.get("end", segment_start)
                
                # Находим перекрывающиеся диаризационные сегменты
                overlapping_speakers = []
                for diar_seg in diarization_segments:
                    # Проверяем пересечение временных интервалов
                    if (segment_start < diar_seg["end"] and segment_end > diar_seg["start"]):
                        # Вычисляем длину пересечения
                        overlap_start = max(segment_start, diar_seg["start"])
                        overlap_end = min(segment_end, diar_seg["end"])
                        overlap_duration = overlap_end - overlap_start
                        overlapping_speakers.append((diar_seg["speaker"], overlap_duration))
                
                # Выбираем говорящего с максимальным пересечением
                if overlapping_speakers:
                    # Сортируем по длине пересечения и берем первого
                    overlapping_speakers.sort(key=lambda x: x[1], reverse=True)
                    speaker = overlapping_speakers[0][0]
                else:
                    # Если нет пересечений, используем последнего известного говорящего или создаем нового
                    speaker = f"SPEAKER_{len(speakers) + 1}"
                
                segment["speaker"] = speaker
                speakers.add(speaker)
            
            speakers_list = sorted(list(speakers))
            
            logger.info(f"Диаризация завершена. Найдено говорящих: {len(speakers_list)}")
            
            return DiarizationResult(result.get("segments", []), speakers_list)
            
        except Exception as e:
            logger.error(f"Ошибка при диаризации с WhisperX + pyannote: {e}")
            raise
    
    def diarize_with_pyannote(self, file_path: str) -> DiarizationResult:
        """Диаризация с помощью pyannote.audio (резервный вариант)"""
        try:
            self._load_pyannote_pipeline()
            
            # Дополнительная проверка, что pipeline загружен
            if self.pyannote_pipeline is None:
                raise RuntimeError("Pipeline pyannote.audio не был загружен")
            
            logger.info(f"Выполнение диаризации с pyannote.audio: {file_path}")
            
            # Выполняем диаризацию
            diarization = self.pyannote_pipeline(file_path)
            
            # Проверяем результат диаризации
            if diarization is None:
                raise RuntimeError("Диаризация вернула None")
            
            # Преобразуем результаты в формат сегментов
            segments = []
            speakers = set()
            
            for segment, _, speaker in diarization.itertracks(yield_label=True):
                speakers.add(speaker)
                segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": speaker,
                    "text": ""  # Текст будет добавлен отдельно через Whisper
                })
            
            speakers_list = sorted(list(speakers))
            
            logger.info(f"Диаризация pyannote завершена. Найдено говорящих: {len(speakers_list)}")
            
            return DiarizationResult(segments, speakers_list)
            
        except Exception as e:
            logger.error(f"Ошибка при диаризации с pyannote.audio: {e}")
            raise
    
    def _convert_audio_format(self, input_path: str, output_format: str = "wav") -> str:
        """Конвертировать аудио файл в поддерживаемый формат"""
        try:
            import subprocess
            
            # Создаем путь для конвертированного файла
            input_dir = os.path.dirname(input_path)
            input_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(input_dir, f"{input_name}_converted.{output_format}")
            
            # Проверяем, не существует ли уже конвертированный файл
            if os.path.exists(output_path):
                logger.info(f"Конвертированный файл уже существует: {output_path}")
                return output_path
            
            logger.info(f"Конвертация {input_path} в {output_format} формат...")
            
            # Используем ffmpeg через subprocess для большей совместимости
            cmd = [
                'ffmpeg', '-i', input_path,
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ac', '1',               # Моно
                '-ar', '16000',           # 16kHz
                '-y',                     # Перезаписать если существует
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"Конвертация завершена: {output_path}")
                return output_path
            else:
                logger.error(f"Ошибка при конвертации: {result.stderr}")
                return input_path
            
        except Exception as e:
            logger.error(f"Ошибка при конвертации аудио: {e}")
            # Возвращаем исходный файл, если конвертация не удалась
            return input_path
    
    def _cleanup_converted_file(self, file_path: str, original_path: str):
        """Удалить временный конвертированный файл"""
        if file_path != original_path and "_converted." in file_path:
            try:
                os.remove(file_path)
                logger.info(f"Удален временный файл: {file_path}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")
    
    def _needs_conversion(self, file_path: str) -> bool:
        """Проверить, нужна ли конвертация файла"""
        file_ext = os.path.splitext(file_path)[1].lower()
        # Форматы, которые обычно не поддерживаются библиотеками диаризации
        unsupported_formats = ['.m4a', '.mp4', '.aac', '.m4p']
        return file_ext in unsupported_formats

    def diarize_file(self, file_path: str, language: str = "ru") -> Optional[DiarizationResult]:
        """Основной метод диаризации файла"""
        if not settings.enable_diarization:
            logger.info("Диаризация отключена в настройках")
            return None
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        
        logger.info(f"Начало диаризации файла: {file_path}")
        
        # Проверяем, нужна ли конвертация
        original_path = file_path
        converted_file = None
        
        if self._needs_conversion(file_path):
            logger.info(f"Файл {file_path} требует конвертации")
            converted_file = self._convert_audio_format(file_path)
            if converted_file != file_path:
                file_path = converted_file
                logger.info(f"Используем конвертированный файл: {file_path}")
        
        try:
            # Пробуем сначала WhisperX
            if WHISPERX_AVAILABLE:
                logger.info("Использование WhisperX для диаризации")
                result = self.diarize_with_whisperx(file_path, language)
                return result
            
            # Если WhisperX недоступен, пробуем pyannote
            elif PYANNOTE_AVAILABLE:
                logger.info("WhisperX недоступен, использование pyannote.audio")
                result = self.diarize_with_pyannote(file_path)
                return result
            
            else:
                logger.error("Ни одна библиотека диаризации не доступна")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при диаризации: {e}")
            
            # Пробуем резервный вариант
            if WHISPERX_AVAILABLE and PYANNOTE_AVAILABLE:
                try:
                    logger.info("Пробуем резервный вариант диаризации...")
                    result = self.diarize_with_pyannote(file_path)
                    return result
                except Exception as e2:
                    logger.error(f"Резервный вариант также не сработал: {e2}")
            
            return None
            
        finally:
            # Очищаем временный конвертированный файл
            if converted_file and converted_file != original_path:
                self._cleanup_converted_file(converted_file, original_path)
    
    def get_speakers_summary(self, result: DiarizationResult) -> str:
        """Получить краткую сводку о говорящих"""
        if not result or not result.speakers:
            return "Говорящие не определены"
        
        speakers_text = result.get_speakers_text()
        summary_lines = []
        
        summary_lines.append(f"Общее количество говорящих: {len(result.speakers)}")
        summary_lines.append("")
        
        for speaker in result.speakers:
            text = speakers_text.get(speaker, "")
            word_count = len(text.split()) if text else 0
            summary_lines.append(f"{speaker}: {word_count} слов")
        
        return "\n".join(summary_lines)


# Глобальный экземпляр сервиса
diarization_service = DiarizationService()
