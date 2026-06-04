"""Delivery of a finished :class:`ProcessingResult` to the user.

Extracted from ``TaskQueueManager`` so that the logic is reusable by any caller
that already holds a result, a chat and a request — without having to fabricate
a throwaway ``QueuedTask`` just to reuse the queue manager (which is what the
speaker-mapping resume path used to do).

The single entry point is :func:`send_result_to_user`. It is intentionally
stateless: everything it needs is passed in explicitly.
"""

import os
import tempfile

from aiogram.types import FSInputFile
from loguru import logger

from src.models.processing import ProcessingRequest, ProcessingResult
from src.utils.telegram_safe import safe_send_document, safe_send_message

MAX_MESSAGE_LENGTH = 4000


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


def _split_protocol_text(protocol_text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long protocol into message-sized parts on line boundaries."""
    parts: list[str] = []
    current_part = ""
    for line in protocol_text.split("\n"):
        if len(current_part) + len(line) + 1 <= max_length:
            current_part += line + "\n"
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + "\n"
    if current_part:
        parts.append(current_part.strip())
    return parts


async def _send_summary_message(bot, chat_id: int, result_message: str) -> None:
    """Send the summary message, degrading gracefully to a plain notification."""
    try:
        sent_message = await safe_send_message(
            bot, chat_id, text=result_message, parse_mode="Markdown"
        )
        if not sent_message:
            logger.warning("Не удалось отправить результат (возможен flood control)")
            await safe_send_message(
                bot, chat_id,
                text="✅ Протокол успешно создан! Файл отправляется ниже...",
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке результата: {e}")
        try:
            await safe_send_message(
                bot, chat_id,
                text="✅ Протокол успешно создан! Файл отправляется ниже...",
            )
        except Exception:
            pass


async def _send_protocol_as_file(bot, chat_id: int, request: ProcessingRequest,
                                 protocol_text: str, output_mode: str) -> None:
    """Render and send the protocol as a downloadable ``.md``/``.pdf`` document."""
    suffix = ".pdf" if output_mode == "pdf" else ".md"
    safe_name = os.path.splitext(os.path.basename(request.file_name))[0][:40] or "protocol"

    if output_mode == "pdf":
        temp_path = tempfile.mktemp(suffix=".pdf")
        try:
            from src.utils.pdf_converter import convert_markdown_to_pdf_async
            await convert_markdown_to_pdf_async(protocol_text, temp_path)
        except Exception as e:
            logger.error(f"Ошибка конвертации в PDF: {e}")
            # Fall back to a markdown file when PDF conversion fails.
            temp_path = tempfile.mktemp(suffix=".md")
            suffix = ".md"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(protocol_text)
    else:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        ) as f:
            temp_path = f.name
            f.write(protocol_text)

    try:
        input_file = FSInputFile(temp_path, filename=f"{safe_name}{suffix}")
        await safe_send_document(
            bot, chat_id, document=input_file, caption="📄 Протокол готов!"
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def _send_protocol_as_messages(bot, chat_id: int, protocol_text: str) -> None:
    """Send the protocol inline, splitting into parts when it exceeds the limit."""
    if len(protocol_text) <= MAX_MESSAGE_LENGTH:
        await safe_send_message(bot, chat_id, text=protocol_text, parse_mode="Markdown")
        return

    parts = _split_protocol_text(protocol_text)
    for i, part in enumerate(parts):
        header = f"📄 **Протокол встречи** (часть {i + 1}/{len(parts)})\n\n"
        await safe_send_message(bot, chat_id, text=header + part, parse_mode="Markdown")


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

        result_message = MessageBuilder.processing_complete_message(
            _build_result_dict(request, result)
        )
        await _send_summary_message(bot, chat_id, result_message)

        if not result.protocol_text:
            logger.warning("protocol_text пустой или None")
            await safe_send_message(bot, chat_id, text="❌ Протокол не был сгенерирован")
            return False

        if output_mode in ("file", "pdf"):
            await _send_protocol_as_file(
                bot, chat_id, request, result.protocol_text, output_mode
            )
        else:
            await _send_protocol_as_messages(bot, chat_id, result.protocol_text)

        return True

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
                bot, chat_id, text=f"❌ Ошибка при отправке результата: {str(e)}"
            )
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")
        return False
