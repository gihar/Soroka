"""
Утилиты для обработки текста
"""

import re
from typing import Dict


def replace_speakers_in_text(text: str, speaker_mapping: Dict[str, str]) -> str:
    """
    Заменяет все упоминания 'Спикер N' или 'SPEAKER_N' на реальные имена
    
    Args:
        text: Исходный текст
        speaker_mapping: Словарь сопоставления {speaker_id: name}
        
    Returns:
        Текст с замененными именами
    """
    if not speaker_mapping:
        return text
    
    result = text
    
    # Создаем список замен, отсортированный по длине (сначала более длинные)
    # Это нужно чтобы "SPEAKER_10" заменялся раньше чем "SPEAKER_1"
    replacements = sorted(
        speaker_mapping.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )
    
    for speaker_id, name in replacements:
        # Паттерны для поиска различных вариантов написания
        patterns = [
            # "SPEAKER_1", "SPEAKER_2" и т.д.
            (rf'\b{re.escape(speaker_id)}\b', name),
            
            # "Спикер 1", "Спикер 2" и т.д. (извлекаем номер)
            (rf'\bСпикер\s+{_extract_speaker_number(speaker_id)}\b', name),
            
            # Варианты с двоеточием "SPEAKER_1:", "Спикер 1:"
            (rf'\b{re.escape(speaker_id)}:', f'{name}:'),
            (rf'\bСпикер\s+{_extract_speaker_number(speaker_id)}:', f'{name}:'),
        ]
        
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result


def _extract_speaker_number(speaker_id: str) -> str:
    """
    Извлекает номер спикера из ID
    
    Args:
        speaker_id: ID спикера (например "SPEAKER_1")
        
    Returns:
        Номер спикера как строка
    """
    # Пытаемся извлечь число из конца строки
    match = re.search(r'(\d+)$', speaker_id)
    if match:
        return match.group(1)
    return ""


def format_participant_name_with_role(name: str, role: str = "") -> str:
    """
    Форматирует имя участника с ролью
    
    Args:
        name: Имя участника
        role: Роль участника (опционально)
        
    Returns:
        Отформатированная строка
    """
    if role:
        return f"{name}, {role}"
    return name


def clean_speaker_markers(text: str) -> str:
    """
    Очищает текст от оставшихся маркеров спикеров без сопоставления
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    # Удаляем паттерны типа "SPEAKER_N:" в начале строк
    result = re.sub(r'^SPEAKER_\d+:\s*', '', text, flags=re.MULTILINE)
    
    # Удаляем паттерны типа "Спикер N:" в начале строк
    result = re.sub(r'^Спикер\s+\d+:\s*', '', result, flags=re.MULTILINE)
    
    return result


