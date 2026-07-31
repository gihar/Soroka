"""Колбэк «Дата и название»: правка шапки уже доставленного протокола.

Тонкий адаптер к :mod:`src.services.protocol_header_edit` — вся логика правки
живёт там и тестируется без Telegram. Здесь только диалог: спросить, поймать
ответ, переотправить исправленный протокол.

Ловец текста привязан к FSM-состоянию, поэтому он не конкурирует с приёмом имён
спикеров (та карточка ловит текст, пока жива сессия сопоставления) — правка
шапки возможна только после доставки, когда сессии уже нет.
"""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.handlers.participants_states import ProtocolHeaderEdit
from src.services.protocol_header_edit import HEADER_EDIT_PROMPT, apply_header_edit

from .helpers import _safe_callback_answer

# Ввод пуст (одни пробелы/переводы строк): просим ещё раз, состояние держим —
# пользователь уже в диалоге, выкидывать его из-за опечатки незачем.
_EMPTY_INPUT_TEXT = (
    "Не увидел дату.\n"
    "Отправьте её одной строкой — например, «27 июля 2026»."
)

_GONE_TEXT = (
    "Протокол не найден — возможно, история очищена.\n"
    "Отправьте запись ещё раз."
)


def _history_id_from(data: str) -> int:
    return int(data.rsplit("_", 1)[-1])


def setup_protocol_header_callbacks() -> Router:
    """Диалог правки шапки: вопрос → ответ → исправленный протокол."""
    router = Router()

    @router.callback_query(F.data.startswith("proto_header_"))
    async def ask_header(callback: CallbackQuery, state: FSMContext):
        """Спросить дату встречи и запомнить, какой протокол правим."""
        try:
            history_id = _history_id_from(callback.data)
        except ValueError:
            logger.warning(f"Правка шапки: неожиданный callback_data «{callback.data}»")
            await _safe_callback_answer(
                callback, "Кнопка устарела — отправьте запись ещё раз."
            )
            return

        await state.set_state(ProtocolHeaderEdit.waiting_for_header)
        await state.update_data(header_history_id=history_id)
        await callback.message.answer(HEADER_EDIT_PROMPT)
        await _safe_callback_answer(callback)

    @router.message(StateFilter(ProtocolHeaderEdit.waiting_for_header), F.text)
    async def receive_header(message: Message, state: FSMContext):
        """Применить правку и переотправить протокол с прежними действиями."""
        data = await state.get_data()
        history_id = data.get("header_history_id")
        if not history_id:
            await state.clear()
            await message.answer(_GONE_TEXT)
            return

        from src.database import history_repo

        outcome = await apply_header_edit(
            history_repo,
            history_id=history_id,
            telegram_user_id=message.from_user.id,
            raw_input=message.text,
        )

        if outcome.status == "empty":
            await message.answer(_EMPTY_INPUT_TEXT)
            return

        await state.clear()

        if outcome.status != "ok":
            await message.answer(_GONE_TEXT)
            return

        await _resend(message, history_id, outcome)

    return router


async def _resend(message: Message, history_id: int, outcome) -> None:
    """Переотправить исправленный протокол в формате пользователя."""
    from src.services.result_sender import (
        _protocol_actions_keyboard,
        send_protocol_body,
    )
    from src.services.user_service import UserService

    try:
        user = await UserService().get_user_by_telegram_id(message.from_user.id)
        output_mode = getattr(user, "protocol_output_mode", None) or "messages"
    except Exception as e:
        logger.warning(f"Правка шапки: не удалось прочитать режим вывода: {e}")
        output_mode = "messages"

    changed = "Дата обновлена." if not outcome.title else "Шапка обновлена."
    await message.answer(changed)

    try:
        await send_protocol_body(
            message.bot,
            message.chat.id,
            outcome.protocol_text,
            outcome.file_name,
            output_mode,
            reply_markup=_protocol_actions_keyboard(history_id, output_mode),
        )
    except Exception as e:
        logger.error(f"Правка шапки {history_id}: переотправка не удалась: {e}")
        await message.answer(
            "❌ Не удалось отправить исправленный протокол.\n"
            "Нажмите «Дата и название» ещё раз."
        )
