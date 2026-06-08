"""Выбор окна и нарезка короткого аудиофрагмента речи спикера.

Чистая логика выбора (``select_fragment_window``) отделена от ввода-вывода
(``cut_voice_fragment``) — первую легко тестировать без ffmpeg.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


def _segment_duration(segment: Dict[str, Any]) -> Optional[float]:
    """Длительность сегмента в секундах или None, если таймстампы невалидны."""
    start = segment.get("start")
    end = segment.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    duration = float(end) - float(start)
    if duration <= 0:
        return None
    return duration


def select_fragment_window(
    segments: List[Dict[str, Any]],
    speaker_id: str,
    *,
    max_seconds: float = 15.0,
    min_segment_seconds: float = 1.5,
) -> Optional[Tuple[float, float]]:
    """Выбрать окно (start, duration) для голосового фрагмента спикера.

    Берёт сегменты спикера по возрастанию ``start``. Начинает фрагмент с первого
    «весомого» сегмента (длиннее ``min_segment_seconds``); если таких нет — с самого
    первого валидного сегмента спикера. Длительность ограничена ``max_seconds``
    (ffmpeg сам остановится на конце файла, если запись короче).

    Возвращает None, если у спикера нет сегментов с валидными таймстампами.
    Не мутирует входные данные.
    """
    speaker_segments = [
        s for s in segments
        if s.get("speaker") == speaker_id and _segment_duration(s) is not None
    ]
    if not speaker_segments:
        return None

    speaker_segments = sorted(speaker_segments, key=lambda s: float(s["start"]))

    weighty = next(
        (s for s in speaker_segments if (_segment_duration(s) or 0) >= min_segment_seconds),
        None,
    )
    chosen = weighty if weighty is not None else speaker_segments[0]

    return (float(chosen["start"]), float(max_seconds))


async def cut_voice_fragment(
    src_path: str,
    start: float,
    duration: float,
    out_path: str,
    *,
    bitrate: str = "32k",
) -> bool:
    """Вырезать фрагмент [start, start+duration] из src_path в OGG/Opus (out_path).

    Использует ffmpeg через ``asyncio.create_subprocess_exec`` — не блокирует
    event loop. ``-ss`` стоит ДО ``-i`` для быстрого seek; ``-vn`` отбрасывает
    видеодорожку (исходник может быть .mp4/.mov).

    Возвращает True при успехе (код возврата 0 и непустой выходной файл), иначе
    False. Исключения не пробрасывает.
    """
    if not os.path.exists(src_path):
        logger.warning(f"cut_voice_fragment: исходный файл не найден: {src_path}")
        return False

    cmd = [
        "ffmpeg",
        "-ss", str(start),
        "-i", src_path,
        "-t", str(duration),
        "-vn",
        "-ac", "1",
        "-c:a", "libopus",
        "-b:a", bitrate,
        "-y",
        out_path,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            logger.error(f"cut_voice_fragment: ffmpeg вернул {process.returncode}: {err[-500:]}")
            return False

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.error(f"cut_voice_fragment: пустой/отсутствующий выход: {out_path}")
            return False

        return True

    except Exception as e:
        logger.error(f"cut_voice_fragment: ошибка запуска ffmpeg: {e}")
        return False
