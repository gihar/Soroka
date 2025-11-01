"""
Сервис построения структурированного представления встречи
"""

import json
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from datetime import datetime

from src.models.meeting_structure import (
    MeetingStructure, MeetingMetadata, SpeakerProfile,
    Topic, Decision, ActionItem,
    DecisionPriority, ActionItemPriority, ActionItemStatus
)
from config import settings
from src.models.llm_schemas import get_schema_by_type
from llm_providers import safe_json_parse


class MeetingStructureBuilder:
    """Построение структурированного представления встречи"""
    
    def __init__(self, llm_manager=None):
        """
        Args:
            llm_manager: Менеджер LLM для извлечения данных
        """
        self.llm_manager = llm_manager
    
    async def build_from_transcription(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]] = None,
        meeting_type: str = "general",
        language: str = "ru"
    ) -> MeetingStructure:
        """
        Построить структуру встречи из транскрипции
        
        Args:
            transcription: Текст транскрипции. Рекомендуется передавать форматированную
                          транскрипцию с разметкой спикеров (formatted_transcript)
                          для лучшего понимания контекста "кто что сказал"
            diarization_analysis: Результат анализа диаризации
            meeting_type: Тип встречи
            language: Язык
            
        Returns:
            MeetingStructure
            
        Note:
            Если передана форматированная транскрипция с метками спикеров
            (SPEAKER_1: текст\n\nSPEAKER_2: текст), LLM сможет лучше определить:
            - Инициаторов решений
            - Ответственных за задачи
            - Участников обсуждения каждой темы
        """
        logger.info("Начало построения структуры встречи")
        
        # Проверка размера транскрипции
        MAX_TRANSCRIPTION_LENGTH = 400000  # ~100k токенов (1 токен ≈ 4 символа)
        transcription_length = len(transcription)
        
        if transcription_length > MAX_TRANSCRIPTION_LENGTH:
            logger.warning(
                f"⚠️ Транскрипция слишком большая для структурирования: "
                f"{transcription_length} символов (максимум {MAX_TRANSCRIPTION_LENGTH})"
            )
            logger.info("Пропускаем структурирование и возвращаем базовую структуру")
            
            # Возвращаем минимальную структуру без LLM обработки
            metadata = self._build_metadata(
                transcription, diarization_analysis, meeting_type, language
            )
            
            return MeetingStructure(
                metadata=metadata,
                speakers={},
                topics=[],
                decisions=[],
                action_items=[]
            )
        
        logger.info(f"Размер транскрипции: {transcription_length} символов (в пределах лимита)")
        
        # 1. Построение метаданных
        metadata = self._build_metadata(
            transcription, diarization_analysis, meeting_type, language
        )
        
        # 2. Построение профилей спикеров
        speakers = await self._build_speaker_profiles(
            transcription, diarization_analysis
        )
        
        # 3. Параллельное извлечение основных сущностей через LLM
        if self.llm_manager and settings.enable_meeting_structure:
            topics, decisions, action_items = await self._extract_entities_parallel(
                transcription, diarization_analysis, speakers
            )
        else:
            # Fallback: базовое извлечение без LLM
            topics = []
            decisions = []
            action_items = []
            logger.warning("LLM manager не доступен или структурирование отключено, используем базовое извлечение")
        
        # 4. Связывание данных
        self._link_entities(topics, decisions, action_items, speakers)
        
        # 5. Генерация инсайтов
        key_insights = self._generate_insights(
            topics, decisions, action_items, speakers
        )
        
        # 6. Создание резюме
        summary = self._generate_summary(
            metadata, topics, decisions, action_items
        )
        
        structure = MeetingStructure(
            metadata=metadata,
            speakers=speakers,
            topics=topics,
            decisions=decisions,
            action_items=action_items,
            original_transcription=transcription,
            diarization_available=bool(diarization_analysis),
            key_insights=key_insights,
            summary=summary
        )
        
        # Валидация
        validation = structure.validate_structure()
        if not validation["valid"]:
            logger.warning(f"Структура имеет проблемы: {validation['issues']}")
        if validation["warnings"]:
            logger.info(f"Предупреждения структуры: {validation['warnings']}")
        
        logger.info(
            f"Структура построена: {len(topics)} тем, {len(decisions)} решений, "
            f"{len(action_items)} задач, {len(speakers)} спикеров"
        )
        
        return structure
    
    def _build_metadata(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]],
        meeting_type: str,
        language: str
    ) -> MeetingMetadata:
        """Построить метаданные встречи"""
        
        duration_seconds = 0.0
        participant_count = 0
        has_diarization = False
        
        if diarization_analysis:
            has_diarization = True
            duration_seconds = diarization_analysis.get("total_speaking_time_seconds", 0.0)
            participant_count = diarization_analysis.get("total_speakers", 0)
        else:
            # Оценка по количеству слов
            word_count = len(transcription.split())
            duration_seconds = (word_count / 150) * 60  # 150 слов/мин
        
        # Форматирование длительности
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        duration_formatted = f"{minutes}:{seconds:02d}"
        
        return MeetingMetadata(
            duration_seconds=duration_seconds,
            duration_formatted=duration_formatted,
            participant_count=participant_count,
            meeting_type=meeting_type,
            language=language,
            has_diarization=has_diarization,
            processing_timestamp=datetime.now()
        )
    
    async def _build_speaker_profiles(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]]
    ) -> Dict[str, SpeakerProfile]:
        """Построить профили спикеров"""
        
        speakers = {}
        
        if not diarization_analysis:
            return speakers
        
        speakers_data = diarization_analysis.get("speakers", {})
        
        for speaker_id, speaker_info in speakers_data.items():
            profile = SpeakerProfile(
                speaker_id=speaker_id,
                role=speaker_info.get("role"),
                speaking_time_percent=speaker_info.get("speaking_time_percent", 0.0),
                word_count=speaker_info.get("word_count", 0),
                interaction_count=len(speaker_info.get("phrases", []))
            )
            speakers[speaker_id] = profile
        
        return speakers
    
    async def _extract_entities_parallel(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]],
        speakers: Dict[str, SpeakerProfile]
    ) -> Tuple[List[Topic], List[Decision], List[ActionItem]]:
        """Параллельное извлечение сущностей через LLM"""
        
        logger.info("Параллельное извлечение тем, решений и задач через LLM")
        
        # Запускаем извлечение параллельно
        tasks = [
            self.extract_topics(transcription, diarization_analysis),
            self.extract_decisions(transcription, speakers),
            self.extract_action_items(transcription, speakers)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        topics = results[0] if not isinstance(results[0], Exception) else []
        decisions = results[1] if not isinstance(results[1], Exception) else []
        action_items = results[2] if not isinstance(results[2], Exception) else []
        
        return topics, decisions, action_items
    
    async def extract_topics(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]] = None
    ) -> List[Topic]:
        """Извлечь темы обсуждения"""
        
        if not self.llm_manager:
            return []
        
        try:
            prompt = self._build_topics_extraction_prompt(transcription, diarization_analysis)
            
            # Используем LLM для извлечения
            response = await self._call_llm_for_extraction(prompt, "topics")
            
            # Парсим результат
            topics = []
            topics_data = response.get("topics", [])
            
            for idx, topic_dict in enumerate(topics_data):
                try:
                    topic = Topic(
                        id=f"topic_{idx + 1}",
                        title=topic_dict.get("title", ""),
                        description=topic_dict.get("description", ""),
                        start_time=topic_dict.get("start_time"),
                        end_time=topic_dict.get("end_time"),
                        duration=topic_dict.get("duration"),
                        participants=topic_dict.get("participants", []),
                        key_points=topic_dict.get("key_points", []),
                        sentiment=topic_dict.get("sentiment")
                    )
                    topics.append(topic)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга темы {idx}: {e}")
            
            logger.info(f"Извлечено тем: {len(topics)}")
            return topics
            
        except Exception as e:
            logger.error(f"Ошибка извлечения тем: {e}")
            return []
    
    async def extract_decisions(
        self,
        transcription: str,
        speakers: Dict[str, SpeakerProfile]
    ) -> List[Decision]:
        """Извлечь решения"""
        
        if not self.llm_manager:
            return []
        
        try:
            prompt = self._build_decisions_extraction_prompt(transcription, speakers)
            
            response = await self._call_llm_for_extraction(prompt, "decisions")
            
            decisions = []
            decisions_data = response.get("decisions", [])
            
            for idx, decision_dict in enumerate(decisions_data):
                try:
                    priority_str = decision_dict.get("priority", "medium")
                    priority = DecisionPriority(priority_str) if priority_str in ["high", "medium", "low"] else DecisionPriority.MEDIUM
                    
                    decision = Decision(
                        id=f"decision_{idx + 1}",
                        text=decision_dict.get("text", ""),
                        context=decision_dict.get("context", ""),
                        decision_makers=decision_dict.get("decision_makers", []),
                        mentioned_speakers=decision_dict.get("mentioned_speakers", []),
                        priority=priority,
                        timestamp=decision_dict.get("timestamp")
                    )
                    decisions.append(decision)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга решения {idx}: {e}")
            
            logger.info(f"Извлечено решений: {len(decisions)}")
            return decisions
            
        except Exception as e:
            logger.error(f"Ошибка извлечения решений: {e}")
            return []
    
    async def extract_action_items(
        self,
        transcription: str,
        speakers: Dict[str, SpeakerProfile]
    ) -> List[ActionItem]:
        """Извлечь задачи и поручения"""
        
        if not self.llm_manager:
            return []
        
        try:
            prompt = self._build_action_items_extraction_prompt(transcription, speakers)
            
            response = await self._call_llm_for_extraction(prompt, "action_items")
            
            action_items = []
            actions_data = response.get("action_items", [])
            
            for idx, action_dict in enumerate(actions_data):
                try:
                    priority_str = action_dict.get("priority", "medium")
                    priority = ActionItemPriority(priority_str) if priority_str in ["critical", "high", "medium", "low"] else ActionItemPriority.MEDIUM
                    
                    action = ActionItem(
                        id=f"action_{idx + 1}",
                        description=action_dict.get("description", ""),
                        assignee=action_dict.get("assignee"),
                        assignee_name=action_dict.get("assignee_name"),
                        deadline=action_dict.get("deadline"),
                        priority=priority,
                        status=ActionItemStatus.NOT_STARTED,
                        context=action_dict.get("context", ""),
                        timestamp=action_dict.get("timestamp")
                    )
                    action_items.append(action)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга задачи {idx}: {e}")
            
            logger.info(f"Извлечено задач: {len(action_items)}")
            return action_items
            
        except Exception as e:
            logger.error(f"Ошибка извлечения задач: {e}")
            return []
    
    def _build_topics_extraction_prompt(
        self,
        transcription: str,
        diarization_analysis: Optional[Dict[str, Any]]
    ) -> str:
        """Построить промпт для извлечения тем"""
        
        has_speaker_labels = "SPEAKER_" in transcription or "Спикер" in transcription
        speaker_note = ""
        if has_speaker_labels:
            speaker_note = """
ПРИМЕЧАНИЕ: Транскрипция содержит метки спикеров (SPEAKER_1, SPEAKER_2 и т.д.).
Используй эти метки для определения участников обсуждения каждой темы.
"""
        
        prompt = f"""Проанализируй транскрипцию встречи и извлеки все обсуждаемые темы.

ТРАНСКРИПЦИЯ:
{transcription}

{speaker_note}

ЗАДАЧА:
Извлеки все темы, которые обсуждались на встрече. Для каждой темы определи:
1. Название темы (краткое и точное)
2. Описание (что конкретно обсуждалось)
3. Ключевые моменты обсуждения (главные идеи)
4. Участники обсуждения (используй ID спикеров из транскрипции: SPEAKER_1, SPEAKER_2 и т.д.)

ФОРМАТ ОТВЕТА:
Верни JSON в формате:
{{
    "topics": [
        {{
            "title": "Название темы",
            "description": "Описание",
            "key_points": ["Пункт 1", "Пункт 2"],
            "participants": ["SPEAKER_1", "SPEAKER_2"],
            "sentiment": "positive/neutral/negative"
        }}
    ]
}}

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""

        return prompt
    
    def _build_decisions_extraction_prompt(
        self,
        transcription: str,
        speakers: Dict[str, SpeakerProfile]
    ) -> str:
        """Построить промпт для извлечения решений"""
        
        speakers_info = ", ".join(speakers.keys()) if speakers else "не указаны"
        has_speaker_labels = "SPEAKER_" in transcription or "Спикер" in transcription
        
        speaker_note = ""
        if has_speaker_labels:
            speaker_note = """
