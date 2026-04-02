"""
Сервис для автоматического сопоставления спикеров с участниками через LLM
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, Set
from loguru import logger

from llm_providers import llm_manager, safe_json_parse
from config import settings
from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA


class SpeakerMappingService:
    """Сервис для сопоставления спикеров с участниками"""
    
    def __init__(self):
        self.confidence_threshold = getattr(settings, 'speaker_mapping_confidence_threshold', 0.7)
        self.full_text_matching = getattr(settings, 'full_text_matching', False)
    
    async def map_speakers_to_participants(
        self,
        diarization_data: Dict[str, Any],
        participants: List[Dict[str, str]],
        transcription_text: str,
        llm_provider: str = "openai"
    ) -> tuple[Dict[str, str], str]:
        """
        Автоматическое сопоставление спикеров с участниками и определение типа встречи
        
        Args:
            diarization_data: Данные диаризации со спикерами
            participants: Список участников с именами и ролями
            transcription_text: Полный текст транскрипции
            llm_provider: LLM провайдер для сопоставления
            
        Returns:
            Tuple (speaker_mapping, meeting_type):
                - speaker_mapping: Словарь сопоставления {speaker_id: participant_name}
                - meeting_type: Тип встречи (technical, business, educational, brainstorm, status, general)
        """
        try:
            logger.info(f"Начало сопоставления {len(participants)} участников со спикерами и определения типа встречи")
            
            # Извлекаем информацию о спикерах из диаризации
            # При full_text_matching не извлекаем фрагменты - вся информация в полной транскрипции
            extract_samples = not self.full_text_matching
            if not extract_samples:
                logger.info("Режим full_text_matching: фрагменты речи не извлекаются (используется полная транскрипция)")
            
            speakers_info = self._extract_speakers_info(
                diarization_data,
                extract_samples=extract_samples
            )
            
            if not speakers_info:
                logger.warning("Нет информации о спикерах для сопоставления")
                return {}, "general"
            
            # Формируем промпт для LLM
            mapping_prompt = self._build_mapping_prompt(
                speakers_info,
                participants,
                transcription_text,
                diarization_data
            )
            
            # Отправляем запрос к LLM
            logger.info(f"Отправка запроса к LLM провайдеру: {llm_provider}")
            mapping_result = await self._call_llm_for_mapping(
                mapping_prompt,
                llm_provider
            )
            
            # Извлекаем meeting_type из результата
            meeting_type = mapping_result.get('meeting_type', 'general')
            logger.info(f"✅ Определен тип встречи: {meeting_type}")
            
            # Валидируем результат
            validated_mapping = self._validate_mapping(
                mapping_result,
                speakers_info,
                participants
            )
            
            logger.info(f"Сопоставление завершено: {len(validated_mapping)} спикеров, тип: {meeting_type}")
            return validated_mapping, meeting_type
            
        except Exception as e:
            logger.error(f"Ошибка при сопоставлении спикеров: {e}")
            # Возвращаем пустой mapping и general тип
            return {}, "general"
    
    def _extract_speakers_info(
        self, 
        diarization_data: Dict[str, Any],
        extract_samples: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Извлечение информации о спикерах из данных диаризации
        
        Args:
            diarization_data: Данные диаризации со спикерами
            extract_samples: Извлекать ли текстовые фрагменты речи (False при full_text_matching)
        
        Returns:
            Список информации о спикерах
        """
        speakers_info = []
        
        # Получаем список спикеров
        speakers = diarization_data.get('speakers', [])
        
        # Получаем форматированную транскрипцию с метками спикеров
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        
        # Получаем сегменты
        segments = diarization_data.get('segments', [])
        
        for speaker in speakers:
            # Извлекаем фрагменты речи этого спикера
            speaker_segments = [
                seg for seg in segments 
                if seg.get('speaker') == speaker
            ]
            
            # Извлекаем фрагменты только если требуется
            # При full_text_matching=True полная транскрипция уже содержит всю информацию,
            # поэтому извлечение фрагментов избыточно и только расходует токены LLM
            if extract_samples:
                text_samples = self._get_distributed_samples(speaker_segments, max_samples=5)
            else:
                text_samples = []
            
            # Подсчет времени говорения
            total_time = sum(
                seg.get('end', 0) - seg.get('start', 0)
                for seg in speaker_segments
            )
            
            speakers_info.append({
                'speaker_id': speaker,
                'segments_count': len(speaker_segments),
                'speaking_time': total_time,
                'text_samples': text_samples
            })
        
        # Сортируем по времени говорения (больше говорил = вероятно важнее)
        speakers_info.sort(key=lambda x: x['speaking_time'], reverse=True)
        
        return speakers_info
    
    def _get_distributed_samples(self, segments: List[Dict[str, Any]], max_samples: int = 5) -> List[str]:
        """
        Извлекает фрагменты речи, распределенные по всей транскрипции
        
        Args:
            segments: Список сегментов спикера
            max_samples: Максимальное количество фрагментов
            
        Returns:
            Список текстовых фрагментов
        """
        if not segments:
            return []
        
        total = len(segments)
        if total <= max_samples:
            # Если сегментов мало, берем все
            return [seg.get('text', '').strip() for seg in segments if seg.get('text')]
        
        # Распределяем индексы по всей длине
        indices = []
        if max_samples >= 3:
            # Начало, середина, конец + равномерно между ними
            indices.append(0)  # Начало
            indices.append(total // 2)  # Середина
            indices.append(total - 1)  # Конец
            
            # Добавляем промежуточные точки
            remaining = max_samples - 3
            if remaining > 0:
                step = total // (remaining + 1)
                for i in range(1, remaining + 1):
                    idx = step * i
                    if idx not in indices and idx < total:
                        indices.append(idx)
        else:
            # Просто равномерно распределяем
            step = total // max_samples
            indices = [i * step for i in range(max_samples)]
        
        # Сортируем индексы
        indices.sort()
        
        # Извлекаем тексты
        samples = []
        for idx in indices:
            if idx < total:
                text = segments[idx].get('text', '').strip()
                if text:
                    samples.append(text)
        
        return samples
    
    def _get_transcript_preview(self, transcript: str) -> str:
        """
        Получает расширенный контекст транскрипции (начало, середина, конец)
        
        Args:
            transcript: Полная транскрипция
            
        Returns:
            Форматированный превью транскрипции
        """
        length = len(transcript)
        
        if length <= 5000:
            # Если транскрипция короткая, возвращаем всю
            return transcript
        
        # Берем начало (2000 символов), середину (1500), конец (1500)
        start = transcript[:2000]
        
        middle_start = (length // 2) - 750
        middle_end = (length // 2) + 750
        middle = transcript[middle_start:middle_end]
        
        end = transcript[-1500:]
        
        preview = (
            "=== НАЧАЛО ВСТРЕЧИ ===\n"
            f"{start}\n"
            "...\n\n"
            "=== СЕРЕДИНА ВСТРЕЧИ ===\n"
            f"{middle}\n"
            "...\n\n"
            "=== КОНЕЦ ВСТРЕЧИ ===\n"
            f"{end}"
        )
        
        return preview
    
    def _get_role_behavior_hint(self, role: str) -> str:
        """
        Получает описание типичного поведения для роли
        
        Args:
            role: Роль участника
            
        Returns:
            Описание типичного поведения
        """
        role_lower = role.lower()
        
        # Руководящие роли
        if any(keyword in role_lower for keyword in ['руководител', 'менеджер', 'директор', 'лид', 'lead', 'manager']):
            return "координирует встречу, задает вопросы, принимает решения, распределяет задачи"
        
        # Технические роли
        if any(keyword in role_lower for keyword in ['разработчик', 'программист', 'developer', 'engineer', 'архитектор']):
            return "объясняет технические детали, предлагает решения, отчитывается о разработке"
        
        # Аналитики и исследователи
        if any(keyword in role_lower for keyword in ['аналитик', 'analyst', 'исследовател', 'researcher']):
            return "анализирует данные, предоставляет выводы, рекомендует на основе исследований"
        
        # Тестировщики и QA
        if any(keyword in role_lower for keyword in ['тестировщик', 'qa', 'качеств', 'quality']):
            return "сообщает о багах, тестирует функционал, проверяет качество"
        
        # Дизайнеры
        if any(keyword in role_lower for keyword in ['дизайнер', 'designer', 'ux', 'ui']):
            return "предлагает дизайн-решения, обсуждает пользовательский опыт"
        
        # Продуктовые роли
        if any(keyword in role_lower for keyword in ['продукт', 'product', 'владелец', 'owner']):
            return "определяет требования, приоритизирует задачи, представляет бизнес-цели"
        
        # Консультанты и эксперты
        if any(keyword in role_lower for keyword in ['консультант', 'эксперт', 'специалист', 'consultant', 'expert']):
            return "дает рекомендации, делится экспертизой, консультирует по специальным вопросам"
        
        # Общий случай
        return "участвует в обсуждении, высказывает мнение"
    
    def _build_mapping_prompt(
        self,
        speakers_info: List[Dict[str, Any]],
        participants: List[Dict[str, str]],
        transcription_text: str,
        diarization_data: Dict[str, Any]
    ) -> str:
        """Формирование промпта для LLM"""
        
        # Форматируем информацию об участниках с расширенным контекстом ролей
        from src.services.participants_service import participants_service
        participants_list = []
        for i, p in enumerate(participants, 1):
            full_name = p['name']
            short_name = participants_service.convert_full_name_to_short(full_name)
            role = p.get('role', '')
            if role:
                participants_list.append(f"{i}. {short_name} ({role})")
            else:
                participants_list.append(f"{i}. {short_name}")
        participants_str = "\n".join(participants_list)
        
        # Форматируем информацию о спикерах (только если есть фрагменты)
        speakers_str = ""
        
        # Проверяем, есть ли хотя бы у одного спикера фрагменты
        has_samples = any(speaker.get('text_samples') for speaker in speakers_info)
        
        if has_samples:
            speakers_list = []
            for speaker in speakers_info:
                speaker_id = speaker['speaker_id']
                samples = speaker['text_samples']
                
                speakers_list.append(f"\n{speaker_id}:")
                
                if samples:
                    # Показываем фрагменты (до 5 штук)
                    for i, sample in enumerate(samples[:5], 1):
                        # Увеличена длина фрагмента до 300 символов
                        sample_text = sample[:300] + "..." if len(sample) > 300 else sample
                        speakers_list.append(f"  Фрагмент {i}: \"{sample_text}\"")
            
            speakers_str = "\n".join(speakers_list)
        
        # Получаем контекст транскрипции (полный или превью)
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        if formatted_transcript:
            if self.full_text_matching:
                transcript_preview = formatted_transcript
            else:
                transcript_preview = self._get_transcript_preview(formatted_transcript)
        else:
            if self.full_text_matching:
                transcript_preview = transcription_text
            else:
                transcript_preview = self._get_transcript_preview(transcription_text)
        
        # Формируем секцию о спикерах отдельно (избегаем обратный слэш в f-string выражении)
        if speakers_str:
            speakers_section = f"ИНФОРМАЦИЯ О СПИКЕРАХ ИЗ ДИАРИЗАЦИИ:{speakers_str}\n\n"
        else:
            speakers_section = "📌 РЕЖИМ FULL TEXT MATCHING: Фрагменты речи не извлекаются. Используй полную транскрипцию ниже для анализа.\n\n"
        
        prompt = f"""Ты — эксперт по анализу встреч и диалогов. Твоя задача — выполнить ДВЕ задачи:

ЗАДАЧА 1: ОПРЕДЕЛЕНИЕ ТИПА ВСТРЕЧИ
На основе анализа контента транскрипции определи тип встречи:

ТИПЫ ВСТРЕЧ:
- **technical** (техническое): Обсуждение кода, архитектуры, API, баз данных, серверов, тестирования, фреймворков, библиотек, CI/CD, девопса, багов, дебага
- **business** (деловое): Обсуждение бюджета, прибыли, контрактов, сделок, клиентов, продаж, маркетинга, стратегии, финансов, инвестиций, ROI, конкурентов, договоров
- **educational** (образовательное): Обучение, объяснение, изучение, лекции, семинары, тренинги, презентации, передача знаний, менторство
- **brainstorm** (брейншторм): Генерация идей, креативные сессии, предложение вариантов, обсуждение возможностей, инновации, новые подходы
- **status** (статусное): Отчеты о прогрессе, статусные обновления, обсуждение метрик, KPI, результатов достижений, стендапы, ретроспективы
- **general** (общее): Если тип точно не определяется или смешанное содержание

ЛОГИКА ОПРЕДЕЛЕНИЯ:
1. Проанализируй основные темы и ключевые слова в транскрипции
2. Определи доминирующий тип контента
3. Учти характер обсуждения (обучение vs принятие решений vs генерация идей)
4. Выбери ОДИН наиболее подходящий тип

ЗАДАЧА 2: СОПОСТАВЛЕНИЕ СПИКЕРОВ С УЧАСТНИКАМИ

УЧАСТНИКИ С РОЛЕВЫМ КОНТЕКСТОМ:
{participants_str}

📌 ВАЖНО: СОПОСТАВЛЕНИЕ СОКРАЩЕННЫХ/НЕПОЛНЫХ ИМЕН

В транскрипции участники могут упоминаться по-разному:

1. УМЕНЬШИТЕЛЬНЫЕ ИМЕНА: Света/Светочка → Светлана, Леша/Алёша → Алексей, Саша → Александр/Александра, Вова → Владимир и т.д.
   
2. УПОМИНАНИЕ ПО ФАМИЛИИ: "Тимченко" → найди в списке полное имя с этой фамилией (например, "Алексей Тимченко")
   
3. УПОМИНАНИЕ ПО ИМЕНИ: Если упомянуто только имя → сопоставь с ФИО из списка (если несколько — используй контекст роли)
   
4. НЕОДНОЗНАЧНЫЕ УПОМИНАНИЯ: "Коллега из ОРТ", "Команда фронта" → если не можешь определить конкретное лицо, не включай в mapping

⚡ В результате используй имя в формате 'Имя Фамилия' (БЕЗ отчества) из списка!

{speakers_section}ФРАГМЕНТЫ ТРАНСКРИПЦИИ ДЛЯ АНАЛИЗА:
{transcript_preview}

ПРИОРИТЕТ КРИТЕРИЕВ: представления ("Меня зовут...") > обращения ("Иван, как думаешь?") > роль и стиль речи > контекст (должность, отдел).

ПРАВИЛА СОПОСТАВЛЕНИЯ:
1. ИСПОЛЬЗУЙ РОЛИ из списка участников для повышения точности сопоставления
2. ПОРОГ УВЕРЕННОСТИ: Включай спикера в speaker_mappings ТОЛЬКО если уверенность >= 0.7
   - Если уверенность < 0.7 — НЕ включай спикера в speaker_mappings
   - Такие спикеры должны быть в unmapped_speakers
3. УНИКАЛЬНОСТЬ: Один участник может соответствовать только одному спикеру (проверяй на противоречия!)
4. ВСЕ НЕСОПОСТАВЛЕННЫЕ В unmapped_speakers: 
   - Если спикер не сопоставлен — обязательно добавь его в unmapped_speakers
   - Пустой массив unmapped_speakers означает "все спикеры успешно сопоставлены"
5. ФОРМАТ ИМЕН: Используй ТОЧНО те имена, что указаны в списке участников в формате "Имя Фамилия"
   - Пример: если в списке "Алексей Тимченко", используй именно это, а не "Леша Тимченко"
6. КОЛИЧЕСТВО СПИКЕРОВ vs УЧАСТНИКОВ:
   - Если участников больше чем спикеров — сопоставь только тех, кто реально говорил
   - Если спикеров больше чем участников — сопоставь только тех, в ком уверен >= 0.7

ФОРМАТ ВЫВОДА:
Строго валидный JSON объект без комментариев:
{{
  "meeting_type": "technical",
  "speaker_mappings": {{
    "SPEAKER_1": "Имя Фамилия",
    "SPEAKER_2": "Имя Фамилия"
  }},
  "confidence_scores": {{
    "SPEAKER_1": 0.95,
    "SPEAKER_2": 0.80
  }},
  "unmapped_speakers": ["SPEAKER_3"],
  "mapping_notes": "Тип встречи: technical (обсуждение архитектуры и кода). SPEAKER_1: представился в начале, ведет встречу. SPEAKER_2: отчитывается о технических задачах."
}}

⚠️ КРИТИЧЕСКИ ВАЖНО:
- meeting_type ОБЯЗАТЕЛЬНО должен быть заполнен
- Все спикеры с confidence >= 0.7 ДОЛЖНЫ быть в speaker_mappings
- Все спикеры с confidence < 0.7 ДОЛЖНЫ быть в unmapped_speakers
- НЕ допускается пустой speaker_mappings если есть спикеры с уверенностью >= 0.7
- Каждый спикер должен быть либо в speaker_mappings, либо в unmapped_speakers

ТРЕБОВАНИЯ К mapping_notes:
- Укажи определенный тип встречи и краткое обоснование
- Для КАЖДОГО сопоставленного спикера укажи: какие сигналы использованы (представление/обращение/роль/стиль)
- Для несопоставленных спикеров (unmapped_speakers) укажи причину: почему уверенность < 0.7
- Формат: "Тип встречи: [тип] ([обоснование]). SPEAKER_N: [объяснение]. SPEAKER_M: [объяснение]."

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""
        
        return prompt
    
    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """
        Извлечь JSON из текста, даже если есть дополнительный текст или markdown разметка
        
        Args:
            text: Текст, который может содержать JSON
            
        Returns:
            Извлеченный JSON строку или None если не удалось найти
        """
        if not text:
            return None
        
        text = text.strip()
        
        # Попытка 1: Попытаться найти JSON в markdown блоке ```json ... ```
        import re
        # Ищем markdown блок с JSON, используя более сложный подход для вложенных структур
        json_block_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
        if json_block_match:
            json_candidate = json_block_match.group(1)
            # Проверяем, что это действительно валидный JSON с правильной вложенностью
            if json_candidate.count('{') == json_candidate.count('}'):
                return json_candidate
            # Если не совпадает, используем альтернативный метод поиска
        
        # Попытка 2: Найти первый { и последний }
        first_brace = text.find('{')
        if first_brace == -1:
            return None
        
        # Находим последнюю закрывающую скобку, учитывая вложенность
        brace_count = 0
        last_brace = -1
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_brace = i
                    break
        
        if last_brace == -1:
            # JSON не закрыт полностью - попробуем найти последнюю }
            last_brace = text.rfind('}')
            if last_brace > first_brace:
                # Попробуем извлечь и добавить недостающие закрывающие скобки
                partial_json = text[first_brace:last_brace + 1]
                # Подсчитаем открывающие и закрывающие скобки
                open_count = partial_json.count('{')
                close_count = partial_json.count('}')
                missing_closes = open_count - close_count
                if missing_closes > 0:
                    partial_json += '}' * missing_closes
                return partial_json
            return None
        
        return text[first_brace:last_brace + 1]
    
    async def _call_llm_for_mapping(
        self,
        prompt: str,
        llm_provider: str
    ) -> Dict[str, Any]:
        """Вызов LLM для получения сопоставления"""
        
        try:
            # Используем системный промпт для точности
            system_prompt = (
                "Ты — эксперт по анализу диалогов и идентификации говорящих. "
                "Твоя задача — точно сопоставить говорящих (SPEAKER_1, SPEAKER_2 и т.д.) с участниками встречи "
                "на основе контекста, ролей и упоминаний имен. "
                "Включай спикера в маппинг ТОЛЬКО при уверенности >= 0.7. "
                "Выводи результат в строгом JSON формате согласно предоставленной схеме."
            )
            
            # Логирование запроса (если включено)
            if settings.llm_debug_log:
                logger.debug("=" * 80)
                logger.debug("=== LLM MAPPING REQUEST ===")
                logger.debug("=" * 80)
                logger.debug(f"Provider: {llm_provider}")
                logger.debug(f"System prompt:\n{system_prompt}")
                logger.debug("-" * 80)
                logger.debug(f"User prompt:\n{prompt}")
                logger.debug("=" * 80)
            
            # Создаем минимальный запрос к LLM
            provider = llm_manager.providers.get(llm_provider)
            if not provider or not provider.is_available():
                raise ValueError(f"LLM провайдер {llm_provider} недоступен")
            
            # Для OpenAI используем специальный вызов
            if llm_provider == "openai":
                import openai
                from config import settings as cfg
                
                client = openai.OpenAI(
                    api_key=cfg.openai_api_key,
                    base_url=cfg.openai_base_url or "https://api.openai.com/v1"
                )
                
                # Формируем extra_headers
                extra_headers = {}
                if cfg.http_referer:
                    extra_headers["HTTP-Referer"] = cfg.http_referer
                if cfg.x_title:
                    extra_headers["X-Title"] = cfg.x_title
                
                async def _call_openai():
                    return await asyncio.to_thread(
                        client.chat.completions.create,
                        model=cfg.speaker_mapping_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.1,
                        response_format={"type": "json_schema", "json_schema": SPEAKER_MAPPING_SCHEMA},
                        extra_headers=extra_headers
                    )
                
                response = await _call_openai()
                content = response.choices[0].message.content
                
                # Логирование ответа (если включено)
                if settings.llm_debug_log:
                    logger.debug("=" * 80)
                    logger.debug("=== LLM MAPPING RESPONSE ===")
                    logger.debug("=" * 80)
                    logger.debug(f"Raw content:\n{content}")
                    logger.debug("=" * 80)
                
                # Парсим JSON с использованием safe_json_parse
                try:
                    result = safe_json_parse(content, context="SpeakerMappingService LLM response")
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"❌ Не удалось распарсить JSON ответа от LLM для маппинга спикеров: {e}")
                    return {}
                
                # Краткое резюме результата (если включено логирование)
                if settings.llm_debug_log:
                    mapped_count = len(result.get('speaker_mappings', {}))
                    unmapped_count = len(result.get('unmapped_speakers', []))
                    confidence_scores = result.get('confidence_scores', {})
                    avg_confidence = sum(confidence_scores.values()) / max(len(confidence_scores), 1) if confidence_scores else 0.0
                    logger.info(f"✅ LLM сопоставил {mapped_count} спикеров, {unmapped_count} несопоставленных")
                    logger.info(f"📊 Средняя уверенность: {avg_confidence:.2f}")
                
                return result
            
            else:
                # Для других провайдеров используем стандартный метод
                logger.warning(f"Сопоставление спикеров не оптимизировано для {llm_provider}")
                # Возвращаем пустой результат
                return {}
            
        except Exception as e:
            logger.error(f"Ошибка при вызове LLM для сопоставления: {e}")
            return {}
    
    def _validate_mapping(
        self,
        mapping_result: Dict[str, Any],
        speakers_info: List[Dict[str, Any]],
        participants: List[Dict[str, str]]
    ) -> Dict[str, str]:
        """Валидация результата сопоставления"""
        
        validated_mapping: Dict[str, str] = {}
        
        if not mapping_result:
            return validated_mapping
        
        from src.services.participants_service import participants_service

        # Извлекаем данные из нового формата схемы SpeakerMappingSchema
        speaker_mappings = mapping_result.get('speaker_mappings', {})
        confidence_scores = mapping_result.get('confidence_scores', {})
        mapping_notes = mapping_result.get('mapping_notes', '')
        
        # Строим карту имен для сопоставления
        name_lookup, ambiguous_variants = participants_service.build_name_lookup(participants)
        used_display_names: Set[str] = set()
        
        # Валидируем каждое сопоставление
        for speaker_id, participant_name in speaker_mappings.items():
            
            candidate_variants = participants_service.generate_name_variants(participant_name)
            normalized_raw = participants_service.normalize_name_for_matching(participant_name)
            if normalized_raw:
                candidate_variants.add(normalized_raw)
            
            ordered_candidates = sorted(
                candidate_variants,
                key=lambda value: (-len(value.split()), -len(value))
            )
            
            matched_entry = None
            for candidate in ordered_candidates:
                if not candidate:
                    continue
                
                if candidate in ambiguous_variants:
                    logger.info(
                        f"Пропускаем вариант '{candidate}' для {speaker_id} — неоднозначное совпадение"
                    )
                    continue
                
                entry = name_lookup.get(candidate)
                if entry:
                    matched_entry = entry
                    break
            
            if not matched_entry:
                logger.warning(
                    f"Участник '{participant_name}' для {speaker_id} не найден среди переданных участников"
                )
                continue
            
            display_name = matched_entry["display_name"]
            
            if display_name in used_display_names:
                logger.info(
                    f"Участник '{display_name}' уже сопоставлен с другим спикером, пропускаем {speaker_id}"
                )
                continue
            
            # Проверяем confidence score
            confidence = confidence_scores.get(speaker_id, 0.0)
            if confidence < self.confidence_threshold:
                logger.info(
                    f"Пропускаем {speaker_id} → {display_name}: уверенность "
                    f"{confidence:.2f} ниже порога {self.confidence_threshold:.2f}"
                )
                continue
            
            logger.debug(
                f"Сопоставление {speaker_id} → {display_name}: уверенность "
                f"{confidence:.2f}"
            )
            
            # Добавляем в валидированный mapping
            validated_mapping[speaker_id] = display_name
            used_display_names.add(display_name)
        
        # Логируем общие заметки по маппингу если есть
        if mapping_notes and settings.llm_debug_log:
            logger.info(f"Заметки по сопоставлению: {mapping_notes}")
        
        return validated_mapping


# Глобальный экземпляр сервиса
speaker_mapping_service = SpeakerMappingService()
