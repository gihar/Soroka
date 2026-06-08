"""Оркестратор аудиопревью спикеров.

При показе UI сопоставления присылает по одному голосовому сообщению на каждого
спикера: окно выбирается из сегментов диаризации, фрагмент режется из оригинального
файла через ffmpeg и отправляется как voice. Фича вспомогательная — любая ошибка
логируется и проглатывается, сопоставление это не ломает.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import settings
from src.services.audio_fragment_service import cut_voice_fragment, select_fragment_window
from src.utils.telegram_safe import safe_send_voice

_MAX_CAPTION_SNIPPET = 120


def _preview_dir() -> str:
    """Каталог для временных клипов (тот же temp/, что чистит cleanup_service)."""
    return settings.temp_dir


def _build_caption(speaker_id: str, speakers_text: Optional[Dict[str, str]]) -> str:
    """Подпись голосового: '🔊 SPEAKER_N' + короткий однострочный сниппет текста."""
    caption = f"🔊 {speaker_id}"
    if speakers_text:
        text = (speakers_text.get(speaker_id) or "").strip().replace("\n", " ")
        if text:
            snippet = text[:_MAX_CAPTION_SNIPPET]
            if len(text) > _MAX_CAPTION_SNIPPET:
                snippet += "…"
            caption = f"{caption}\n«{snippet}»"
    return caption


async def _prepare_clip(
    speaker_id: str,
    diarization_data: Dict[str, Any],
    temp_file_path: str,
    user_id: int,
) -> Optional[str]:
    """Выбрать окно и вырезать клип спикера. Возвращает путь к .ogg или None."""
    segments = diarization_data.get("segments", [])
    window = select_fragment_window(
        segments,
        speaker_id,
        max_seconds=float(settings.speaker_preview_max_seconds),
        min_segment_seconds=float(settings.speaker_preview_min_segment_seconds),
    )
    if window is None:
        logger.debug(f"Аудиопревью: нет окна для {speaker_id}, пропускаю")
        return None

    start, duration = window
    out_path = os.path.join(_preview_dir(), f"preview_{user_id}_{speaker_id}.ogg")

    ok = await cut_voice_fragment(
        temp_file_path, start, duration, out_path,
        bitrate=settings.speaker_preview_bitrate,
    )
    if not ok:
        logger.warning(f"Аудиопревью: не удалось вырезать клип для {speaker_id}")
        return None
    return out_path


async def send_speaker_audio_previews(
    bot: Any,
    chat_id: int,
    user_id: int,
    speakers: List[str],
    diarization_data: Dict[str, Any],
    temp_file_path: Optional[str],
    speakers_text: Optional[Dict[str, str]] = None,
) -> None:
    """Прислать голосовые фрагменты речи каждого спикера.

    Никогда не пробрасывает исключения — фича вспомогательная и не должна мешать
    показу UI сопоставления.
    """
    try:
        if not settings.speaker_audio_preview_enabled:
            return
        if not temp_file_path or not os.path.exists(temp_file_path):
            logger.info("Аудиопревью: исходный файл недоступен, пропускаю превью")
            return

        # Нарезаем все клипы параллельно, чтобы не задерживать показ UI.
        from aiogram.types import FSInputFile

        clip_paths = await asyncio.gather(
            *[
                _prepare_clip(speaker_id, diarization_data, temp_file_path, user_id)
                for speaker_id in speakers
            ],
            return_exceptions=True,
        )

        # Отправляем по порядку спикеров; каждый клип удаляем сразу после отправки.
        for speaker_id, clip in zip(speakers, clip_paths):
            if isinstance(clip, Exception):
                logger.warning(f"Аудиопревью: ошибка подготовки клипа {speaker_id}: {clip}")
                continue
            if not clip:
                continue
            try:
                await safe_send_voice(
                    bot,
                    chat_id=chat_id,
                    voice=FSInputFile(clip),
                    caption=_build_caption(speaker_id, speakers_text),
                    parse_mode=None,
                )
            except Exception as send_error:
                logger.warning(f"Аудиопревью: ошибка отправки {speaker_id}: {send_error}")
            finally:
                try:
                    if os.path.exists(clip):
                        os.remove(clip)
                except OSError as rm_error:
                    logger.debug(f"Аудиопревью: не удалось удалить клип {clip}: {rm_error}")

    except Exception as e:
        logger.error(f"Аудиопревью: непредвиденная ошибка, пропускаю превью: {e}", exc_info=True)