ПРИМЕЧАНИЕ: Транскрипция содержит метки спикеров. Используй их для точного
определения того, КТО принял каждое решение, основываясь на контексте диалога.
"""
        
        prompt = f"""Проанализируй транскрипцию встречи и извлеки все принятые решения.

ТРАНСКРИПЦИЯ:
{transcription}

УЧАСТНИКИ:
{speakers_info}

{speaker_note}

ЗАДАЧА:
Извлеки все решения, которые были приняты на встрече. Для каждого решения определи:
1. Текст решения (что именно решили)
2. Контекст (почему это решение было принято)
3. Кто принял решение (ID спикеров: SPEAKER_1, SPEAKER_2 и т.д.)
4. Приоритет: high/medium/low

ФОРМАТ ОТВЕТА:
Верни JSON в формате:
{{
    "decisions": [
        {{
            "text": "Текст решения",
            "context": "Контекст",
            "decision_makers": ["SPEAKER_1"],
            "mentioned_speakers": ["SPEAKER_2"],
            "priority": "high"
        }}
    ]
}}

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""

        return prompt
    
    def _build_action_items_extraction_prompt(
        self,
        transcription: str,
        speakers: Dict[str, SpeakerProfile]
    ) -> str:
        """Построить промпт для извлечения задач"""
        
        speakers_info = ", ".join(speakers.keys()) if speakers else "не указаны"
        has_speaker_labels = "SPEAKER_" in transcription or "Спикер" in transcription
        
        speaker_note = ""
        if has_speaker_labels:
            speaker_note = """
ПРИМЕЧАНИЕ: Транскрипция содержит метки спикеров. Используй их для точного
определения того, КОМУ назначена каждая задача, основываясь на контексте диалога.
Ответственный - это тот, кто взял задачу на себя или кому её поручили.
"""
        
        prompt = f"""Проанализируй транскрипцию встречи и извлеки все задачи и поручения.

ТРАНСКРИПЦИЯ:
{transcription}

УЧАСТНИКИ:
{speakers_info}

{speaker_note}

ЗАДАЧА:
Извлеки все задачи, поручения и действия, которые нужно выполнить. Для каждой задачи определи:
1. Описание задачи (что нужно сделать)
2. Ответственный (ID спикера: SPEAKER_1, SPEAKER_2 и т.д.)
3. Срок выполнения (если упомянут)
4. Приоритет: critical/high/medium/low
5. Контекст задачи

ФОРМАТ ОТВЕТА:
Верни JSON в формате:
{{
    "action_items": [
        {{
            "description": "Описание задачи",
            "assignee": "SPEAKER_1",
            "assignee_name": null,
            "deadline": "до конца недели",
            "priority": "high",
            "context": "В рамках проекта X"
        }}
    ]
}}

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""

        return prompt
    
    async def _call_llm_for_extraction(
        self,
        prompt: str,
        extraction_type: str
    ) -> Dict[str, Any]:
        """Вызов LLM для извлечения данных"""
        
        try:
            if not self.llm_manager:
                return {}
            
            # Используем OpenAI для структурного извлечения
            provider = self.llm_manager.providers.get("openai")
            if not provider or not provider.client:
                logger.warning("OpenAI провайдер недоступен для извлечения структур")
                return {}
            
            import openai
            
            # Простой системный промпт
            system_prompt = "Ты — точный аналитик встреч. Извлекай только фактическую информацию из транскрипции."
            
            # Формируем extra_headers для атрибуции
            extra_headers = {}
            if settings.http_referer:
                extra_headers["HTTP-Referer"] = settings.http_referer
            if settings.x_title:
                extra_headers["X-Title"] = settings.x_title
            
            # Выбираем соответствующую схему в зависимости от типа извлечения
            schema = get_schema_by_type(extraction_type)
            
            # Определяем модель для логирования
            model = settings.structure_extraction_model or settings.openai_model
            
            # Логирование запроса (если включено)
            if settings.llm_debug_log:
                logger.debug("=" * 80)
                logger.debug(f"=== LLM STRUCTURE EXTRACTION REQUEST ({extraction_type.upper()}) ===")
                logger.debug("=" * 80)
                logger.debug(f"Extraction type: {extraction_type}")
                logger.debug(f"Model: {model}")
                logger.debug(f"Schema type: {extraction_type}")
                logger.debug("-" * 80)
                logger.debug(f"System prompt:\n{system_prompt}")
                logger.debug("-" * 80)
                logger.debug(f"User prompt:\n{prompt}")
                logger.debug("=" * 80)
            
            async def _call_openai():
                return await asyncio.to_thread(
                    provider.client.chat.completions.create,
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_schema", "json_schema": schema},
                    extra_headers=extra_headers
                )
            
            response = await _call_openai()
            content = response.choices[0].message.content
            
            # Валидация ответа перед парсингом
            if content is None:
                logger.error(f"Получен None в качестве ответа от LLM для {extraction_type}")
                return {}
            
            if not content or len(content.strip()) == 0:
                logger.error(f"Получен пустой ответ от LLM для {extraction_type}")
                return {}
            
            # Проверка на HTML (признак ошибки API)
            if content.strip().startswith('<!DOCTYPE') or content.strip().startswith('<html'):
                logger.error(f"Получен HTML вместо JSON для {extraction_type}")
                logger.error(f"Первые 500 символов ответа: {content[:500]}")
                return {}
            
            # Проверка на текстовые сообщения об ошибках
            if any(error_pattern in content.lower() for error_pattern in ['error', 'rate limit', 'invalid request', 'service unavailable']):
                if not content.strip().startswith('{'):
                    logger.error(f"Получено сообщение об ошибке вместо JSON для {extraction_type}: {content[:200]}")
                    return {}
            
            # Логирование ответа (если включено)
            if settings.llm_debug_log:
                logger.debug("=" * 80)
                logger.debug(f"=== LLM STRUCTURE EXTRACTION RESPONSE ({extraction_type.upper()}) ===")
                logger.debug("=" * 80)
                logger.debug(f"Raw content:\n{content}")
                logger.debug("=" * 80)
            
            # Улучшенный парсинг JSON с использованием safe_json_parse
            try:
                result = safe_json_parse(content, context=f"MeetingStructureBuilder extraction ({extraction_type})")
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"❌ Не удалось распарсить JSON ответ от LLM для {extraction_type}: {e}")
                self._log_json_error_details(content, e, extraction_type)
                return {}
            
            if not result:
                logger.warning(f"Пустой результат парсинга для {extraction_type}")
                return {}
            
            # Логирование распарсенного результата (если включено)
            if settings.llm_debug_log:
                logger.debug(f"Parsed result keys: {list(result.keys())}")
                logger.debug(f"Result summary: {extraction_type}={len(result.get(extraction_type, []))}")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка вызова LLM для извлечения {extraction_type}: {e}")
            return {}
    
    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """Извлечь JSON из текста ответа (если LLM обернул JSON в markdown или текст)"""
        if not text:
            return None
        
        # Ищем JSON в markdown кодовых блоках
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json_match.group(1)
        
        # Ищем JSON объект напрямую (от первой { до последней })
        # Используем жадный поиск от первой { до последней }
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)
        
        return None
    
    def _log_json_error_details(self, content: str, error: json.JSONDecodeError, extraction_type: str):
        """Детальное логирование ошибок парсинга JSON"""
        logger.error(f"=== JSON PARSE ERROR DETAILS ({extraction_type}) ===")
        logger.error(f"Ошибка: {error}")
        logger.error(f"Длина content: {len(content)} символов")
        logger.error(f"Первые 500 символов: {content[:500]}")
        logger.error(f"Последние 500 символов: {content[-500:]}")
        
        # Логируем контекст вокруг ошибки
        if hasattr(error, 'pos') and error.pos is not None:
            error_pos = error.pos
            start = max(0, error_pos - 200)
            end = min(len(content), error_pos + 200)
            logger.error(f"Контекст вокруг ошибки (позиция {error_pos}):")
            logger.error(f"{content[start:end]}")
    
    def _link_entities(
        self,
        topics: List[Topic],
        decisions: List[Decision],
        action_items: List[ActionItem],
        speakers: Dict[str, SpeakerProfile]
    ):
        """Связать сущности между собой"""
        
        # Связываем решения с темами
        for decision in decisions:
            for topic in topics:
                # Простая эвристика: если слова из решения встречаются в теме
                decision_words = set(decision.text.lower().split())
                topic_words = set(topic.title.lower().split() + topic.description.lower().split())
                
                if len(decision_words & topic_words) >= 2:
                    decision.related_topics.append(topic.id)
                    topic.related_decisions.append(decision.id)
        
        # Связываем задачи с решениями и темами
        for action in action_items:
            action_words = set(action.description.lower().split())
            
            for decision in decisions:
                decision_words = set(decision.text.lower().split())
                if len(action_words & decision_words) >= 2:
                    action.related_decisions.append(decision.id)
            
            for topic in topics:
                topic_words = set(topic.title.lower().split() + topic.description.lower().split())
                if len(action_words & topic_words) >= 2:
                    action.related_topics.append(topic.id)
                    topic.related_actions.append(action.id)
        
        # Обновляем профили спикеров
        for speaker_id, profile in speakers.items():
            # Решения
            profile.decisions_made = [
                d.id for d in decisions 
                if speaker_id in d.decision_makers or speaker_id in d.mentioned_speakers
            ]
            
            # Задачи
            profile.tasks_assigned = [
                a.id for a in action_items 
                if a.assignee == speaker_id
            ]
            
            # Темы
            profile.topics_discussed = [
                t.id for t in topics 
                if speaker_id in t.participants
            ]
    
    def _generate_insights(
        self,
        topics: List[Topic],
        decisions: List[Decision],
        action_items: List[ActionItem],
        speakers: Dict[str, SpeakerProfile]
    ) -> List[str]:
        """Сгенерировать ключевые инсайты"""
        
        insights = []
        
        # Инсайт о количестве решений
        if len(decisions) > 5:
            insights.append(f"Принято большое количество решений ({len(decisions)})")
        elif len(decisions) == 0:
            insights.append("Не было принято явных решений")
        
        # Инсайт о задачах
        if len(action_items) > 0:
            unassigned = sum(1 for a in action_items if not a.assignee)
            if unassigned > 0:
                insights.append(f"{unassigned} из {len(action_items)} задач не имеют ответственного")
        
        # Инсайт об участии
        if speakers:
            speaking_times = [s.speaking_time_percent for s in speakers.values()]
            if speaking_times:
                max_time = max(speaking_times)
                if max_time > 60:
                    insights.append("Встреча доминировалась одним участником")
        
        # Инсайт о темах
        if len(topics) > 7:
            insights.append("Обсуждалось много тем - возможно, встреча была перегружена")
        
        return insights
    
    def _generate_summary(
        self,
        metadata: MeetingMetadata,
        topics: List[Topic],
        decisions: List[Decision],
        action_items: List[ActionItem]
    ) -> str:
        """Сгенерировать краткое резюме"""
        
        parts = []
        
        parts.append(f"Встреча типа '{metadata.meeting_type}' длительностью {metadata.duration_formatted}.")
        
        if topics:
            parts.append(f"Обсуждено тем: {len(topics)}.")
        
        if decisions:
            parts.append(f"Принято решений: {len(decisions)}.")
        
        if action_items:
            parts.append(f"Назначено задач: {len(action_items)}.")
        
        return " ".join(parts)


# Глобальный экземпляр (будет инициализирован позже с LLM manager)
_structure_builder = None


def get_structure_builder(llm_manager=None):
    """Получить экземпляр билдера структуры"""
    global _structure_builder
    if _structure_builder is None or llm_manager is not None:
        _structure_builder = MeetingStructureBuilder(llm_manager)
    return _structure_builder

