"""
Утилиты для обработки текста
"""

import re
from typing import Dict, Tuple

_SPEAKER_LABEL_RE = re.compile(r"\bSPEAKER[_\s](\d+)\b")

# Неразрывный дефис (U+2011) визуально не отличим от обычного, но соседство с
# ним в одном тексте — машинный артефакт (живой протокол 358: «15‑минутки»).
# Длинное (U+2014) и среднее (U+2013) тире — легитимные разделители, их не трогаем.
_NON_BREAKING_HYPHEN = "‑"
_PLAIN_HYPHEN = "-"


def normalize_hyphens(text: str) -> str:
    """Свести неразрывный дефис (U+2011) к обычному в тексте протокола.

    Детерминированный финальный проход: убирает разнобой «неразрывный vs
    обычный дефис», не касаясь длинного/среднего тире (структурные
    разделители «задача — ответственный», диапазоны «14:00–15:30»).
    """
    return text.replace(_NON_BREAKING_HYPHEN, _PLAIN_HYPHEN)


# Маркер буллета перед нумерованным пунктом: «- 1. …», «* 2. …» (с отступом).
# Пробел после точки обязателен — «- 1.5 часа» и «- 05.2025» не номера пунктов.
_BULLETED_NUMBER_RE = re.compile(r"^(\s*)[-*]\s+(?=\d+\.\s)")
# ```-фенс — дословный контент (логи, код): согласовано с telegram_html.
_FENCE_RE = re.compile(r"^\s*```")


def normalize_list_markers(text: str) -> str:
    """Снять маркер буллета перед нумерованным пунктом («- 1. …» → «1. …»).

    LLM недетерминированно совмещает общее правило «маркер '- '» с полевым
    «НУМЕРОВАННЫЙ "N. …"» — компромисс «- 1. …» каждый канал рендерит как
    буллет + литеральный номер (живой DOCX 23.07). Детерминированный финальный
    проход возвращает строку в канонический вид, включая правильную ветку
    нумерации в рендерах (Word: List Number с рестартом на секцию).

    Содержимое ```-фенсов не трогается — это дословные цитаты (логи, код).
    Осознанный компромисс: буллет, чей текст сам начинается с «N. »
    («- 1. этап миграции…»), синтаксически неотличим от нумерованного пункта
    со случайным маркером — он тоже станет нумерованным.
    """
    lines: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_code = not in_code
            lines.append(line)
            continue
        lines.append(line if in_code else _BULLETED_NUMBER_RE.sub(r"\1", line))
    return "\n".join(lines)


def squeeze_blank_lines(text: str) -> str:
    """Схлопнуть подряд идущие пустые строки до одной («\\n\\n\\n+» → «\\n\\n»).

    Пустые Jinja-ветки шапки оставляют лишние пустые строки перед первым
    заголовком (живой протокол 365). Детерминированный финальный проход;
    содержимое ```-фенсов не трогается.
    """
    out: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out)


def humanize_speaker_labels(text: str) -> Tuple[str, int]:
    """Заменить оставшиеся метки SPEAKER_N на «Участник N».

    Метка диаризации в пересланном «наверх» протоколе — сырой машинный
    вывод (анти-референс PRODUCT.md). Возвращает (текст, число разных
    несопоставленных говорящих) — по счётчику владелец получает пометку.
    """
    numbers = set(_SPEAKER_LABEL_RE.findall(text))
    if not numbers:
        return text, 0
    return _SPEAKER_LABEL_RE.sub(r"Участник \1", text), len(numbers)


def humanize_speaker_labels_for_reader(protocol_text: str, warnings: list) -> str:
    """Финальный проход перед доставкой: SPEAKER_N -> «Участник N» + пометка.

    Единая точка для обоих путей генерации (пайплайн и перегенерация из
    истории): текст пометки владельцу не должен разъезжаться между ними.
    """
    protocol_text, unmapped_count = humanize_speaker_labels(protocol_text)
    if unmapped_count:
        warnings.append(
            "ℹ️ Не всех говорящих удалось сопоставить с именами — "
            "в протоколе они обозначены как «Участник N»."
        )
    return protocol_text


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


