"""Компактная диагностика реквизитов встречи в логах.

Реквизиты (участники, тема, дата, повестка, проекты) — необязательные: часть
встреч приходит вообще без них, и это исправный сценарий. Раньше каждый путь
логировал их своей копией блока на 12 строк, а отсутствие необязательного поля
поднимал до ``WARNING`` («НЕ ПЕРЕДАН!»), — ложная тревога вытесняла из логов
настоящие ошибки. Здесь одна строка на запрос и только факты: незаданное поле
просто не упоминается.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

_MAX_TOPIC_CHARS = 60


def _topic_fragment(meeting_topic: str) -> str:
    topic = meeting_topic.strip()
    if len(topic) > _MAX_TOPIC_CHARS:
        topic = f"{topic[:_MAX_TOPIC_CHARS].rstrip()}…"
    return f"тема «{topic}»"


def log_meeting_inputs(
    stage: str,
    *,
    participants_list: Optional[List[Dict[str, Any]]] = None,
    meeting_topic: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_time: Optional[str] = None,
    meeting_agenda: Optional[str] = None,
    project_list: Optional[str] = None,
    speaker_mapping: Optional[Dict[str, str]] = None,
) -> None:
    """Залогировать одной строкой, какие реквизиты встречи дошли до ``stage``.

    ``stage`` — человекочитаемая точка пути («очередь (callback)», «обработка»),
    чтобы по логу было видно, на каком стыке реквизит потерялся, если это
    случится. Пустые значения опускаются; когда не задано ничего — «не заданы».
    """
    parts: List[str] = []

    if participants_list:
        parts.append(f"участники: {len(participants_list)}")
    if meeting_topic and meeting_topic.strip():
        parts.append(_topic_fragment(meeting_topic))
    if meeting_date and str(meeting_date).strip():
        parts.append(f"дата: {meeting_date}")
    if meeting_time and str(meeting_time).strip():
        parts.append(f"время: {meeting_time}")
    if meeting_agenda and meeting_agenda.strip():
        parts.append("повестка: есть")
    if project_list and project_list.strip():
        parts.append("проекты: есть")
    if speaker_mapping:
        parts.append(f"сопоставление: {len(speaker_mapping)}")

    summary = ", ".join(parts) if parts else "не заданы"
    logger.info(f"Реквизиты встречи [{stage}]: {summary}")
