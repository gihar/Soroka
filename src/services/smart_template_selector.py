"""
ML-based классификатор шаблонов на основе embeddings
"""

import re
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger

from src.models.template import Template

# Ключевые слова категорий (бывший meeting_classifier — внутренний шов подсказки шаблонов)
_CATEGORY_KEYWORDS = {
    'technical': [
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
    ],
    'business': [
        r'\bбюджет\w*\b', r'\bприбыл[ьи]\w*\b', r'\bконтракт\w*\b',
        r'\bсделк[аи]\w*\b', r'\bклиент\w+\b', r'\bпродаж\w+\b',
        r'\bмаркетинг\w*\b', r'\bстратеги[яи]\w*\b', r'\bфинанс\w+\b',
        r'\bинвестиц\w+\b', r'\bбизнес\b', r'\bдоход\w*\b',
        r'\bрасход\w*\b', r'\bплан\s+продаж\b', r'\bROI\b',
        r'\bконкурент\w+\b', r'\bрын\w*\b', r'\bдоговор\w*\b',
        r'\bсмет[аы]\b', r'\bаккаунтинг\b', r'\bтендер\w*\b',
        r'\bкоммерческ\w+\s+предложен\w+\b', r'\bКП\b'
    ],
    'educational': [
        r'\bобъясн\w+\b', r'\bпонятн\w+\b', r'\bизуч\w+\b',
        r'\bобуч\w+\b', r'\bучеб\w+\b', r'\bкурс\w*\b',
        r'\bлекци[яи]\b', r'\bсеминар\b', r'\bтренинг\b',
        r'\bзанят\w+\b', r'\bматериал\w*\b', r'\bтеор\w+\b',
        r'\bпракти\w+\b', r'\bзадани[ея]\b', r'\bдомашн\w+\b'
    ],
    'brainstorm': [
        r'\bидея\w*\b', r'\bпредлага[ю|е]м\b', r'\bможно\b',
        r'\bа\s+если\b', r'\bвариант\w*\b', r'\bопци[яи]\b',
        r'\bкреатив\w+\b', r'\bинновац\w+\b', r'\bновизн\w*\b',
        r'\bпредложен\w+\b', r'\bпридум\w+\b', r'\bгенерир\w+\b'
    ],
    'status': [
        r'\bстатус\b', r'\bпрогресс\b', r'\bвыполнен\w+\b',
        r'\bметрик\w*\b', r'\bKPI\b', r'\bпоказател\w+\b',
        r'\bдостижен\w+\b', r'\bрезультат\w*\b', r'\bотчет\w*\b',
        r'\bитог\w*\b', r'\bдостигнут\w*\b', r'\bзавершен\w+\b'
    ],
    'management': [
        r'\bпоручени\w+\b', r'\bсрок\w*\b', r'\bответственн\w+\b',
        r'\bисполнен\w+\b', r'\bисполнител\w+\b', r'\bконтрол\w+\b',
        r'\bдиректив\w*\b', r'\bпротокол\w*\s+поручени\w+\b'
    ],
}

_CATEGORY_PATTERNS = {
    name: re.compile('|'.join(words), re.IGNORECASE | re.UNICODE)
    for name, words in _CATEGORY_KEYWORDS.items()
}

# Маппинг категорий к ключевым словам шаблонов (aligned with 7-template set).
# Каждая категория классификатора (_CATEGORY_KEYWORDS) обязана иметь ключи,
# иначе категорийный boost для неё никогда не сработает.
MEETING_TYPE_TO_CATEGORIES = {
    'technical': ['техническое', 'code review', 'разработка', 'архитектура', 'api'],
    'business': ['стандартный протокол', 'резюме'],
    'educational': ['лекция', 'обучение', 'презентация', 'тренинг'],
    'brainstorm': ['стандартный протокол', 'резюме'],
    'status': ['статус', 'стендап', 'ретроспектива', 'дейли', 'ежедневн', 'daily'],
    'management': ['поручение', 'задача', 'срок', 'ответственный', 'од'],
}


