"""
Обработчики callback запросов для сопоставления спикеров с участниками.

Работают с типизированной сессией сопоставления: peek для чтения (смена,
выбор, отмена), атомарный take для подтверждения/пропуска — повторный тап
получает None и не запускает второе возобновление.
"""

from typing import Callable, Optional

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.services import ProcessingService, TemplateService, UserService
from src.services.mapping_session import (
    MappingSession,
    mapping_sessions,
    name_wait_registry,
)
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
    SmSkipConfirm,
)
from src.ux.speaker_mapping_ui import (
    create_name_prompt_keyboard,
    create_skip_confirm_keyboard,
    format_name_prompt_message,
    format_skip_confirm_message,
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


_SKIP_CONTINUED_TEXT = (
    "⏭️ **Сопоставление пропущено**\n\n"
    "⏳ Продолжаю генерацию протокола без замены имен спикеров..."
)


def _skip_needs_confirmation(session: MappingSession) -> bool:
    """Стоит ли перед пропуском переспросить.

    Трение оправдано только когда цена пропуска видна: быстрый прогон без
    переданного списка участников, где ни один спикер не назван — все уйдут в
    протокол метками «Участник N» молча (кейс 356). Если список передавали или
    хоть кто-то назван — пропуск продолжается сразу, без лишнего шага.
    """
    has_participants = bool(session.request.participants_list)
    has_any_name = bool(session.speaker_mapping)
    return not has_participants and not has_any_name


async def _finish_skip(
    callback: CallbackQuery,
    state: FSMContext,
    session: MappingSession,
    processing_service: ProcessingService,
) -> None:
    """Финал пустого пропуска: правка сообщения, очистка FSM, генерация без имён.

    Общий хвост прямого пропуска без трения и подтверждённого пропуска
    (``sm_skipok``). Сессия уже изъята вызывающим (take) — здесь только продолжаем
    обработку с пустым сопоставлением.
    """
    await safe_edit_text(
        callback.message, _SKIP_CONTINUED_TEXT, parse_mode="Markdown"
    )
    await state.clear()
    name_wait_registry.clear(session.request.user_id)
    await processing_service.continue_processing_after_mapping_confirmation(
        session=session,
        confirmed_mapping={},
        bot=callback.bot,
        chat_id=callback.message.chat.id,
    )


async def _skip_or_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user_id: int,
    session: MappingSession,
    processing_service: ProcessingService,
) -> None:
    """Тело ``sm_skip``: развилка пропуска.

    Цена пропуска видна (пустой прогон без списка, никто не назван) → показываем
    под-вид подтверждения тем же отправителем карточек, сессию НЕ изымаем (peek):
    продолжение — только после явного «Да, продолжить». Цены нет → продолжаем
    сразу; атомарный take даёт защиту двойного тапа — второй тап получит None и
    тихо выйдет.
    """
    if _skip_needs_confirmation(session):
        await edit_card(
            callback.message,
            format_skip_confirm_message(),
            create_skip_confirm_keyboard(user_id),
        )
        return

    taken = mapping_sessions.take(user_id)
    if taken is None:
        return
    await _finish_skip(callback, state, taken, processing_service)


