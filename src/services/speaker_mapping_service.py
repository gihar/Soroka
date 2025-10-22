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
            
            # Берем первые 3 фрагмента (для анализа контекста)
            first_segments = speaker_segments[:3] if speaker_segments else []
            
            speaker_text_samples = [
                seg.get('text', '').strip() 
                for seg in first_segments
                if seg.get('text')
            ]
            
            # Подсчет времени говорения
            total_time = sum(
                seg.get('end', 0) - seg.get('start', 0)
                for seg in speaker_segments
            )
            
            speakers_info.append({
                'speaker_id': speaker,
                'segments_count': len(speaker_segments),
                'speaking_time': total_time,
                'text_samples': speaker_text_samples
            })
        
        # Сортируем по времени говорения (больше говорил = вероятно важнее)
        speakers_info.sort(key=lambda x: x['speaking_time'], reverse=True)
        
        return speakers_info
    
    def _build_mapping_prompt(
        self,
        speakers_info: List[Dict[str, Any]],
        participants: List[Dict[str, str]],
        transcription_text: str,
        diarization_data: Dict[str, Any]
    ) -> str:
        """Формирование промпта для LLM"""
        
        # Форматируем информацию об участниках
        participants_list = []
        for p in participants:
            name = p['name']
            role = p.get('role', '')
            if role:
                participants_list.append(f"- {name} ({role})")
            else:
                participants_list.append(f"- {name}")
        participants_str = "\n".join(participants_list)
        
        # Форматируем информацию о спикерах
        speakers_list = []
        for speaker in speakers_info:
            speaker_id = speaker['speaker_id']
            samples = speaker['text_samples'][:2]  # Первые 2 фрагмента
            
            speakers_list.append(f"\n{speaker_id}:")
            if samples:
                for i, sample in enumerate(samples, 1):
                    # Обрезаем длинные фрагменты
                    sample_text = sample[:200] + "..." if len(sample) > 200 else sample
                    speakers_list.append(f"  Фрагмент {i}: \"{sample_text}\"")
            else:
                speakers_list.append("  (нет текстовых фрагментов)")
        
        speakers_str = "\n".join(speakers_list)
        
        # Получаем начало транскрипции для контекста
        formatted_transcript = diarization_data.get('formatted_transcript', '')
        if formatted_transcript:
            # Берем первые 2000 символов
            transcript_preview = formatted_transcript[:2000]
            if len(formatted_transcript) > 2000:
                transcript_preview += "\n...(транскрипция обрезана)"
        else:
            transcript_preview = transcription_text[:2000]
            if len(transcription_text) > 2000:
                transcript_preview += "\n...(транскрипция обрезана)"
        
        prompt = f"""Ты — эксперт по анализу встреч и диалогов. Твоя задача — сопоставить говорящих (Спикер 1, Спикер 2, и т.д.) с реальными участниками встречи.

СПИСОК УЧАСТНИКОВ ВСТРЕЧИ:
{participants_str}

ИНФОРМАЦИЯ О СПИКЕРАХ ИЗ ДИАРИЗАЦИИ:
{speakers_str}

НАЧАЛО ТРАНСКРИПЦИИ С МЕТКАМИ СПИКЕРОВ:
{transcript_preview}

ЗАДАЧА:
Проанализируй транскрипцию и сопоставь каждого спикера с участником из списка.

КРИТЕРИИ ДЛЯ СОПОСТАВЛЕНИЯ:
1. ПРЕДСТАВЛЕНИЯ: Кто представляется в начале? ("Меня зовут...", "Я — ...")
2. ОБРАЩЕНИЯ: Как участники обращаются друг к другу? ("Иван, как думаешь?")
3. РОЛИ: Кто ведет встречу? Кто принимает решения? Кто задает вопросы? Кто отчитывается?
4. СТИЛЬ РЕЧИ: Авторитетный/директивный стиль vs исполнительский/вопросительный
5. КОНТЕКСТ: Упоминания должностей, отделов, ответственности

ВАЖНО:
- Если уверенности в сопоставлении нет — оставь спикера без имени (не включай в результат)
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
    "SPEAKER_1": "Краткое объяснение (представился, роль руководителя)",
    "SPEAKER_2": "Краткое объяснение"
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
    "SPEAKER_1": "Представился в начале, ведет встречу, принимает решения",
    "SPEAKER_2": "К ней обращаются 'Мария', отчитывается о проделанной работе"
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


