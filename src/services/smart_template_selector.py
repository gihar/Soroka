"""
ML-based классификатор шаблонов на основе embeddings
"""

import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from loguru import logger

from src.models.template import Template


# Маппинг типов встреч к ключевым словам категорий шаблонов
MEETING_TYPE_TO_CATEGORIES = {
    'technical': ['техническое', 'code review', 'разработка', 'архитектура', 'технический'],
    'business': ['деловое', 'переговоры', 'бизнес', 'продажи', 'коммерческ'],
    'educational': ['обучение', 'презентация', 'лекция', 'тренинг', 'образовательн'],
    'brainstorm': ['брейншторм', 'мозговой штурм', 'идеи', 'генерация'],
    'status': ['статус', 'отчет', 'ретроспектива', 'стендап', 'отчетн'],
}


class SmartTemplateSelector:
    """Умный выбор шаблона на основе ML"""
    
    def __init__(self):
        self.model = None
        self.template_embeddings: Dict[int, np.ndarray] = {}
        self._initialized = False
    
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
        meeting_type: Optional[str] = None,
        type_scores: Optional[Dict[str, float]] = None
    ) -> List[Tuple[Template, float]]:
        """
        Предложить подходящие шаблоны
        
        Args:
            transcription: Текст транскрипции
            templates: Доступные шаблоны
            top_k: Количество рекомендаций
            user_history: История использования (template_id)
            meeting_type: Классифицированный тип встречи (для boost)
            type_scores: Оценки по всем типам (для тонкой настройки)
        
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
            
            # Берем первые 1500 символов транскрипции для анализа
            sample = transcription[:1500]
            
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
                
                # Бонус за соответствие типу встречи
                category_boost = 0.0
                if meeting_type and meeting_type in MEETING_TYPE_TO_CATEGORIES:
                    category_keywords = MEETING_TYPE_TO_CATEGORIES[meeting_type]
                    template_text = f"{template.name} {template.description or ''} {template.category or ''}".lower()
                    
                    for keyword in category_keywords:
                        if keyword in template_text:
                            category_boost = 0.15  # +15% за соответствие категории
                            logger.debug(
                                f"Категорийный boost для шаблона '{template.name}': "
                                f"meeting_type={meeting_type}, keyword='{keyword}'"
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

