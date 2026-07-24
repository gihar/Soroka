"""
Обработчики callback запросов для сопоставления спикеров с участниками.

Работают с типизированной сессией сопоставления: peek для чтения (смена,
выбор, отмена), атомарный take для подтверждения/пропуска — повторный тап
получает None и не запускает второе возобновление.

Прямой ввод имени (ADR-0006): тап на спикера (``sm_change``) открывает под-вид,
готовый принять имя сообщением. Признак «какой спикер ждёт имя» — поле сессии
``editing_speaker``. Ловец имени привязан только к тексту без ссылки: файл,
голосовое, фото и ссылка проваливаются мимо, в обычную обработку записи.
"""

import re
from typing import Callable, Optional

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.services import ProcessingService, TemplateService, UserService
from src.services.mapping_session import MappingSession, mapping_sessions
from src.services.participants_service import participants_service
from src.utils.telegram_safe import safe_edit_text
from src.utils.url_detection import contains_url
from src.ux.card_sender import edit_card
from src.ux.speaker_mapping_callback_data import (
    SmCancel,
    SmChange,
    SmConfirm,
    SmSelect,
    SmSkip,
    SmSkipConfirm,
)
from src.ux.speaker_mapping_ui import (
    create_skip_confirm_keyboard,
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

# Разделители нескольких имён в одном сообщении: запятая или перенос строки.
_NAME_SEPARATORS = re.compile(r"[,\n]")


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
    (``sm_skipok``). Сессия уже изъята вызывающим (take) — под-вид с ней закрыт,
    ``editing_speaker`` неактуален; здесь только продолжаем обработку с пустым
    сопоставлением.
    """
    await safe_edit_text(
        callback.message, _SKIP_CONTINUED_TEXT, parse_mode="Markdown"
    )
    await state.clear()
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
    """

    def decorator(core: Callable) -> Callable:
        async def wrapper(callback: CallbackQuery, callback_data, state: FSMContext) -> None:
            try:
                user_id = callback_data.user_id
                if callback.from_user.id != user_id:
                    await _safe_callback_answer(callback, "❌ Это не ваш запрос")
                    return

                await _safe_callback_answer(callback, answer_text)

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
                          user_id: int) -> None:
    """Перерисовать Карточку сопоставления из типизированной сессии.

    Под-вид спикера или главный вид выбирается признаком ``editing_speaker``
    самой сессии: задан — под-вид ждёт имя, None — главный вид.
    """
    diarization = session.transcription_result.diarization
    await update_mapping_message(
        callback.message,
        session.speaker_mapping,
        diarization,
        session.request.participants_list or [],
        user_id,
        current_editing_speaker=session.editing_speaker,
        speakers_text=diarization.speakers_text if diarization else None,
        speakers_with_audio=session.speakers_with_audio,
    )


async def _redraw_main_card_after_naming(
    session: MappingSession, user_id: int, fallback_message: Message
) -> None:
    """Перерисовать главный вид карточки после ввода имени.

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


def _looks_like_multiple_names(text: str) -> bool:
    """Несколько имён (разделители — запятая или перенос строки) в одном сообщении.

    Под-вид ждёт ровно одно имя для одного спикера; пачку имён принимает общий
    вид карточки. Считаем непустые куски после разбиения — их два и больше.
    """
    parts = [p.strip() for p in _NAME_SEPARATORS.split(text) if p.strip()]
    return len(parts) >= 2


async def receive_speaker_name(message: Message) -> None:
    """Сообщение с именем спикера, пока открыт под-вид (``editing_speaker``).

    Фильтр гарантировал: живая сессия, ``editing_speaker`` задан, content — текст
    без ссылки. Валидное одно имя → полноценный участник сессии и сопоставление
    спикера, под-вид закрывается, карточка перерисовывается главным видом.
    Несколько имён или имя вне планки 2–50 → короткий отказ, ничего не применяем
    (всё или ничего).
    """
    try:
        user_id = message.from_user.id
        session = mapping_sessions.peek(user_id)
        if session is None:
            # Сессия истекла между проверкой фильтра и телом — ловить нечего.
            return
        speaker_id = session.editing_speaker
        text = message.text

        if _looks_like_multiple_names(text):
            await message.answer(
                f"Здесь ждём одно имя — для {speaker_id}. Несколько имён можно "
                "отправить из общего вида карточки (◀️ Назад)."
            )
            return

        new_list, display_name = participants_service.add_manual_participant(
            session.request.participants_list, text
        )
        if new_list is None:
            await message.answer(
                "Имя должно быть 2–50 символов и не начинаться с «/».\n"
                "Отправьте имя ещё раз или нажмите «◀️ Назад»."
            )
            return

        session.request.participants_list = new_list
        new_mapping = dict(session.speaker_mapping)
        if speaker_id:
            new_mapping[speaker_id] = display_name
        mapping_sessions.update_mapping(user_id, new_mapping)
        session.editing_speaker = None

        await _redraw_main_card_after_naming(session, user_id, message)

    except Exception as e:
        logger.error(f"Ошибка в receive_speaker_name: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке имени.")


@card_handler(session="peek")
async def speaker_mapping_cancel_callback(
    callback: CallbackQuery, callback_data: SmCancel, state: FSMContext,
    user_id: int, session: MappingSession,
) -> None:
    """sm_cancel: «◀️ Назад» — закрыть под-вид спикера, вернуться к главному виду.

    Снимает ``editing_speaker``: следующее текстовое сообщение уже не ловится
    как имя, а уходит в обычную обработку записи.
    """
    session.editing_speaker = None
    await _show_main_view(callback, session, user_id)


async def _capturing_speaker_name(message: Message) -> bool:
    """Фильтр message-хендлера имени: ловим текст, только пока открыт под-вид
    спикера (``editing_speaker`` живой сессии) и это не ссылка.

    Ссылка, не-текст (файл/голос/видео/фото) и истёкшая по TTL сессия
    проваливаются мимо — в обычный поток обработки записи; под-вид карточки их
    не съедает (ADR-0006). Живость сессии читается здесь же: под-вида нет без
    живой сессии, поэтому истёкшая сессия просто перестаёт ловить.
    """
    user = message.from_user
    if user is None or not message.text:
        return False
    if contains_url(message.text):
        return False
    session = mapping_sessions.peek(user.id)
    return session is not None and session.editing_speaker is not None


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    # Прямой ввод имени спикера (ADR-0006): message-хендлер приёма имени, пока
    # открыт под-вид спикера. Роутер сопоставления включён раньше общего
    # message_router (см. bot.py), поэтому имя ловится здесь, а команды, кнопки
    # меню и ссылки/файлы перехватывают их роутеры (или общий поток) по цепочке.
    router.message(_capturing_speaker_name)(receive_speaker_name)

    @router.callback_query(SmChange.filter())
    @card_handler(session="peek")
    async def speaker_mapping_change_callback(
        callback: CallbackQuery, callback_data: SmChange, state: FSMContext,
        user_id: int, session: MappingSession,
    ):
        """sm_change: открыть под-вид спикера, готовый принять имя сообщением."""
        session.editing_speaker = callback_data.speaker_id
        await _show_main_view(callback, session, user_id)

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
        session.editing_speaker = None

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
        запустил второе возобновление. Под-вид закрыт вместе с изъятой сессией —
        ``editing_speaker`` отдельно снимать не нужно.
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