def card_handler(
    *,
    session: Optional[str] = None,
    answer_text: Optional[str] = None,
    on_error: str = "answer",
    clear_name_wait: bool = False,
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
        clear_name_wait: снять признак ожидания имени до разрешения сессии
            (отмена из под-вида ручного ввода не должна оставлять ловлю имени —
            следующее сообщение ушло бы в хендлер имени вместо обычной обработки).
    """

    def decorator(core: Callable) -> Callable:
        async def wrapper(callback: CallbackQuery, callback_data, state: FSMContext) -> None:
            try:
                user_id = callback_data.user_id
                if callback.from_user.id != user_id:
                    await _safe_callback_answer(callback, "❌ Это не ваш запрос")
                    return

                await _safe_callback_answer(callback, answer_text)

                if clear_name_wait:
                    name_wait_registry.clear(user_id)

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

    Каркас проверил владельца и прочитал сессию (peek). Тело отмечает в реестре
    ожидания, что пользователь вводит имя для этого спикера, и перерисовывает
    карточку в под-вид «Отправьте имя для SPEAKER_N сообщением» с «◀️ Отмена».
    """
    speaker_id = callback_data.speaker_id
    name_wait_registry.mark(user_id, speaker_id)

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


async def receive_custom_speaker_name(message: Message) -> None:
    """Сообщение с именем спикера, пока пользователь ждёт ручной ввод (реестр).

    Валидное имя → полноценный участник сессии и сопоставление спикера, признак
    ожидания снимается, карточка перерисовывается главным видом. Невалидное —
    мягко переспрашиваем, ожидание держим. Нет живой сессии (истекла по TTL) —
    сообщение об истёкшем состоянии и сброс признака: ловить больше нечего.
    """
    try:
        user_id = message.from_user.id
        speaker_id = name_wait_registry.speaker_for(user_id)

        session = mapping_sessions.peek(user_id)
        if session is None:
            name_wait_registry.clear(user_id)
            await message.answer(_SESSION_GONE_TEXT)
            return

        # Не-текстовый контент (голосовое/аудио/видео/документ/фото/стикер):
        # message.text is None. Не трактуем как «слишком короткое имя» и не теряем
        # запись молча — держим ожидание и точечно просим прислать имя текстом.
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

        name_wait_registry.clear(user_id)

        await _redraw_main_card_after_naming(session, user_id, message)

    except Exception as e:
        logger.error(f"Ошибка в receive_custom_speaker_name: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке имени.")


@card_handler(session="peek", clear_name_wait=True)
async def speaker_mapping_cancel_callback(
    callback: CallbackQuery, callback_data: SmCancel, state: FSMContext,
    user_id: int, session: MappingSession,
) -> None:
    """sm_cancel: вернуться к основному виду карточки.

    Каркас с ``clear_name_wait=True`` снимает признак ожидания имени до
    разрешения сессии: отмена из под-вида ручного ввода не должна оставлять
    пользователя в ловле имени (следующее сообщение ушло бы в хендлер имени
    вместо обычной обработки). Из под-вида выбора участника признак не
    установлен — сброс безвреден.
    """
    await _show_main_view(callback, session, user_id)


async def _awaiting_speaker_name(message: Message) -> bool:
    """Фильтр message-хендлера имени: ловим сообщение, только пока пользователь
    ждёт ручной ввод имени (реестр ожидания).

    Живость сессии проверяет сам хендлер, не фильтр: истёкшая по TTL сессия
    должна получить _SESSION_GONE_TEXT, а не провалиться мимо в общий обработчик.
    """
    user = message.from_user
    return user is not None and name_wait_registry.is_waiting(user.id)


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    # Ручной ввод имени спикера (ADR-0002): callback перехода в ожидание имени
    # и message-хендлер приёма имени. Роутер сопоставления включён раньше общего
    # message_router (см. bot.py), поэтому имя ловится реестром ожидания здесь, а
    # команды и кнопки меню перехватывают их роутеры ещё раньше по цепочке.
    router.callback_query(SmCustom.filter())(request_custom_speaker_name)
    router.message(_awaiting_speaker_name)(receive_custom_speaker_name)

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

        # Очищаем состояние FSM и признак ожидания имени
        await state.clear()
        name_wait_registry.clear(user_id)

        # Продолжаем обработку — сессия передаётся владением
        await processing_service.continue_processing_after_mapping_confirmation(
            session=session,
            confirmed_mapping=session.speaker_mapping,
            bot=callback.bot,
            chat_id=callback.message.chat.id
        )

    @router.callback_query(SmSkip.filter())
    @card_handler(session="peek", on_error="edit")
    async def speaker_mapping_skip_callback(
        callback: CallbackQuery, callback_data: SmSkip, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_skip: развилка пропуска — подтверждение пустого прогона либо
        продолжение без имён.

        Сессию не изымаем до финала (peek); атомарный take выполняет
        ``_skip_or_confirm`` при продолжении без трения (защита двойного тапа).
        Тост не обещаем: под-вид подтверждения не должен выглядеть как «продолжаю».
        """
        await _skip_or_confirm(
            callback, state, user_id, session, processing_service
        )

    @router.callback_query(SmSkipConfirm.filter())
    @card_handler(
        session="take",
        answer_text="⏳ Продолжаю обработку без сопоставления...",
        on_error="edit",
    )
    async def speaker_mapping_skip_confirm_callback(
        callback: CallbackQuery, callback_data: SmSkipConfirm, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_skipok: подтверждённый пустой пропуск — продолжить без имён.

        Каркас атомарно изъял сессию (take): повторный тап получит None и не
        запустит второе возобновление.
        """
        await _finish_skip(callback, state, session, processing_service)

    return router
