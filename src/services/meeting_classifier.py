"""
Классификатор типа встречи для выбора специализированных промптов
"""

import re
from typing import Dict, Any, Tuple, Optional, TYPE_CHECKING
from loguru import logger

# Импорт для избежания циркулярных зависимостей
if TYPE_CHECKING:
    from src.models.diarization_analysis import DiarizationAnalysisResult


class MeetingClassifier:
    """Классификатор для определения типа встречи"""
    
    # Ключевые слова для разных типов встреч
    TECHNICAL_KEYWORDS = [
        r'\bAPI\b', r'\bбаз[аы]\s+данных\b', r'\bсервер\w*\b',
        r'\bкод\w*\b', r'\bархитектур\w+\b', r'\bалгоритм\w*\b',
        r'\bфункци[яи]\w*\b', r'\bкласс\w*\b', r'\bметод\w*\b',
        r'\bрепозитори[йи]\b', r'\bкоммит\w*\b', r'\bгит\b',
        r'\bфронтенд\b', r'\bбэкенд\b', r'\bдевопс\b', r'\bCI\/CD\b',
        r'\bтест\w*\b', r'\bбаг\w*\b', r'\bдебаг\w*\b',
        r'\bфреймворк\w*\b', r'\bбиблиотек\w*\b', r'\bпакет\w*\b',
        r'\bспринт\w*\b', r'\bдеплой\w*\b', r'\bрелиз\w*\b',
        r'\bмердж\w*\b', r'\bпулл\s+реквест\b', r'\bлог\w*\b',
        r'\bмониторинг\w*\b'
    ]
    
    BUSINESS_KEYWORDS = [
        r'\bбюджет\w*\b', r'\bприбыл[ьи]\w*\b', r'\bконтракт\w*\b',
        r'\bсделк[аи]\w*\b', r'\bклиент\w+\b', r'\bпродаж\w+\b',
        r'\bмаркетинг\w*\b', r'\bстратеги[яи]\w*\b', r'\bфинанс\w+\b',
        r'\bинвестиц\w+\b', r'\bбизнес\b', r'\bдоход\w*\b',
        r'\bрасход\w*\b', r'\bплан\s+продаж\b', r'\bROI\b',
        r'\bконкурент\w+\b', r'\bрын\w*\b', r'\bдоговор\w*\b',
        r'\bсмет[аы]\b', r'\bаккаунтинг\b', r'\bтендер\w*\b',
        r'\bкоммерческ\w+\s+предложен\w+\b', r'\bКП\b'
    ]
    
    EDUCATIONAL_KEYWORDS = [
        r'\bобъясн\w+\b', r'\bпонятн\w+\b', r'\bизуч\w+\b',
        r'\bобуч\w+\b', r'\bучеб\w+\b', r'\bкурс\w*\b',
        r'\bлекци[яи]\b', r'\bсеминар\b', r'\bтренинг\b',
        r'\bзанят\w+\b', r'\bматериал\w*\b', r'\bтеор\w+\b',
        r'\bпракти\w+\b', r'\bзадани[ея]\b', r'\bдомашн\w+\b'
    ]
    
    BRAINSTORM_KEYWORDS = [
        r'\bидея\w*\b', r'\bпредлага[ю|е]м\b', r'\bможно\b',
        r'\bа\s+если\b', r'\bвариант\w*\b', r'\bопци[яи]\b',
        r'\bкреатив\w+\b', r'\bинновац\w+\b', r'\bновизн\w*\b',
        r'\bпредложен\w+\b', r'\bпридум\w+\b', r'\bгенерир\w+\b'
    ]
    
    STATUS_KEYWORDS = [
        r'\bстатус\b', r'\bпрогресс\b', r'\bвыполнен\w+\b',
        r'\bметрик\w*\b', r'\bKPI\b', r'\bпоказател\w+\b',
        r'\bдостижен\w+\b', r'\bрезультат\w*\b', r'\bотчет\w*\b',
        r'\bитог\w*\b', r'\bдостигнут\w*\b', r'\bзавершен\w+\b'
    ]
    
    def __init__(self):
        """Инициализация классификатора"""
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Компилировать regex паттерны для эффективности"""
        self.technical_pattern = re.compile(
            '|'.join(self.TECHNICAL_KEYWORDS), 
            re.IGNORECASE | re.UNICODE
        )
        self.business_pattern = re.compile(
            '|'.join(self.BUSINESS_KEYWORDS), 
            re.IGNORECASE | re.UNICODE
        )
        self.educational_pattern = re.compile(
            '|'.join(self.EDUCATIONAL_KEYWORDS), 
            re.IGNORECASE | re.UNICODE
        )
        self.brainstorm_pattern = re.compile(
            '|'.join(self.BRAINSTORM_KEYWORDS), 
            re.IGNORECASE | re.UNICODE
        )
        self.status_pattern = re.compile(
            '|'.join(self.STATUS_KEYWORDS), 
            re.IGNORECASE | re.UNICODE
        )
    
    def classify(
        self,
        transcription: str,
        diarization_analysis: Optional[Any] = None
    ) -> Tuple[str, Dict[str, float]]:
        """
        Классифицировать тип встречи
        
        Args:
            transcription: Текст транскрипции
            diarization_analysis: Результат анализа диаризации (объект или словарь)
            
        Returns:
            (тип встречи, словарь с оценками для каждого типа)
        """
        # Подсчитываем совпадения для каждого типа
        scores = {
            'technical': self._count_matches(self.technical_pattern, transcription),
            'business': self._count_matches(self.business_pattern, transcription),
            'educational': self._count_matches(self.educational_pattern, transcription),
            'brainstorm': self._count_matches(self.brainstorm_pattern, transcription),
            'status': self._count_matches(self.status_pattern, transcription)
        }
        
        # Нормализуем оценки (делим на длину транскрипции в словах)
        word_count = len(transcription.split())
        normalized_scores = {
            k: (v / word_count * 100) if word_count > 0 else 0
            for k, v in scores.items()
        }
        
        # Дополнительные эвристики на основе диаризации
        if diarization_analysis:
            try:
                # Получаем данные в зависимости от типа (объект или словарь)
                if isinstance(diarization_analysis, dict):
                    statistics = diarization_analysis.get('statistics', {})
                    total_speakers = statistics.get('total_speakers', 0)
                    speakers = diarization_analysis.get('speakers', {})
                    participation_balance = statistics.get('participation_balance', 0)
                else:
                    # Это объект DiarizationAnalysisResult
                    total_speakers = diarization_analysis.total_speakers
                    speakers = diarization_analysis.speakers
                    participation_balance = diarization_analysis.participation_balance
                
                # Если один спикер доминирует (>60%), вероятно презентация или обучение
                if total_speakers > 0 and speakers:
                    if isinstance(speakers, dict):
                        # Если speakers это словарь
                        max_contribution = max(
                            (s.get('speaking_time_percent', 0) if isinstance(s, dict) 
                             else s.speaking_time_percent)
                            for s in speakers.values()
                        )
                        
                        if max_contribution > 60:
                            normalized_scores['educational'] += 2.0
                
                # Если много участников с равным вкладом, вероятно брейнш��орм
                if participation_balance > 0.7:
                    normalized_scores['brainstorm'] += 1.5
            except (AttributeError, KeyError, ValueError) as e:
                logger.warning(f"Ошибка при использовании diarization_analysis: {e}")
        
        # Специальные проверки
        question_count = len(re.findall(r'[?？]', transcription))
        if question_count > 20:
            normalized_scores['brainstorm'] += 1.0
        
        # Определяем тип с наибольшей оценкой
        meeting_type = max(normalized_scores, key=normalized_scores.get)
        max_score = normalized_scores[meeting_type]
        
        # Если все оценки низкие, возвращаем "general"
        if max_score < 0.5:
            meeting_type = "general"
        
        logger.info(
            f"Классификация встречи: {meeting_type} "
            f"(оценки: {', '.join(f'{k}={v:.2f}' for k, v in normalized_scores.items())})"
        )
        
        return meeting_type, normalized_scores
    
    def _count_matches(self, pattern: re.Pattern, text: str) -> int:
        """Подсчитать количество совпадений паттерна в тексте"""
        return len(pattern.findall(text))
    
    def get_meeting_description(self, meeting_type: str) -> str:
        """
        Получить описание типа встречи
        
        Args:
            meeting_type: Тип встречи
            
        Returns:
            Текстовое описание типа
        """
        descriptions = {
            'technical': 'Техническое совещание (разработка, архитектура, code review)',
            'business': 'Деловые переговоры (продажи, контракты, финансы)',
            'educational': 'Образовательная встреча (обучение, презентация, лекция)',
            'brainstorm': 'Брейнш��орм (генерация идей, обсуждение вариантов)',
            'status': 'Отчетная встреча (статусы, метрики, прогресс)',
            'general': 'Общая встреча (смешанная тематика)'
        }
        
        return descriptions.get(meeting_type, 'Общая встреча')


# Глобальный экземпляр классификатора
meeting_classifier = MeetingClassifier()

