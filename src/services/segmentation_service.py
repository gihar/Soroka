"""
Сервис для сегментации длинных транскрипций для Chain-of-Thought обработки
"""

import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from loguru import logger

from config import settings


@dataclass
class TranscriptionSegment:
    """Сегмент транскрипции для обработки"""
    segment_id: int
    start_time: float  # В секундах
    end_time: float
    text: str
    speakers: List[str]  # Список спикеров в сегменте
    word_count: int
    has_diarization: bool = False
    formatted_text: Optional[str] = None  # Форматированный текст с метками спикеров


class TranscriptionSegmentationService:
    """Сервис для сегментации транскрипций"""
    
    def __init__(self):
        """Инициализация сервиса сегментации"""
        self.min_segment_words = 100  # Минимум слов в сегменте
        self.max_segment_words = 500  # Максимум слов в сегменте
        self.target_segment_minutes = 5  # Целевая длительность сегмента в минутах
        self.words_per_minute = 150  # Средняя скорость речи
    
    def should_use_segmentation(
        self,
        transcription: str,
        estimated_duration_minutes: Optional[float] = None
    ) -> bool:
        """
        Определить, нужна ли сегментация для данной транскрипции
        
        Args:
            transcription: Текст транскрипции
            estimated_duration_minutes: Примерная длительность встречи в минутах
            
        Returns:
            True если нужна сегментация
        """
        word_count = len(transcription.split())
        threshold = settings.chain_of_thought_threshold_minutes
        
        # Если передана длительность, используем её
        if estimated_duration_minutes:
            return estimated_duration_minutes > threshold
        
        # Иначе оцениваем по количеству слов
        # threshold минут * 150 слов/мин
        estimated_minutes = word_count / self.words_per_minute
        return estimated_minutes > threshold
    
    def segment_by_time(
        self,
        transcription: str,
        diarization_data: Optional[Dict[str, Any]] = None,
        target_minutes: int = 5,
        speaker_mapping: Optional[Dict[str, str]] = None
    ) -> List[TranscriptionSegment]:
        """
        Разделить транскрипцию на временные сегменты
        
        Args:
            transcription: Текст транскрипции
            diarization_data: Данные диаризации (опционально)
            target_minutes: Целевая длительность сегмента
            
        Returns:
            Список сегментов
        """
        target_words = target_minutes * self.words_per_minute
        words = transcription.split()
        total_words = len(words)
        
        segments = []
        segment_id = 0
        start_idx = 0
        
        while start_idx < total_words:
            # Определяем размер сегмента
            end_idx = min(start_idx + target_words, total_words)
            
            # Пытаемся найти естественную границу (конец предложения)
            if end_idx < total_words:
                # Берем немного больше слов для поиска границы
                search_end = min(end_idx + 100, total_words)
                search_segment = words[start_idx:search_end]
                
                # Ищем конец предложения в диапазоне ±50 слов от целевой позиции
                target_word_idx = end_idx - start_idx
                search_start = max(target_word_idx - 50, 0)
                search_end_range = min(target_word_idx + 50, len(search_segment))
                
                best_boundary = None
                min_distance = float('inf')
                
                # Ищем точки, вопросы или восклицательные знаки
                for i in range(search_start, search_end_range):
                    word = search_segment[i]
                    if word.endswith(('.', '!', '?')):
                        distance = abs(i - target_word_idx)
                        if distance < min_distance:
                            min_distance = distance
                            best_boundary = i + 1  # +1 чтобы включить слово с точкой
                
                # Если нашли подходящую границу, используем её
                if best_boundary is not None:
                    end_idx = start_idx + best_boundary
            
            # Извлекаем текст сегмента
            segment_words = words[start_idx:end_idx]
            segment_text = ' '.join(segment_words)
            
            # Оценка времени (примерная)
            start_time = (start_idx / self.words_per_minute) * 60
            end_time = (end_idx / self.words_per_minute) * 60
            
            # Извлекаем спикеров если есть диаризация
            speakers, formatted_text = self._extract_speakers_from_segment(
                segment_text, diarization_data, speaker_mapping, start_time, end_time
            )
            
            segment = TranscriptionSegment(
                segment_id=segment_id,
                start_time=start_time,
                end_time=end_time,
                text=segment_text,
                speakers=speakers,
                word_count=len(segment_words),
                has_diarization=bool(diarization_data),
                formatted_text=formatted_text
            )
            
            segments.append(segment)
            segment_id += 1
            start_idx = end_idx
        
        logger.info(
            f"Транскрипция разделена на {len(segments)} сегментов "
            f"(~{target_minutes} мин каждый)"
        )
        
        return segments
    
    def segment_by_speakers(
        self,
        diarization_data: Dict[str, Any],
        transcription: str,
        max_segment_duration: float = 600.0,  # 10 минут
        speaker_mapping: Optional[Dict[str, str]] = None
    ) -> List[TranscriptionSegment]:
        """
        Разделить транскрипцию по изменениям доминирующего спикера
        
        Args:
            diarization_data: Данные диаризации
            transcription: Текст транскрипции
            max_segment_duration: Максимальная длительность сегмента в секундах
            
        Returns:
            Список сегментов
        """
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        
        if not formatted_transcript:
            # Если нет форматированной транскрипции, используем временную сегментацию
            return self.segment_by_time(transcription, diarization_data)
        
        # Разбираем форматированную транскрипцию на реплики
        lines = formatted_transcript.split('\n')
        speaker_turns = []
        
        for line in lines:
            match = re.match(r'^(Спикер \d+|Speaker \d+):\s*(.+)$', line.strip())
            if match:
                speaker = match.group(1)
                text = match.group(2)
                speaker_turns.append((speaker, text))
        
        if not speaker_turns:
            return self.segment_by_time(transcription, diarization_data)
        
        # Группируем по доминирующему спикеру
        segments = []
        segment_id = 0
        current_speaker = None
        current_texts = []
        current_speakers_set = set()
        start_idx = 0
        
        for idx, (speaker, text) in enumerate(speaker_turns):
            # Если спикер изменился или достигли лимита
            words_so_far = sum(len(t.split()) for t in current_texts)
            
            if current_speaker and (
                speaker != current_speaker or 
                words_so_far > self.max_segment_words
            ):
                # Создаем сегмент
                segment_text = ' '.join(current_texts)
                formatted_segment = '\n'.join([
                    f"{s}: {t}" for s, t in speaker_turns[start_idx:idx]
                ])
                
                # Оценка времени
                start_time = (start_idx / len(speaker_turns)) * (len(transcription.split()) / self.words_per_minute) * 60
                end_time = (idx / len(speaker_turns)) * (len(transcription.split()) / self.words_per_minute) * 60
                
                # Применяем маппинг к спикерам если есть
                speakers_list = list(current_speakers_set)
                if speaker_mapping:
                    speakers_list = [speaker_mapping.get(s, s) for s in speakers_list]
                
                segment = TranscriptionSegment(
                    segment_id=segment_id,
                    start_time=start_time,
                    end_time=end_time,
                    text=segment_text,
                    speakers=speakers_list,
                    word_count=len(segment_text.split()),
                    has_diarization=True,
                    formatted_text=formatted_segment
                )
                
                segments.append(segment)
                segment_id += 1
                
                # Сброс
                current_texts = []
                current_speakers_set = set()
                start_idx = idx
            
            current_speaker = speaker
            current_texts.append(text)
            current_speakers_set.add(speaker)
        
        # Добавляем последний сегмент
        if current_texts:
            segment_text = ' '.join(current_texts)
            formatted_segment = '\n'.join([
                f"{s}: {t}" for s, t in speaker_turns[start_idx:]
            ])
            
            start_time = (start_idx / len(speaker_turns)) * (len(transcription.split()) / self.words_per_minute) * 60
            end_time = len(transcription.split()) / self.words_per_minute * 60
            
            # Применяем маппинг к спикерам если есть
            speakers_list = list(current_speakers_set)
            if speaker_mapping:
                speakers_list = [speaker_mapping.get(s, s) for s in speakers_list]
            
            segment = TranscriptionSegment(
                segment_id=segment_id,
                start_time=start_time,
                end_time=end_time,
                text=segment_text,
                speakers=speakers_list,
                word_count=len(segment_text.split()),
                has_diarization=True,
                formatted_text=formatted_segment
            )
            
            segments.append(segment)
        
        logger.info(
            f"Транскрипция разделена на {len(segments)} сегментов "
            f"по изменениям спикеров"
        )
        
        return segments
    
    def _extract_speakers_from_segment(
        self,
        segment_text: str,
        diarization_data: Optional[Dict[str, Any]],
        speaker_mapping: Optional[Dict[str, str]] = None,
        segment_start_time: float = 0,
        segment_end_time: float = 0
    ) -> Tuple[List[str], Optional[str]]:
        """
        Извлечь список спикеров из сегмента
        
        Args:
            segment_text: Текст сегмента
            diarization_data: Данные диаризации
            speaker_mapping: Маппинг спикеров на имена
            segment_start_time: Время начала сегмента
            segment_end_time: Время окончания сегмента
            
        Returns:
            (список спикеров, форматированный текст)
        """
        if not diarization_data:
            return [], None
        
        speakers = set()
        formatted_lines = []
        
        # Используем временные метки из segments
        diarization_segments = diarization_data.get('segments', [])
        if diarization_segments and segment_start_time < segment_end_time:
            for seg in diarization_segments:
                seg_start = seg.get('start', 0)
                seg_end = seg.get('end', 0)
                # Проверяем пересечение временных интервалов
                if seg_start < segment_end_time and seg_end > segment_start_time:
                    speaker = seg.get('speaker', '')
                    text = seg.get('text', '')
                    if speaker:
                        speakers.add(speaker)
                        if text:
                            formatted_lines.append(f"{speaker}: {text}")
        
        # Если нет segments с временными метками, пробуем старый метод
        if not speakers:
            formatted_transcript = diarization_data.get('formatted_transcript', '')
            if formatted_transcript:
                # Разбираем форматированную транскрипцию построчно
                for line in formatted_transcript.split('\n'):
                    match = re.match(r'^(Спикер \d+|Speaker \d+|SPEAKER_\d+):\s*(.+)$', line.strip())
                    if match:
                        speaker = match.group(1)
                        text = match.group(2)
                        # Если часть текста содержится в сегменте
                        if text[:50] in segment_text or segment_text[:50] in text:
                            speakers.add(speaker)
                            formatted_lines.append(line.strip())
        
        # Применяем маппинг к спикерам если есть
        speakers_list = list(speakers)
        if speaker_mapping:
            speakers_list = [speaker_mapping.get(s, s) for s in speakers_list]
        
        # Формируем финальный форматированный текст
        formatted_text = '\n'.join(formatted_lines) if formatted_lines else None
        
        return speakers_list, formatted_text
    
    def create_segment_summary(self, segment: TranscriptionSegment) -> str:
        """
        Создать краткое описание сегмента для логов
        
        Args:
            segment: Сегмент транскрипции
            
        Returns:
            Текстовое описание
        """
        duration_min = (segment.end_time - segment.start_time) / 60
        speakers_str = ', '.join(segment.speakers) if segment.speakers else 'нет данных'
        
        return (
            f"Сегмент {segment.segment_id + 1}: "
            f"{duration_min:.1f} мин, "
            f"{segment.word_count} слов, "
            f"спикеры: {speakers_str}"
        )


# Глобальный экземпляр сервиса
segmentation_service = TranscriptionSegmentationService()

