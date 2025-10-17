"""
Сервис для анализа и обогащения данных диаризации
Определяет роли спикеров, паттерны взаимодействия, фазы встречи
"""

from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import re
from loguru import logger

from src.models.diarization_analysis import (
    DiarizationAnalysisResult,
    SpeakerContribution,
    SpeakerRole,
    InteractionPattern,
    MeetingPhase
)


class DiarizationAnalyzer:
    """Анализатор данных диаризации для извлечения инсайтов"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.min_word_count_for_analysis = 10  # Минимум слов для анализа спикера
    
    def analyze_speakers_contribution(
        self,
        diarization_data: Dict[str, Any],
        transcription: str
    ) -> Dict[str, SpeakerContribution]:
        """
        Анализировать вклад каждого спикера
        
        Args:
            diarization_data: Данные диаризации
            transcription: Текст транскрипции
            
        Returns:
            Словарь с вкладом каждого спикера
        """
        speakers = {}
        speakers_text = diarization_data.get('speakers_text', {})
        
        if not speakers_text:
            logger.warning("Нет данных о спикерах для анализа")
            return speakers
        
        # Подсчитываем общее количество слов
        total_words = len(transcription.split())
        
        for speaker_id, speaker_segments in speakers_text.items():
            # Объединяем все сегменты спикера
            speaker_text = ' '.join(speaker_segments) if isinstance(speaker_segments, list) else str(speaker_segments)
            
            word_count = len(speaker_text.split())
            
            # Пропускаем спикеров с минимальным вкладом
            if word_count < self.min_word_count_for_analysis:
                continue
            
            # Подсчет количества реплик (по количеству сегментов)
            turn_count = len(speaker_segments) if isinstance(speaker_segments, list) else 1
            
            # Примерная оценка времени говорения (5 слов в секунду - средняя скорость речи)
            speaking_time = word_count / 5.0
            
            # Средняя длительность реплики
            avg_turn_duration = speaking_time / turn_count if turn_count > 0 else 0
            
            # Процент от общего времени/слов
            speaking_percent = (word_count / total_words * 100) if total_words > 0 else 0
            
            contribution = SpeakerContribution(
                speaker_id=speaker_id,
                total_speaking_time=speaking_time,
                speaking_time_percent=speaking_percent,
                word_count=word_count,
                turn_count=turn_count,
                average_turn_duration=avg_turn_duration,
                interruptions=0,  # Будет вычислено в analyze_interaction_patterns
                interrupted_by=[],
                role=SpeakerRole.UNKNOWN  # Будет определено в identify_speaker_roles
            )
            
            speakers[speaker_id] = contribution
        
        logger.info(f"Проанализирован вклад {len(speakers)} спикеров")
        return speakers
    
    def identify_speaker_roles(
        self,
        speakers: Dict[str, SpeakerContribution],
        transcription: str
    ) -> Dict[str, SpeakerContribution]:
        """
        Определить роли спикеров на основе их поведения
        
        Args:
            speakers: Вклад спикеров
            transcription: Текст транскрипции
            
        Returns:
            Обновленный словарь спикеров с определенными ролями
        """
        if not speakers:
            return speakers
        
        # Сортируем спикеров по проценту говорения
        sorted_speakers = sorted(
            speakers.items(),
            key=lambda x: x[1].speaking_time_percent,
            reverse=True
        )
        
        # Ключевые слова для определения модератора
        moderator_keywords = [
            r'\bдавайте\s+начнем\b',
            r'\bпереходим\s+к\b',
            r'\bследующий\s+вопрос\b',
            r'\bкто\s+хочет\b',
            r'\bу\s+кого\s+есть\b',
            r'\bподведем\s+итог\b',
            r'\bзаканчиваем\b',
            r'\bспасибо\s+всем\b'
        ]
        
        # Ключевые слова для эксперта
        expert_keywords = [
            r'\bпо\s+моему\s+опыту\b',
            r'\bя\s+рекомендую\b',
            r'\bлучше\s+всего\b',
            r'\bправильный\s+подход\b',
            r'\bтехнически\b',
            r'\bархитектур\w+\b',
            r'\bоптимальн\w+\b'
        ]
        
        moderator_pattern = re.compile('|'.join(moderator_keywords), re.IGNORECASE)
        expert_pattern = re.compile('|'.join(expert_keywords), re.IGNORECASE)
        
        for i, (speaker_id, contribution) in enumerate(sorted_speakers):
            # Получаем текст спикера из транскрипции
            speaker_text_pattern = re.compile(
                rf'{re.escape(speaker_id)}:\s*([^\n]+)',
                re.IGNORECASE
            )
            speaker_matches = speaker_text_pattern.findall(transcription)
            speaker_full_text = ' '.join(speaker_matches)
            
            # Определяем роль
            if i == 0 and contribution.speaking_time_percent > 40:
                # Первый спикер с большим процентом - вероятно модератор или лектор
                if moderator_pattern.search(speaker_full_text):
                    contribution.role = SpeakerRole.MODERATOR
                else:
                    contribution.role = SpeakerRole.DOMINANT
            
            elif contribution.speaking_time_percent > 25:
                # Спикер с высоким процентом участия
                if expert_pattern.search(speaker_full_text):
                    contribution.role = SpeakerRole.EXPERT
                else:
                    contribution.role = SpeakerRole.DOMINANT
            
            elif contribution.speaking_time_percent < 5:
                # Спикер с низким участием
                contribution.role = SpeakerRole.OBSERVER
            
            else:
                # Обычный участник
                contribution.role = SpeakerRole.PARTICIPANT
            
            speakers[speaker_id] = contribution
        
        logger.info(f"Определены роли для {len(speakers)} спикеров")
        return speakers
    
    def analyze_interaction_patterns(
        self,
        diarization_data: Dict[str, Any],
        speakers: Dict[str, SpeakerContribution]
    ) -> List[InteractionPattern]:
        """
        Анализировать паттерны взаимодействия между спикерами
        
        Args:
            diarization_data: Данные диаризации
            speakers: Вклад спикеров
            
        Returns:
            Список паттернов взаимодействия
        """
        interactions = []
        
        # Получаем форматированную транскрипцию
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        
        if not formatted_transcript:
            logger.warning("Нет форматированной транскрипции для анализа взаимодействий")
            return interactions
        
        # Разбираем транскрипцию на реплики
        lines = formatted_transcript.split('\n')
        speaker_turns = []
        
        for line in lines:
            match = re.match(r'^(Спикер \d+|Speaker \d+):\s*(.+)$', line.strip())
            if match:
                speaker = match.group(1)
                text = match.group(2)
                speaker_turns.append((speaker, text))
        
        # Анализируем последовательные обмены репликами
        interaction_counts = defaultdict(int)
        
        for i in range(len(speaker_turns) - 1):
            current_speaker = speaker_turns[i][0]
            next_speaker = speaker_turns[i + 1][0]
            
            if current_speaker != next_speaker:
                # Создаем ключ для пары спикеров (сортируем, чтобы A-B == B-A)
                pair = tuple(sorted([current_speaker, next_speaker]))
                interaction_counts[pair] += 1
        
        # Создаем объекты InteractionPattern
        for (speaker_a, speaker_b), exchanges in interaction_counts.items():
            # Вычисляем оценку интенсивности (нормализуем по количеству реплик)
            total_turns = sum(s.turn_count for s in speakers.values())
            interaction_score = min(exchanges / (total_turns * 0.1), 1.0) if total_turns > 0 else 0
            
            pattern = InteractionPattern(
                speaker_a=speaker_a,
                speaker_b=speaker_b,
                turn_exchanges=exchanges,
                avg_response_time=0,  # Требует временных меток
                interaction_score=interaction_score,
                topics_discussed=[]  # Требует анализа содержания
            )
            
            interactions.append(pattern)
        
        # Сортируем по интенсивности взаимодействия
        interactions.sort(key=lambda x: x.interaction_score, reverse=True)
        
        logger.info(f"Найдено {len(interactions)} паттернов взаимодействия")
        return interactions
    
    def segment_by_time(
        self,
        diarization_data: Dict[str, Any],
        speakers: Dict[str, SpeakerContribution],
        segment_duration: float = 300.0  # 5 минут по умолчанию
    ) -> List[MeetingPhase]:
        """
        Разделить встречу на временные фазы
        
        Args:
            diarization_data: Данные диаризации
            speakers: Вклад спикеров
            segment_duration: Длительность сегмента в секундах
            
        Returns:
            Список фаз встречи
        """
        phases = []
        
        # Получаем общую длительность
        total_duration = sum(s.total_speaking_time for s in speakers.values())
        
        if total_duration < segment_duration:
            # Встреча короткая - одна фаза
            dominant_speaker = max(speakers.items(), key=lambda x: x[1].speaking_time_percent)[0]
            
            phase = MeetingPhase(
                phase_id=1,
                start_time=0,
                end_time=total_duration,
                duration=total_duration,
                dominant_speaker=dominant_speaker,
                participants=list(speakers.keys()),
                phase_type="discussion"
            )
            phases.append(phase)
        else:
            # Делим на сегменты
            num_segments = int(total_duration // segment_duration) + 1
            
            for i in range(num_segments):
                start = i * segment_duration
                end = min((i + 1) * segment_duration, total_duration)
                
                phase = MeetingPhase(
                    phase_id=i + 1,
                    start_time=start,
                    end_time=end,
                    duration=end - start,
                    dominant_speaker=None,  # Требует детального анализа временных меток
                    participants=list(speakers.keys()),
                    phase_type="discussion"
                )
                phases.append(phase)
        
        logger.info(f"Встреча разделена на {len(phases)} фаз")
        return phases
    
    def detect_meeting_type(
        self,
        speakers: Dict[str, SpeakerContribution],
        transcription: str
    ) -> str:
        """
        Определить тип встречи
        
        Args:
            speakers: Вклад спикеров
            transcription: Текст транскрипции
            
        Returns:
            Тип встречи
        """
        # Если один спикер доминирует (>60%), вероятно презентация
        if speakers:
            max_contribution = max(s.speaking_time_percent for s in speakers.values())
            if max_contribution > 60:
                return "presentation"
        
        # Проверяем технические термины
        tech_keywords = [
            r'\bAPI\b', r'\bбаз[аы]\s+данных\b', r'\bсервер\b',
            r'\bкод\b', r'\bархитектур\w+\b', r'\bалгоритм\b',
            r'\bфункци[яи]\b', r'\bкласс\b', r'\bметод\b'
        ]
        tech_pattern = re.compile('|'.join(tech_keywords), re.IGNORECASE)
        tech_matches = len(tech_pattern.findall(transcription))
        
        if tech_matches > 10:
            return "technical"
        
        # Проверяем бизнес-термины
        business_keywords = [
            r'\bбюджет\b', r'\bприбыл[ьи]\b', r'\bконтракт\b',
            r'\bсделк[аи]\b', r'\bклиент\w+\b', r'\bпродаж\w+\b',
            r'\bмаркетинг\b', r'\bстратеги[яи]\b'
        ]
        business_pattern = re.compile('|'.join(business_keywords), re.IGNORECASE)
        business_matches = len(business_pattern.findall(transcription))
        
        if business_matches > 10:
            return "business"
        
        # Проверяем на брейнш��орм (много вопросов, идей)
        question_pattern = re.compile(r'[?？]')
        questions = len(question_pattern.findall(transcription))
        
        idea_keywords = [r'\bидея\b', r'\bпредлага[ю|е]м\b', r'\bможно\b', r'\bа\s+если\b']
        idea_pattern = re.compile('|'.join(idea_keywords), re.IGNORECASE)
        ideas = len(idea_pattern.findall(transcription))
        
        if questions > 20 or ideas > 15:
            return "brainstorm"
        
        # По умолчанию - обычное обсуждение
        return "general"
    
    def calculate_participation_balance(
        self,
        speakers: Dict[str, SpeakerContribution]
    ) -> float:
        """
        Вычислить баланс участия (насколько равномерно распределено участие)
        
        Args:
            speakers: Вклад спикеров
            
        Returns:
            Оценка баланса от 0 (очень несбалансированно) до 1 (идеально)
        """
        if not speakers or len(speakers) < 2:
            return 1.0
        
        # Вычисляем стандартное отклонение процентов участия
        percentages = [s.speaking_time_percent for s in speakers.values()]
        mean = sum(percentages) / len(percentages)
        variance = sum((p - mean) ** 2 for p in percentages) / len(percentages)
        std_dev = variance ** 0.5
        
        # Нормализуем: идеальное std_dev = 0, максимальное = 50 (один говорит 100%, остальные 0%)
        balance = 1.0 - min(std_dev / 50.0, 1.0)
        
        return round(balance, 2)
    
    def enrich_diarization_data(
        self,
        diarization_data: Dict[str, Any],
        transcription: str
    ) -> DiarizationAnalysisResult:
        """
        Выполнить полный анализ и обогащение данных диаризации
        
        Args:
            diarization_data: Исходные данные диаризации
            transcription: Текст транскрипции
            
        Returns:
            Полный результат анализа
        """
        logger.info("Начало обогащения данных диаризации")
        
        # Шаг 1: Анализ вклада спикеров
        speakers = self.analyze_speakers_contribution(diarization_data, transcription)
        
        if not speakers:
            logger.warning("Не удалось проанализировать спикеров")
            return self._create_empty_result()
        
        # Шаг 2: Определение ролей
        speakers = self.identify_speaker_roles(speakers, transcription)
        
        # Шаг 3: Анализ взаимодействий
        interactions = self.analyze_interaction_patterns(diarization_data, speakers)
        
        # Шаг 4: Разделение на фазы
        phases = self.segment_by_time(diarization_data, speakers)
        
        # Шаг 5: Определение типа встречи
        meeting_type = self.detect_meeting_type(speakers, transcription)
        
        # Шаг 6: Вычисление метрик
        total_duration = sum(s.total_speaking_time for s in speakers.values())
        dominant_speaker = max(speakers.items(), key=lambda x: x[1].speaking_time_percent)[0] if speakers else None
        
        # Топ-3 активных взаимодействия
        most_active = [
            (i.speaker_a, i.speaker_b)
            for i in interactions[:3]
        ]
        
        # Баланс участия
        participation_balance = self.calculate_participation_balance(speakers)
        
        # Определение уровня энергии (по количеству реплик и их длительности)
        avg_turn_duration = sum(s.average_turn_duration for s in speakers.values()) / len(speakers) if speakers else 0
        total_turns = sum(s.turn_count for s in speakers.values())
        
        if avg_turn_duration < 5 and total_turns > 50:
            energy_level = "high"
        elif avg_turn_duration > 15 or total_turns < 20:
            energy_level = "low"
        else:
            energy_level = "medium"
        
        result = DiarizationAnalysisResult(
            speakers=speakers,
            interactions=interactions,
            phases=phases,
            topic_segments=[],  # Требует более глубокого анализа содержания
            total_duration=total_duration,
            total_speakers=len(speakers),
            dominant_speaker_id=dominant_speaker,
            most_active_interactions=most_active,
            meeting_type=meeting_type,
            energy_level=energy_level,
            participation_balance=participation_balance
        )
        
        logger.info(f"Анализ диаризации завершен: {len(speakers)} спикеров, тип: {meeting_type}")
        
        return result
    
    def _create_empty_result(self) -> DiarizationAnalysisResult:
        """Создать пустой результат для случаев ошибки"""
        return DiarizationAnalysisResult(
            speakers={},
            interactions=[],
            phases=[],
            topic_segments=[],
            total_duration=0,
            total_speakers=0,
            dominant_speaker_id=None,
            most_active_interactions=[],
            meeting_type="general",
            energy_level="medium",
            participation_balance=1.0
        )


# Глобальный экземпляр анализатора
diarization_analyzer = DiarizationAnalyzer()

