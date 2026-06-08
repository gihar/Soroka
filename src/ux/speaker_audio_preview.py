"""Оркестратор аудиопревью спикеров.

При показе UI сопоставления присылает по одному фрагменту речи на каждого спикера:
окно выбирается из сегментов диаризации, фрагмент режется из оригинального файла
через ffmpeg и отправляется голосовым сообщением. Если голосовые запрещены у
получателя (VOICE_MESSAGES_FORBIDDEN) — фолбэк на обычный аудиофайл.

Фича вспомогательная: запускается ФОНОВОЙ задачей (``schedule_speaker_audio_previews``)
и не блокирует и не задерживает показ карточки сопоставления; любая ошибка
логируется и проглатывается.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import settings
from src.services.audio_fragment_service import cut_voice_fragment, select_fragment_window
from src.utils.telegram_safe import safe_send_audio, safe_send_voice

_MAX_CAPTION_SNIPPET = 120

# Удерживаем ссылки на фоновые задачи, чтобы их не собрал GC до завершения.
_background_tasks: set = set()


def _preview_dir() -> str:
    """Каталог для временных клипов (тот же temp/, что чистит cleanup_service)."""
    return settings.temp_dir


def _build_caption(speaker_id: str, speakers_text: Optional[Dict[str, str]]) -> str:
    """Подпись фрагмента: '🔊 SPEAKER_N' + короткий однострочный сниппет текста."""
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


async def _send_clip(bot: Any, chat_id: int, clip_path: str, caption: str) -> Optional[Any]:
    """Отправить клип голосовым; при неудаче — фолбэк на обычный аудиофайл.

    Голосовые могут быть запрещены настройками приватности получателя
    (VOICE_MESSAGES_FORBIDDEN). sendAudio под этот запрет не подпадает, поэтому
    получатель всё равно получит фрагмент — как аудиофайл.
    """
    from aiogram.types import FSInputFile

    message = await safe_send_voice(
        bot, chat_id=chat_id, voice=FSInputFile(clip_path),
        caption=caption, parse_mode=None,
    )
    if message is not None:
        return message

    logger.info("Аудиопревью: голосовое не отправлено, фолбэк на аудиофайл")
    return await safe_send_audio(
        bot, chat_id=chat_id, audio=FSInputFile(clip_path),
        caption=caption, parse_mode=None,
    )


async def send_speaker_audio_previews(
    bot: Any,
    chat_id: int,
    user_id: int,
    speakers: List[str],
    diarization_data: Dict[str, Any],
    temp_file_path: Optional[str],
    speakers_text: Optional[Dict[str, str]] = None,
) -> None:
    """Прислать фрагменты речи каждого спикера.

    Никогда не пробрасывает исключения — фича вспомогательная и не должна мешать
    сопоставлению. Обычно запускается через ``schedule_speaker_audio_previews``.
    """
    try:
        if not settings.speaker_audio_preview_enabled:
            return
        if not temp_file_path or not os.path.exists(temp_file_path):
            logger.info("Аудиопревью: исходный файл недоступен, пропускаю превью")
            return

        # Нарезаем все клипы параллельно.
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
                await _send_clip(bot, chat_id, clip, _build_caption(speaker_id, speakers_text))
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


def schedule_speaker_audio_previews(
    bot: Any,
    chat_id: int,
    user_id: int,
    speakers: List[str],
    diarization_data: Dict[str, Any],
    temp_file_path: Optional[str],
    speakers_text: Optional[Dict[str, str]] = None,
) -> Optional[asyncio.Task]:
    """Запланировать отправку аудиопревью ФОНОВОЙ задачей (fire-and-forget).

    Возвращает управление немедленно — НЕ блокирует и не задерживает показ карточки
    сопоставления (в этом и была причина прежней регрессии: встроенный ``await``
    на падающих отправках голосовых стопорил UI). Ссылка на задачу удерживается,
    чтобы её не собрал сборщик мусора до завершения.
    """
    try:
        task = asyncio.create_task(
            send_speaker_audio_previews(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                speakers=speakers,
                diarization_data=diarization_data,
                temp_file_path=temp_file_path,
                speakers_text=speakers_text,
            )
        )
    except RuntimeError as e:
        # Нет активного event loop — в боте не случается; на всякий случай не падаем.
        logger.warning(f"Аудиопревью: не удалось запланировать фоновую задачу: {e}")
        return None

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
