"""
Утилиты для форматирования транскрипций с сохранением последовательности реплик
"""
from typing import List, Dict, Any


def format_transcript_with_speaker_sequence(segments: List[Dict[str, Any]]) -> str:
    """
    Форматировать транскрипцию с сохранением последовательности реплик спикеров.
    
    Группирует только последовательные сегменты одного спикера, сохраняя при этом
    чередование разных спикеров в диалоге. Это позволяет LLM понимать динамику
    диалога и контекст каждого участника.
    
    Args:
        segments: Список сегментов с полями 'speaker' и 'text'
        
    Returns:
        Отформатированная транскрипция вида:
        SPEAKER_1: первая группа последовательных реплик
        
        SPEAKER_2: реплика спикера 2
        
        SPEAKER_1: вторая группа последовательных реплик
        
    Example:
        >>> segments = [
        ...     {"speaker": "SPEAKER_1", "text": "Привет"},
        ...     {"speaker": "SPEAKER_1", "text": "Как дела?"},
        ...     {"speaker": "SPEAKER_2", "text": "Хорошо"},
        ...     {"speaker": "SPEAKER_1", "text": "Отлично"}
        ... ]
        >>> format_transcript_with_speaker_sequence(segments)
        'SPEAKER_1: Привет Как дела?\\n\\nSPEAKER_2: Хорошо\\n\\nSPEAKER_1: Отлично'
    
    Note:
        НЕ группирует весь текст спикера в один блок - сохраняет последовательность!
        Плохо: SPEAKER_1: весь текст\n\nSPEAKER_2: весь текст
        Хорошо: SPEAKER_1: текст1\n\nSPEAKER_2: текст\n\nSPEAKER_1: текст2
    """
    if not segments:
        return ""
    
    formatted_lines = []
    current_speaker = None
    current_text = []
    
    for segment in segments:
        speaker = segment.get('speaker')
        text = segment.get('text', '').strip()
        
        if not text:
            continue
        
        if speaker != current_speaker:
            # Завершаем предыдущего говорящего
            if current_speaker and current_text:
                formatted_lines.append(f"{current_speaker}: {' '.join(current_text)}")
            
            # Начинаем нового говорящего
            current_speaker = speaker
            current_text = [text]
        else:
            # Продолжаем текущего говорящего (последовательные реплики)
            current_text.append(text)
    
    # Добавляем последнего говорящего
    if current_speaker and current_text:
        formatted_lines.append(f"{current_speaker}: {' '.join(current_text)}")
    
    return "\n\n".join(formatted_lines)

