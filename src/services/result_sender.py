"""Delivery of a finished :class:`ProcessingResult` to the user.

Extracted from ``TaskQueueManager`` so that the logic is reusable by any caller
that already holds a result, a chat and a request — without having to fabricate
a throwaway ``QueuedTask`` just to reuse the queue manager (which is what the
speaker-mapping resume path used to do).

The single entry point is :func:`send_result_to_user`. It is intentionally
stateless: everything it needs is passed in explicitly.
"""

import contextlib
import os
import re
import tempfile

from aiogram.types import FSInputFile
from loguru import logger

from src.models.processing import ProcessingRequest, ProcessingResult
from src.services.protocol_render import render_protocol_messages
from src.utils.telegram_safe import safe_send_document, safe_send_message

MAX_MESSAGE_LENGTH = 4000
# Запас под префикс «<i>Часть N/M</i>\n» у многочастных протоколов.
PART_PREFIX_RESERVE = 24


def _build_result_dict(request: ProcessingRequest, result: ProcessingResult) -> dict:
    """Build the dict consumed by ``MessageBuilder.processing_complete_message``."""
    llm_display_name = (
        result.llm_model_used
        if getattr(result, "llm_model_used", None)
        else (
            "OpenAI"
            if result.llm_provider_used == "openai"
            else result.llm_provider_used.capitalize()
        )
    )

    transcription = result.transcription_result
    return {
        "template_used": getattr(result, "template_used", None) or {"name": "Неизвестный"},
        "llm_provider_used": result.llm_provider_used,
        "llm_model_name": llm_display_name,
        "transcription_result": {
            "transcription": transcription.transcription if transcription else "",
            "diarization": transcription.diarization if transcription else None,
            "compression_info": transcription.compression_info if transcription else None,
        },
        "processing_duration": getattr(result, "processing_duration", None),
        "speaker_mapping": getattr(request, "speaker_mapping", None),
    }




async def _send_summary_message(bot, chat_id: int, result_message: str) -> None:
    """Send the summary message, degrading gracefully to a plain notification."""
    try:
        sent_message = await safe_send_message(
            bot, chat_id, text=result_message, parse_mode="HTML"
        )
        if not sent_message:
            logger.warning("Не удалось отправить результат (возможен flood control)")
            await safe_send_message(
                bot, chat_id,
                text="✅ Протокол готов",
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке результата: {e}")
        try:
            await safe_send_message(
                bot, chat_id,
                text="✅ Протокол готов",
            )
        except Exception:
            pass


def _protocol_file_name(protocol_text: str, source_file_name: str) -> str:
    """Имя файла протокола: название встречи из первого заголовка.

    Файл пересылают дальше — «Дейли команды.pdf» читается, «voice_message_123.pdf»
    выдаёт происхождение. Фолбэк — имя исходного файла записи.
    """
    title = ""
    for line in protocol_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break

    if title:
        title = re.sub(r'[\\/:*?"<>|]', " ", title)
        title = re.sub(r"\s+", " ", title).strip()[:60].strip()
    if title:
        return title

    return os.path.splitext(os.path.basename(source_file_name))[0][:40] or "protocol"


async def _send_protocol_as_file(bot, chat_id: int, request: ProcessingRequest,
                                 protocol_text: str, output_mode: str) -> bool:
    """Render and send the protocol as a downloadable ``.md``/``.pdf`` document.

    Returns ``True`` only when the document was actually delivered.
    """
    suffix = ".pdf" if output_mode == "pdf" else ".md"
    safe_name = _protocol_file_name(protocol_text, request.file_name)

    if output_mode == "pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
            temp_path = pdf_file.name
        try:
            from src.utils.pdf_converter import convert_markdown_to_pdf_async
            await convert_markdown_to_pdf_async(protocol_text, temp_path)
        except Exception as e:
            logger.error(f"Ошибка конвертации в PDF: {e}")
            # Fall back to a markdown file when PDF conversion fails. The temp
            # file may already be gone — cleanup must not kill the fallback.
            with contextlib.suppress(OSError):
                os.remove(temp_path)
            suffix = ".md"
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, encoding="utf-8"
            ) as md_file:
                temp_path = md_file.name
                md_file.write(protocol_text)
    else:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        ) as f:
            temp_path = f.name
            f.write(protocol_text)

    try:
        input_file = FSInputFile(temp_path, filename=f"{safe_name}{suffix}")
        sent = await safe_send_document(bot, chat_id, document=input_file)
        if not sent:
            logger.warning("Документ протокола не был доставлен (flood control?)")
            return False
        return True
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def _send_protocol_as_messages(bot, chat_id: int, protocol_text: str) -> bool:
    """Send the protocol inline as Telegram HTML, split on section boundaries.

    The canonical protocol text is Markdown; legacy parse_mode="Markdown" would
    show literal ##/** markers, so the chat channel renders it to HTML.
    Returns ``True`` only when every part was delivered.
    """
    parts = render_protocol_messages(
        protocol_text, max_length=MAX_MESSAGE_LENGTH - PART_PREFIX_RESERVE
    )
    if not parts:
        # Протокол из одной markdown-разметки (например, только «---»)
        # рендерится в ноль сообщений — молчание не считается доставкой.
        logger.warning("Протокол отрендерился в пустой список сообщений")
        return False
    total = len(parts)
    delivered = True
    for index, part in enumerate(parts, start=1):
        text = f"<i>Часть {index}/{total}</i>\n{part}" if total > 1 else part
        sent = await safe_send_message(bot, chat_id, text=text, parse_mode="HTML")
        if not sent:
            logger.warning(f"Часть протокола {index}/{total} не доставлена (flood control?)")
            delivered = False
    return delivered


