"""
Обработчики callback запросов для сопоставления спикеров с участниками.

Работают с типизированной сессией сопоставления: peek для чтения (смена,
выбор, отмена), атомарный take для подтверждения/пропуска — повторный тап
получает None и не запускает второе возобновление.
"""

from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from loguru import logger

from services import ProcessingService, TemplateService, UserService
from src.services.mapping_session import MappingSession, mapping_sessions
from src.utils.telegram_safe import safe_edit_text
from src.ux.speaker_mapping_ui import update_mapping_message

from .helpers import _safe_callback_answer

_SESSION_GONE_TEXT = (
    "❌ Состояние обработки не найдено или истекло.\n\n"
    "Пожалуйста, начните обработку заново."
)


def _owner_id(callback: CallbackQuery, parts_index: int) -> Optional[int]:
    """Извлечь user_id из callback data и проверить владельца."""
    parts = callback.data.split(":")
    if len(parts) <= parts_index:
        logger.error(f"Неверный формат callback data: {callback.data}")
        return None
    user_id = int(parts[parts_index])
    if callback.from_user.id != user_id:
        return None
    return user_id


async def _show_main_view(callback: CallbackQuery, session: MappingSession,
                          user_id: int, editing_speaker: Optional[str] = None) -> None:
    """Перерисовать карточку сопоставления из типизированной сессии."""
    diarization = session.transcription_result.diarization
    await update_mapping_message(
        callback.message,
        session.speaker_mapping,
        diarization,
        session.request.participants_list or [],
        user_id,
        current_editing_speaker=editing_speaker,
        speakers_text=diarization.speakers_text if diarization else None,
        speakers_with_audio=session.speakers_with_audio,
    )


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    @router.callback_query(F.data.startswith("sm_change:"))
    async def speaker_mapping_change_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик начала изменения сопоставления спикера"""
        try:
            await _safe_callback_answer(callback)

            # Парсим данные: sm_change:{speaker_id}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 3:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            speaker_id = parts[1]
            user_id = _owner_id(callback, 2)
            if user_id is None:
                await callback.answer("❌ Это не ваш запрос")
                return

            session = mapping_sessions.peek(user_id)
            if session is None:
                await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                await callback.answer()
                return

            # Показываем выбор участников для этого спикера
            await _show_main_view(callback, session, user_id, editing_speaker=speaker_id)
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_change_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_select:"))
    async def speaker_mapping_select_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора участника для спикера"""
        try:
            await _safe_callback_answer(callback)

            # Парсим данные: sm_select:{speaker_id}:{participant_idx}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 4:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            speaker_id = parts[1]
            participant_idx_str = parts[2]
            user_id = _owner_id(callback, 3)
            if user_id is None:
                await callback.answer("❌ Это не ваш запрос")
                return

            session = mapping_sessions.peek(user_id)
            if session is None:
                await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                await callback.answer()
                return

            speaker_mapping = session.speaker_mapping.copy()
            participants = session.request.participants_list or []

            # Обрабатываем выбор
            if participant_idx_str == "none":
                # Удаляем сопоставление
                speaker_mapping.pop(speaker_id, None)
                await callback.answer("✅ Сопоставление удалено")
            else:
                try:
                    participant_idx = int(participant_idx_str)
                    if 0 <= participant_idx < len(participants):
                        participant_name = participants[participant_idx].get('name', '')
                        if participant_name:
                            # Допускаем many-to-one: один участник может быть
                            # сопоставлен нескольким спикерам. Диаризация иногда
                            # дробит одного человека на несколько SPEAKER_N, и
                            # пользователю нужно свести их к одному участнику.
                            speaker_mapping[speaker_id] = participant_name
                            await callback.answer("✅ Сопоставление изменено")
                        else:
                            await callback.answer("❌ Имя участника не найдено")
                            return
                    else:
                        await callback.answer("❌ Неверный индекс участника")
                        return
                except ValueError:
                    await callback.answer("❌ Неверный формат индекса")
                    return

            mapping_sessions.update_mapping(user_id, speaker_mapping)

            # Обновляем сообщение (возвращаемся к основному виду)
            await _show_main_view(callback, session, user_id)

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_select_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_cancel:"))
    async def speaker_mapping_cancel_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены редактирования (возврат к основному виду)"""
        try:
            await _safe_callback_answer(callback)

            user_id = _owner_id(callback, 1)
            if user_id is None:
                await callback.answer("❌ Это не ваш запрос")
                return

            session = mapping_sessions.peek(user_id)
            if session is None:
                await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                await callback.answer()
                return

            await _show_main_view(callback, session, user_id)
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_cancel_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_confirm:"))
    async def speaker_mapping_confirm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик подтверждения сопоставления и продолжения обработки"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку...")

            user_id = _owner_id(callback, 1)
            if user_id is None:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Атомарно изымаем сессию: повторный тап получит None
            session = mapping_sessions.take(user_id)
            if session is None:
                await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                return

            # Обновляем сообщение (кратко, без обещаний - реальная обработка начнется в следующем сообщении)
            await safe_edit_text(
                callback.message,
                "✅ **Сопоставление подтверждено**",
                parse_mode="Markdown"
            )

            # Очищаем состояние FSM
            await state.clear()

            # Продолжаем обработку — сессия передаётся владением
            await processing_service.continue_processing_after_mapping_confirmation(
                session=session,
                confirmed_mapping=session.speaker_mapping,
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )

        except Exception as e:
            logger.error(
                f"Ошибка в speaker_mapping_confirm_callback "
                f"({type(e).__name__}): {e}",
                exc_info=True,
            )
            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )

    @router.callback_query(F.data.startswith("sm_skip:"))
    async def speaker_mapping_skip_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик пропуска сопоставления (продолжение без имен)"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку без сопоставления...")

            user_id = _owner_id(callback, 1)
            if user_id is None:
                await callback.answer("❌ Это не ваш запрос")
                return

            session = mapping_sessions.take(user_id)
            if session is None:
                await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                return

            # Обновляем сообщение
            await safe_edit_text(
                callback.message,
                "⏭️ **Сопоставление пропущено**\n\n"
                "⏳ Продолжаю генерацию протокола без замены имен спикеров...",
                parse_mode="Markdown"
            )

            # Очищаем состояние FSM
            await state.clear()

            # Продолжаем обработку с пустым mapping
            await processing_service.continue_processing_after_mapping_confirmation(
                session=session,
                confirmed_mapping={},
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_skip_callback: {e}", exc_info=True)
            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )

    return router
