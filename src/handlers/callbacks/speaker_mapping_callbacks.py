"""
Обработчики callback запросов для сопоставления спикеров с участниками.

Работают с типизированной сессией сопоставления: peek для чтения (смена,
выбор, отмена), атомарный take для подтверждения/пропуска — повторный тап
получает None и не запускает второе возобновление.
"""

from typing import Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from services import ProcessingService, TemplateService, UserService
from src.handlers.participants_states import SpeakerNameInput
from src.services.mapping_session import MappingSession, mapping_sessions
from src.services.participants_service import participants_service
from src.utils.telegram_safe import safe_edit_text
from src.ux.speaker_mapping_ui import (
    create_name_prompt_keyboard,
    format_name_prompt_message,
    update_mapping_message,
)

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


async def request_custom_speaker_name(callback: CallbackQuery, state: FSMContext) -> None:
    """sm_custom: перейти в ожидание имени спикера, введённого вручную.

    Проверяет владельца, читает сессию (peek), устанавливает FSM-состояние
    ожидания имени с {speaker_id, user_id} и перерисовывает карточку в под-вид
    «Отправьте имя для SPEAKER_N сообщением» с кнопкой «◀️ Отмена».
    """
    try:
        await _safe_callback_answer(callback)

        # Парсим данные: sm_custom:{speaker_id}:{user_id}
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

        await state.set_state(SpeakerNameInput.waiting)
        await state.update_data(speaker_id=speaker_id, user_id=user_id)

        await safe_edit_text(
            callback.message,
            format_name_prompt_message(speaker_id),
            parse_mode=None,
            reply_markup=create_name_prompt_keyboard(user_id),
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в request_custom_speaker_name: {e}", exc_info=True)
        await _safe_callback_answer(callback, "❌ Произошла ошибка")


async def _redraw_main_card_after_naming(
    session: MappingSession, user_id: int, fallback_message: Message
) -> None:
    """Перерисовать главный вид карточки после ручного ввода имени.

    Карточка — отдельное сообщение (``session.confirmation_message``): правим её
    на месте, чтобы новый участник сразу стал доступен кнопкой для остальных
    спикеров. Если ссылки на карточку нет — отправляем свежую.
    """
    diarization = session.transcription_result.diarization
    participants = session.request.participants_list or []
    speakers_text = diarization.speakers_text if diarization else None
    card = session.confirmation_message

    if card is not None:
        await update_mapping_message(
            card,
            session.speaker_mapping,
            diarization,
            participants,
            user_id,
            current_editing_speaker=None,
            speakers_text=speakers_text,
            speakers_with_audio=session.speakers_with_audio,
        )
        return

    from src.ux.speaker_mapping_ui import show_mapping_confirmation
    session.confirmation_message = await show_mapping_confirmation(
        bot=fallback_message.bot,
        chat_id=fallback_message.chat.id,
        user_id=user_id,
        speaker_mapping=session.speaker_mapping,
        diarization=diarization,
        participants=participants,
        speakers_text=speakers_text,
        speakers_with_audio=session.speakers_with_audio,
    )


async def receive_custom_speaker_name(message: Message, state: FSMContext) -> None:
    """Сообщение с именем спикера в состоянии ожидания имени.

    Валидное имя → полноценный участник сессии и сопоставление спикера,
    состояние очищается, карточка перерисовывается главным видом. Невалидное —
    мягко переспрашиваем, остаёмся в состоянии. Нет сессии — сообщение об
    истёкшем состоянии.
    """
    try:
        data = await state.get_data()
        speaker_id = data.get("speaker_id")
        user_id = data.get("user_id")

        session = mapping_sessions.peek(user_id) if user_id is not None else None
        if session is None:
            await state.clear()
            await message.answer(_SESSION_GONE_TEXT)
            return

        # Не-текстовый контент (голосовое/аудио/видео/документ/фото/стикер):
        # message.text is None. Не трактуем как «слишком короткое имя» и не теряем
        # запись молча — остаёмся в состоянии и точечно просим прислать имя текстом.
        if not message.text:
            await message.answer(
                "Отправьте имя спикера текстом или нажмите «◀️ Отмена»."
            )
            return

        new_list, display_name = participants_service.add_manual_participant(
            session.request.participants_list, message.text
        )
        if new_list is None:
            await message.answer(
                "Имя должно быть не короче 2 символов и не начинаться с «/».\n"
                "Отправьте имя ещё раз или нажмите «Отмена»."
            )
            return

        session.request.participants_list = new_list
        new_mapping = dict(session.speaker_mapping)
        if speaker_id:
            new_mapping[speaker_id] = display_name
        mapping_sessions.update_mapping(user_id, new_mapping)

        await state.clear()

        await _redraw_main_card_after_naming(session, user_id, message)

    except Exception as e:
        logger.error(f"Ошибка в receive_custom_speaker_name: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке имени.")


async def speaker_mapping_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """sm_cancel: вернуться к основному виду карточки.

    Также очищает FSM-состояние ожидания имени: отмена из под-вида ручного
    ввода не должна оставлять пользователя в ловле имени (следующее сообщение
    ушло бы в хендлер имени вместо обычной обработки). Из под-вида выбора
    участника состояние не задано — clear безвреден.
    """
    try:
        await _safe_callback_answer(callback)

        user_id = _owner_id(callback, 1)
        if user_id is None:
            await callback.answer("❌ Это не ваш запрос")
            return

        await state.clear()

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


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    # Ручной ввод имени спикера (ADR-0002): callback перехода в ожидание имени
    # и message-хендлер приёма имени. Роутер сопоставления включён раньше общего
    # message_router (см. bot.py), а общий текстовый хендлер стоит на
    # StateFilter(None) — коллизии за текст в состоянии ожидания имени нет.
    router.callback_query(F.data.startswith("sm_custom:"))(request_custom_speaker_name)
    router.message(StateFilter(SpeakerNameInput.waiting))(receive_custom_speaker_name)

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

    router.callback_query(F.data.startswith("sm_cancel:"))(speaker_mapping_cancel_callback)

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