async def send_result_to_user(
    bot,
    chat_id: int,
    user_id: int,
    request: ProcessingRequest,
    result: ProcessingResult,
    progress_tracker=None,
) -> bool:
    """Send a finished processing result to the user.

    Handles the summary message and the protocol body, respecting the user's
    ``protocol_output_mode`` (messages / file / pdf). Errors are reported to the
    user and the progress tracker but never re-raised — delivery is best-effort.

    Returns ``True`` only when the protocol BODY was delivered, ``False`` when it
    was not (empty protocol, or the body send raised). Callers use this to avoid
    recording a task as completed / caching a result that the user never got.
    The summary message is cosmetic and does not affect the return value.
    """
    try:
        # Lazy imports: avoid pulling the whole src.ux package at module import
        # time (keeps result_sender importable in isolation / in unit tests).
        from src.services.user_service import UserService
        from src.ux.message_builder import MessageBuilder

        user_service = UserService()
        user = await user_service.get_user_by_telegram_id(user_id)
        output_mode = getattr(user, "protocol_output_mode", None) or "messages"

        # Пустой протокол проверяется ДО сводки: «✅ Протокол готов» с последующим
        # «❌ не получился» — противоречащие друг другу статусы подряд.
        if not result.protocol_text:
            logger.warning("protocol_text пустой или None")
            await safe_send_message(
                bot, chat_id,
                text=(
                    "❌ Протокол не получился: модель не вернула текст.\n"
                    "Отправьте запись ещё раз — обычно повторная попытка помогает."
                ),
            )
            return False

        result_message = MessageBuilder.processing_complete_message(
            _build_result_dict(request, result)
        )
        await _send_summary_message(bot, chat_id, result_message)

        if output_mode in ("file", "pdf"):
            delivered = await _send_protocol_as_file(
                bot, chat_id, request, result.protocol_text, output_mode
            )
        else:
            delivered = await _send_protocol_as_messages(
                bot, chat_id, result.protocol_text
            )

        if not delivered:
            await safe_send_message(
                bot, chat_id,
                text=(
                    "⚠️ Протокол доставлен не полностью.\n"
                    "Отправьте запись ещё раз или выберите формат файла в /settings."
                ),
            )
        return delivered

    except Exception as e:
        logger.error(f"Ошибка отправки результата: {e}")
        if progress_tracker:
            try:
                await progress_tracker.error(
                    "analysis", f"Ошибка отправки результата: {str(e)}"
                )
            except Exception as tracker_error:
                logger.error(f"Ошибка обновления прогресс-трекера: {tracker_error}")
        try:
            await safe_send_message(
                bot, chat_id,
                text=(
                    "❌ Не удалось отправить протокол.\n"
                    "Попробуйте ещё раз или выберите другой формат вывода в /settings."
                ),
            )
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")
        return False
