"""
Утилиты для извлечения релевантных фрагментов транскрипции
вместо передачи полного текста в LLM запросы
"""

from typing import List, Dict, Any, Optional
import re


def extract_relevant_excerpts(
    transcription: str,
    extracted_data: Dict[str, str],
    max_tokens: int = 10000
) -> str:
    """
    Извлечь релевантные фрагменты транскрипции на основе уже извлеченных данных
    
    Args:
        transcription: Полная транскрипция
        extracted_data: Данные, извлеченные на Stage 1
        max_tokens: Максимальное количество токенов (~4 символа на токен)
        
    Returns:
        Сжатое представление с релевантными фрагментами
    """
    max_chars = max_tokens * 4
    
    # Извлекаем ключевые фразы из extracted_data
    key_phrases = []
    for value in extracted_data.values():
        if value and isinstance(value, str) and len(value) > 10:
            # Берем первые значимые слова (3-5 слов)
            words = value.split()[:5]
            if len(words) >= 3:
                key_phrases.append(' '.join(words))
    
    if not key_phrases:
        # Fallback: начало и конец транскрипции
        half = max_chars // 2
        return f"НАЧАЛО:\n{transcription[:half]}\n\n...КОНЕЦ:\n{transcription[-half:]}"
    
    # Ищем фрагменты с упоминанием ключевых фраз
    relevant_parts = []
    total_length = 0
    
    for phrase in key_phrases:
        # Ищем контекст вокруг фразы (±200 символов)
        pattern = re.escape(phrase[:30])  # Первые 30 символов для поиска
        matches = list(re.finditer(pattern, transcription, re.IGNORECASE))
        
        for match in matches[:2]:  # Максимум 2 вхождения на фразу
            start = max(0, match.start() - 200)
            end = min(len(transcription), match.end() + 200)
            fragment = transcription[start:end]
            
            if total_length + len(fragment) > max_chars:
                break
                
            relevant_parts.append(fragment)
            total_length += len(fragment)
        
        if total_length >= max_chars:
            break
    
    if not relevant_parts:
        # Fallback
        return transcription[:max_chars]
    
    return "\n\n...\n\n".join(relevant_parts)


def build_structure_summary(meeting_structure) -> str:
    """
    Создать компактное текстовое представление meeting_structure
    вместо передачи полной структуры
    
    Args:
        meeting_structure: Объект MeetingStructure
        
    Returns:
        Текстовое представление для промпта
    """
    if not meeting_structure:
        return ""
    
    summary_parts = []
    
    # Темы
    if meeting_structure.topics:
        summary_parts.append(f"ТЕМЫ ({len(meeting_structure.topics)}):")
        for i, topic in enumerate(meeting_structure.topics[:10], 1):  # Максимум 10 тем
            summary_parts.append(f"{i}. {topic.title}")
            if topic.key_points:
                summary_parts.append(f"   Ключевые моменты: {', '.join(topic.key_points[:3])}")
    
    # Решения
    if meeting_structure.decisions:
        summary_parts.append(f"\nРЕШЕНИЯ ({len(meeting_structure.decisions)}):")
        for i, decision in enumerate(meeting_structure.decisions[:15], 1):
            summary_parts.append(f"{i}. {decision.text}")
    
    # Задачи
    if meeting_structure.action_items:
        summary_parts.append(f"\nЗАДАЧИ ({len(meeting_structure.action_items)}):")
        for i, action in enumerate(meeting_structure.action_items[:15], 1):
            assignee = action.assignee_name or action.assignee or "не указан"
            summary_parts.append(f"{i}. {action.description} (Ответственный: {assignee})")
    
    return "\n".join(summary_parts)


def add_prompt_caching_markers(
    system_prompt: str,
    transcription: str,
    task_specific_prompt: str
) -> List[Dict[str, Any]]:
    """
    Создать структуру сообщений с маркерами для prompt caching (OpenAI)
    
    Args:
        system_prompt: Системный промпт
        transcription: Транскрипция (будет кэшироваться)
        task_specific_prompt: Специфичный промпт для задачи
        
    Returns:
        Список сообщений в формате OpenAI с cache_control
    """
    messages = [
        {
            "role": "system",
            "content": system_prompt,
            # OpenAI автоматически кэширует длинные промпты
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"ТРАНСКРИПЦИЯ:\n\n{transcription}",
                    # Длинная транскрипция будет закэширована
                },
                {
                    "type": "text",
                    "text": task_specific_prompt
                }
            ]
        }
    ]
    
    return messages

