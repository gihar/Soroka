"""
Обработчики callback запросов для сопоставления спикеров с участниками.

Работают с типизированной сессией сопоставления: peek для чтения (смена,
выбор, отмена), атомарный take для подтверждения/пропуска — повторный тап
получает None и не запускает второе возобновление.
"""

from typing import Callable, Optional

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.handlers.participants_states import SpeakerNameInput
from src.services import ProcessingService, TemplateService, UserService
from src.services.mapping_session import MappingSession, mapping_sessions
from src.services.participants_service import participants_service
from src.utils.telegram_safe import safe_edit_text
from src.ux.card_sender import edit_card
from src.ux.speaker_mapping_callback_data import (
    SmCancel,
    SmChange,
    SmConfirm,
    SmCustom,
    SmSelect,
    SmSkip,
)
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

_PROCESSING_ERROR_TEXT = (
    "❌ Произошла ошибка при продолжении обработки.\n\n"
    "Пожалуйста, попробуйте начать обработку заново."
)


def card_handler(
    *,
    session: Optional[str] = None,
    answer_text: Optional[str] = None,
    on_error: str = "answer",
    clear_state: bool = False,
) -> Callable:
    """Каркас callback-хендлера Карточки сопоставления.

    Снимает с тела повторяющуюся обвязку и оставляет ему предметную суть.
    Тело: ``async core(callback, callback_data, state, user_id, session)`` —
    ``session`` равен ``None``, когда режим сессии не задан.

    Args:
        session: ``"peek"`` (читать, не изымая), ``"take"`` (атомарно изъять —
            двойной тап получит None) или ``None`` (сессия телу не нужна).
        answer_text: текст ответа на callback (тост/снятие «загрузки»).
        on_error: ``"answer"`` — тост «Произошла ошибка»; ``"edit"`` — правка
            сообщения текстом об ошибке продолжения обработки.
        clear_state: очистить FSM-состояние до разрешения сессии (отмена из
            под-вида ручного ввода имени не должна оставлять ловлю имени).
    """

    def decorator(core: Callable) -> Callable:
        async def wrapper(callback: CallbackQuery, callback_data, state: FSMContext) -> None:
            try:
                user_id = callback_data.user_id
                if callback.from_user.id != user_id:
                    await _safe_callback_answer(callback, "❌ Это не ваш запрос")
                    return

                await _safe_callback_answer(callback, answer_text)

                if clear_state:
                    await state.clear()

                current_session = None
                if session == "peek":
                    current_session = mapping_sessions.peek(user_id)
                elif session == "take":
                    current_session = mapping_sessions.take(user_id)

                if session is not None and current_session is None:
                    await safe_edit_text(callback.message, _SESSION_GONE_TEXT)
                    return

                await core(callback, callback_data, state, user_id, current_session)

            except Exception as e:
                logger.error(f"Ошибка в {core.__name__}: {e}", exc_info=True)
                if on_error == "edit":
                    await safe_edit_text(callback.message, _PROCESSING_ERROR_TEXT)
                else:
                    await _safe_callback_answer(callback, "❌ Произошла ошибка")

        wrapper.__name__ = core.__name__
        return wrapper

    return decorator


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


@card_handler(session="peek")
async def request_custom_speaker_name(
    callback: CallbackQuery, callback_data: SmCustom, state: FSMContext,
    user_id: int, session: MappingSession,
) -> None:
    """sm_custom: перейти в ожидание имени спикера, введённого вручную.

    Каркас проверил владельца и прочитал сессию (peek). Тело переводит FSM в
    ожидание имени с {speaker_id, user_id} и перерисовывает карточку в под-вид
    «Отправьте имя для SPEAKER_N сообщением» с кнопкой «◀️ Отмена».
    """
    speaker_id = callback_data.speaker_id
    await state.set_state(SpeakerNameInput.waiting)
    await state.update_data(speaker_id=speaker_id, user_id=user_id)

    # Под-вид ожидания имени идёт тем же отправителем карточек (ADR-0005).
    await edit_card(
        callback.message,
        format_name_prompt_message(speaker_id),
        create_name_prompt_keyboard(user_id),
    )


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


@card_handler(session="peek", clear_state=True)
async def speaker_mapping_cancel_callback(
    callback: CallbackQuery, callback_data: SmCancel, state: FSMContext,
    user_id: int, session: MappingSession,
) -> None:
    """sm_cancel: вернуться к основному виду карточки.

    Каркас с ``clear_state=True`` очищает FSM-состояние ожидания имени до
    разрешения сессии: отмена из под-вида ручного ввода не должна оставлять
    пользователя в ловле имени (следующее сообщение ушло бы в хендлер имени
    вместо обычной обработки). Из под-вида выбора участника состояние не
    задано — clear безвреден.
    """
    await _show_main_view(callback, session, user_id)


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    # Ручной ввод имени спикера (ADR-0002): callback перехода в ожидание имени
    # и message-хендлер приёма имени. Роутер сопоставления включён раньше общего
    # message_router (см. bot.py), а общий текстовый хендлер стоит на
    # StateFilter(None) — коллизии за текст в состоянии ожидания имени нет.
    router.callback_query(SmCustom.filter())(request_custom_speaker_name)
    router.message(StateFilter(SpeakerNameInput.waiting))(receive_custom_speaker_name)

    @router.callback_query(SmChange.filter())
    @card_handler(session="peek")
    async def speaker_mapping_change_callback(
        callback: CallbackQuery, callback_data: SmChange, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_change: показать под-вид выбора участника для спикера."""
        await _show_main_view(
            callback, session, user_id, editing_speaker=callback_data.speaker_id
        )

    @router.callback_query(SmSelect.filter())
    @card_handler(session="peek")
    async def speaker_mapping_select_callback(
        callback: CallbackQuery, callback_data: SmSelect, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_select: применить выбор участника (или снять имя) и вернуться к виду."""
        speaker_id = callback_data.speaker_id
        participant_idx_str = callback_data.participant_idx

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

    router.callback_query(SmCancel.filter())(speaker_mapping_cancel_callback)

    @router.callback_query(SmConfirm.filter())
    @card_handler(session="take", answer_text="⏳ Продолжаю обработку...", on_error="edit")
    async def speaker_mapping_confirm_callback(
        callback: CallbackQuery, callback_data: SmConfirm, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_confirm: подтвердить сопоставление и продолжить обработку.

        Каркас атомарно изъял сессию (take): повторный тап получил бы None и не
        запустил второе возобновление.
        """
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

    @router.callback_query(SmSkip.filter())
    @card_handler(
        session="take",
        answer_text="⏳ Продолжаю обработку без сопоставления...",
        on_error="edit",
    )
    async def speaker_mapping_skip_callback(
        callback: CallbackQuery, callback_data: SmSkip, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_skip: пропустить сопоставление и продолжить без замены имён."""
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

    return router
