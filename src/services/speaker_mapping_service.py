"""
Сервис для автоматического сопоставления спикеров с участниками через LLM
"""

import json
import asyncio
from typing import List, Dict, Optional, Any
from loguru import logger

from llm_providers import llm_manager
from config import settings


class SpeakerMappingService:
    """Сервис для сопоставления спикеров с участниками"""
    
    def __init__(self):
        self.confidence_threshold = getattr(settings, 'speaker_mapping_confidence_threshold', 0.7)
    
    async def map_speakers_to_participants(
        self,
        diarization_data: Dict[str, Any],
        participants: List[Dict[str, str]],
        transcription_text: str,
        llm_provider: str = "openai"
    ) -> Dict[str, str]:
        """
        Автоматическое сопоставление спикеров с участниками
        
        Args:
            diarization_data: Данные диаризации со спикерами
            participants: Список участников с именами и ролями
            transcription_text: Полный текст транскрипции
            llm_provider: LLM провайдер для сопоставления
            
        Returns:
            Словарь сопоставления {speaker_id: participant_name}
        """
        try:
            logger.info(f"Начало сопоставления {len(participants)} участников со спикерами")
            
            # Извлекаем информацию о спикерах из диаризации
            speakers_info = self._extract_speakers_info(diarization_data)
            
            if not speakers_info:
                logger.warning("Нет информации о спикерах для сопоставления")
                return {}
            
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
            
            # Валидируем результат
            validated_mapping = self._validate_mapping(
                mapping_result,
                speakers_info,
                participants
            )
            
            logger.info(f"Сопоставление завершено: {len(validated_mapping)} спикеров")
            return validated_mapping
            
        except Exception as e:
            logger.error(f"Ошибка при сопоставлении спикеров: {e}")
            # Возвращаем пустой mapping - протокол будет без имен
            return {}
    
    def _extract_speakers_info(self, diarization_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Извлечение информации о спикерах из данных диаризации"""
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
            
            # Распределяем фрагменты: начало, середина, конец (всего до 5 фрагментов)
            text_samples = self._get_distributed_samples(speaker_segments, max_samples=5)
            
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
        participants_list = []
        for i, p in enumerate(participants, 1):
            name = p['name']
            role = p.get('role', '')
            if role:
                # Добавляем описание типичного поведения для роли
                behavior = self._get_role_behavior_hint(role)
                participants_list.append(f"{i}. {name} ({role})")
                if behavior:
                    participants_list.append(f"   Типичное поведение: {behavior}")
            else:
                participants_list.append(f"{i}. {name}")
        participants_str = "\n".join(participants_list)
        
        # Форматируем информацию о спикерах с расширенным набором фрагментов
        speakers_list = []
        for speaker in speakers_info:
            speaker_id = speaker['speaker_id']
            samples = speaker['text_samples'][:5]  # Увеличено до 5 фрагментов
            
            speakers_list.append(f"\n{speaker_id}:")
            if samples:
                for i, sample in enumerate(samples, 1):
                    # Увеличена длина фрагмента до 300 символов
                    sample_text = sample[:300] + "..." if len(sample) > 300 else sample
                    speakers_list.append(f"  Фрагмент {i}: \"{sample_text}\"")
            else:
                speakers_list.append("  (нет текстовых фрагментов)")
        
        speakers_str = "\n".join(speakers_list)
        
        # Получаем расширенный контекст транскрипции (начало, середина, конец)
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        if formatted_transcript:
            transcript_preview = self._get_transcript_preview(formatted_transcript)
        else:
            transcript_preview = self._get_transcript_preview(transcription_text)
        
        prompt = f"""Ты — эксперт по анализу встреч и диалогов. Твоя задача — сопоставить говорящих (Спикер 1, Спикер 2, и т.д.) с реальными участниками встречи.

УЧАСТНИКИ С РОЛЕВЫМ КОНТЕКСТОМ:
{participants_str}

ИНФОРМАЦИЯ О СПИКЕРАХ ИЗ ДИАРИЗАЦИИ:
{speakers_str}

ФРАГМЕНТЫ ТРАНСКРИПЦИИ ДЛЯ АНАЛИЗА:
{transcript_preview}

ЗАДАЧА:
Проанализируй транскрипцию и сопоставь каждого спикера с участником из списка, используя роли и типичное поведение.

КРИТЕРИИ ДЛЯ СОПОСТАВЛЕНИЯ:
1. ПРЕДСТАВЛЕНИЯ: Кто представляется в начале? ("Меня зовут...", "Я — ...")
2. ОБРАЩЕНИЯ: Как участники обращаются друг к другу? ("Иван, как думаешь?")
3. РОЛИ И ПОВЕДЕНИЕ: Сопоставь стиль речи с ролью участника (см. "типичное поведение")
4. СТИЛЬ РЕЧИ: Авторитетный/директивный vs исполнительский/вопросительный
5. КОНТЕКСТ: Упоминания должностей, отделов, ответственности, экспертизы

ТИПИЧНЫЕ ПАТТЕРНЫ ИДЕНТИФИКАЦИИ:

ОРГАНИЗАТОР/РУКОВОДИТЕЛЬ/МЕНЕДЖЕР:
- "Давайте начнем", "Переходим к следующему пункту", "Итак, подводя итоги"
- Задает вопросы всем участникам: "Иван, как у тебя дела с задачей?"
- Принимает решения: "Хорошо, решено", "Делаем так"
- Распределяет задачи: "Мария, займись этим"

ДОКЛАДЧИК/ИСПОЛНИТЕЛЬ/СПЕЦИАЛИСТ:
- "Я сделал...", "У меня готово...", "Я хотел бы показать..."
- Отвечает на вопросы о статусе своей работы
- Использует "у меня", "я работал", "я планирую"
- Объясняет детали своей области ответственности

ЭКСПЕРТ/КОНСУЛЬТАНТ/ТЕХНИЧЕСКИЙ СПЕЦИАЛИСТ:
- "На мой взгляд", "Я рекомендую", "Лучше сделать так..."
- Дает советы и рекомендации по специальным вопросам
- Объясняет технические детали и нюансы
- Использует профессиональную терминологию

ВАЖНО:
- ИСПОЛЬЗУЙ РОЛИ из списка участников для повышения точности сопоставления
- Если уверенности в сопоставлении нет (< 0.7) — не включай спикера в результат
- Один участник может соответствовать только одному спикеру
- Если участников больше чем спикеров — сопоставь только тех, кто говорил
- Если спикеров больше чем участников — сопоставь только тех, в ком уверен

ФОРМАТ ВЫВОДА:
Строго валидный JSON объект без комментариев:
{{
  "SPEAKER_1": "Имя Участника",
  "SPEAKER_2": "Имя Участника",
  "confidence": {{
    "SPEAKER_1": 0.95,
    "SPEAKER_2": 0.80
  }},
  "reasoning": {{
    "SPEAKER_1": "Краткое объяснение (представился, роль руководителя, ведет встречу)",
    "SPEAKER_2": "Краткое объяснение (обращаются 'Мария', отчитывается, роль разработчика)"
  }}
}}

ПРИМЕР:
{{
  "SPEAKER_1": "Иван Петров",
  "SPEAKER_2": "Мария Иванова",
  "confidence": {{
    "SPEAKER_1": 0.95,
    "SPEAKER_2": 0.85
  }},
  "reasoning": {{
    "SPEAKER_1": "Представился в начале, ведет встречу, принимает решения — соответствует роли Менеджера",
    "SPEAKER_2": "К ней обращаются 'Мария', отчитывается о технических задачах — соответствует роли Разработчика"
  }}
}}

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""
        
        return prompt
    
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
                "Твоя задача — точно сопоставить говорящих с участниками встречи "
                "на основе контекста, ролей и упоминаний имен."
            )
            
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
                        model=cfg.openai_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.1,
                        response_format={"type": "json_object"},
                        extra_headers=extra_headers
                    )
                
                response = await _call_openai()
                content = response.choices[0].message.content
                
                # Парсим JSON
                result = json.loads(content)
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
        
        validated_mapping = {}
        
        if not mapping_result:
            return validated_mapping
        
        # Извлекаем confidence scores
        confidence_scores = mapping_result.get('confidence', {})
        reasoning = mapping_result.get('reasoning', {})
        
        # Получаем список имен участников
        participant_names = [p['name'] for p in participants]
        
        # Валидируем каждое сопоставление
        for speaker_id, participant_name in mapping_result.items():
            # Пропускаем служебные поля
            if speaker_id in ['confidence', 'reasoning']:
                continue
            
            # Проверяем что участник существует в списке
            if participant_name not in participant_names:
                logger.warning(
                    f"Участник '{participant_name}' для {speaker_id} не найден в списке"
                )
                continue
            
            # Проверяем confidence score
            confidence = confidence_scores.get(speaker_id, 0.0)
            if confidence < self.confidence_threshold:
                logger.info(
                    f"Низкая уверенность для {speaker_id} → {participant_name}: "
                    f"{confidence:.2f} < {self.confidence_threshold}"
                )
                continue
            
            # Добавляем в валидированный mapping
            validated_mapping[speaker_id] = participant_name
            
            # Логируем reasoning если есть
            if speaker_id in reasoning:
                logger.info(
                    f"Сопоставление {speaker_id} → {participant_name}: "
                    f"{reasoning[speaker_id]}"
                )
        
        return validated_mapping


# Глобальный экземпляр сервиса
speaker_mapping_service = SpeakerMappingService()