class SmartTemplateSelector:
    """Умный выбор шаблона на основе ML"""
    
    def __init__(self):
        self.model = None
        self.template_embeddings: Dict[int, np.ndarray] = {}
        self._initialized = False
    
    def _score_categories(self, transcription: str) -> Tuple[str, Dict[str, float]]:
        """Оценить категории шаблонов по ключевым словам транскрипции.

        Возвращает (топ-категория или 'general', нормированные оценки).
        Это подбор категории шаблона, а не «тип встречи» — тип встречи
        определяет LLM (см. CONTEXT.md).
        """
        word_count = len(transcription.split())
        scores = {
            name: (len(pattern.findall(transcription)) / word_count * 100) if word_count > 0 else 0.0
            for name, pattern in _CATEGORY_PATTERNS.items()
        }

        question_count = len(re.findall(r'[?？]', transcription))
        if question_count > 20:
            scores['brainstorm'] += 1.0

        top_category = max(scores, key=scores.get)
        if scores[top_category] < 0.5:
            top_category = 'general'

        logger.info(
            f"Категория шаблона: {top_category} "
            f"(оценки: {', '.join(f'{k}={v:.2f}' for k, v in scores.items())})"
        )
        return top_category, scores

    def _lazy_init(self):
        """Ленивая инициализация модели"""
        if self._initialized:
            return
        
        try:
            # Используем легковесную multilingual модель
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self._initialized = True
            logger.info("Smart template selector инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации ML модели: {e}")
            self._initialized = False
    
    async def index_templates(self, templates: List[Template]):
        """
        Создать embeddings для всех шаблонов
        
        Args:
            templates: Список шаблонов для индексации
        """
        self._lazy_init()
        if not self._initialized:
            return
        
        logger.info(f"Индексация {len(templates)} шаблонов...")
        
        for template in templates:
            try:
                # Создаем текстовое представление шаблона
                text = self._create_template_text(template)
                
                # Генерируем embedding
                embedding = self.model.encode(text, convert_to_numpy=True)
                self.template_embeddings[template.id] = embedding
                
            except Exception as e:
                logger.error(f"Ошибка индексации шаблона {template.id}: {e}")
        
        logger.info(f"Проиндексировано {len(self.template_embeddings)} шаблонов")
    
    def _create_template_text(self, template: Template) -> str:
        """Создать текстовое представление шаблона для embedding"""
        parts = [
            template.name,
            template.description or "",
            template.category or "",
        ]
        
        if hasattr(template, 'tags') and template.tags:
            parts.extend(template.tags)
        
        if hasattr(template, 'keywords') and template.keywords:
            parts.extend(template.keywords)
        
        return " ".join(parts)
    
    async def suggest_templates(
        self,
        transcription: str,
        templates: List[Template],
        top_k: int = 3,
        user_history: Optional[List[int]] = None,
        meeting_topic: Optional[str] = None
    ) -> List[Tuple[Template, float]]:
        """
        Предложить подходящие шаблоны
        
        Args:
            transcription: Текст транскрипции
            templates: Доступные шаблоны
            top_k: Количество рекомендаций
            user_history: История использования (template_id)
            meeting_topic: Тема встречи (если есть)
        
        Returns:
            List[(template, confidence_score)]
        """
        self._lazy_init()
        if not self._initialized:
            return []
        
        # Индексируем шаблоны если еще не сделали
        if not self.template_embeddings:
            await self.index_templates(templates)
        
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            
            # Формируем текст для анализа (расширенный контекст)
            # Берем начало (2000) и середину (2000) для лучшего охвата
            text_len = len(transcription)
            if text_len <= 4000:
                sample = transcription
            else:
                start_part = transcription[:2000]
                mid_start = text_len // 2
                mid_part = transcription[mid_start : mid_start + 2000]
                sample = f"{start_part} ... {mid_part}"
            
            top_category, _category_scores = self._score_categories(transcription)

            # Добавляем тему встречи в контекст поиска (сильный сигнал)
            if meeting_topic:
                sample = f"Тема: {meeting_topic}\n\n{sample}"
            
            # Создаем embedding транскрипции
            query_embedding = self.model.encode(sample, convert_to_numpy=True)
            
            # Вычисляем similarity со всеми шаблонами
            scores = []
            for template in templates:
                if template.id not in self.template_embeddings:
                    continue
                
                template_embedding = self.template_embeddings[template.id]
                similarity = cosine_similarity(
                    query_embedding.reshape(1, -1),
                    template_embedding.reshape(1, -1)
                )[0][0]
                
                # Бонус за историю использования
                history_boost = 0.0
                if user_history and template.id in user_history:
                    frequency = user_history.count(template.id)
                    history_boost = min(0.1 * frequency, 0.3)  # макс +30%
                
                # Бонус за соответствие категории (скоринг по ключевым словам)
                category_boost = 0.0
                if top_category in MEETING_TYPE_TO_CATEGORIES:
                    category_keywords = MEETING_TYPE_TO_CATEGORIES[top_category]
                    template_text = f"{template.name} {template.description or ''} {template.category or ''}".lower()

                    for keyword in category_keywords:
                        if keyword in template_text:
                            # Повышенный boost для бизнес встреч (+30% вместо +15%)
                            if top_category == 'business':
                                category_boost = 0.30  # +30% для бизнес шаблонов
                            else:
                                category_boost = 0.15  # +15% для остальных категорий
                            logger.debug(
                                f"Категорийный boost для шаблона '{template.name}': "
                                f"category={top_category}, keyword='{keyword}', boost={category_boost}"
                            )
                            break
                
                final_score = similarity + history_boost + category_boost
                scores.append((template, float(final_score)))
            
            # Сортируем по убыванию score
            scores.sort(key=lambda x: x[1], reverse=True)
            
            return scores[:top_k]
            
        except Exception as e:
            logger.error(f"Ошибка в suggest_templates: {e}")
            return []
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Извлечь ключевые слова из текста (простая эвристика)"""
        keywords = []

        # Управленческие ключевые слова
        management_terms = [
            "стратегия", "бюджет", "KPI", "цели", "OKR", "ресурсы",
            "планирование", "риски", "отчет", "квартал"
        ]

        # Продуктовые ключевые слова
        product_terms = [
            "спринт", "задачи", "backlog", "story", "ретроспектива",
            "standup", "roadmap", "фичи", "релиз", "пользователи"
        ]

        # Образовательные ключевые слова
        educational_terms = [
            "лекция", "презентация", "тренинг", "семинар", "мастер-класс",
            "обучение", "учебный", "образовательный", "практикум", "воркшоп",
            "вебинар", "концепция", "определение", "теория", "практика",
            "упражнение", "материал", "курс", "занятие", "дискуссия"
        ]

        text_lower = text.lower()

        for term in management_terms + product_terms + educational_terms:
            if term in text_lower:
                keywords.append(term)

        return keywords


# Глобальный экземпляр
smart_selector = SmartTemplateSelector()

