"""Критика v11: у диалога «Дата и название» появилась ручка.

Приглашение уходило без клавиатуры, `/cancel` нигде не обрабатывался, а первая
непустая строка становилась датой — протокол переотправлялся с шапкой
«**Дата:** /cancel». Ссылка на новую запись, отправленная в этом состоянии,
тоже становилась датой: общий text_handler фильтрован StateFilter(None) и до
неё не доходил.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.protocol_header_edit import apply_header_edit


class FakeRepo:
    def __init__(self):
        self.updated = []

    async def get_result_for_user(self, history_id, telegram_id):
        return {
            "id": history_id,
            "file_name": "встреча.mp3",
            "result_text": "# Встреча\n**Дата:** 30 июля 2026\n\n## Решения\nОк.\n",
        }

    async def update_result_text(self, history_id, telegram_id, result_text):
        self.updated.append(result_text)
        return True


class FakeState:
    def __init__(self, state=None, data=None):
        self._state = state
        self._data = dict(data or {})

    async def get_state(self):
        return self._state

    async def set_state(self, state):
        self._state = state

    async def update_data(self, **values):
        self._data.update(values)
        return self._data

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self._state = None
        self._data = {}


def _handler(name: str):
    from src.handlers.callbacks.protocol_header_callbacks import (
        setup_protocol_header_callbacks,
    )

    router = setup_protocol_header_callbacks()
    for observer in (router.callback_query, router.message):
        for h in observer.handlers:
            if h.callback.__name__ == name:
                return h.callback
    raise AssertionError(f"хендлер {name} не зарегистрирован")


# ---------------------------------------------------------------------------
# Ввод, который не является датой
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_is_refused_not_written_into_the_header():
    """Ссылка — это новая запись, а не дата встречи."""
    repo = FakeRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42,
        raw_input="https://drive.google.com/file/d/abc/view",
    )

    assert outcome.status == "rejected"
    assert repo.updated == [], "в историю такое попасть не должно"


@pytest.mark.asyncio
async def test_command_is_refused():
    """«/cancel», «/start» — команды, а не даты."""
    repo = FakeRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="/cancel",
    )

    assert outcome.status == "rejected"
    assert repo.updated == []


@pytest.mark.asyncio
async def test_a_real_date_still_applies():
    repo = FakeRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27 июля 2026",
    )

    assert outcome.status == "ok"
    assert "**Дата:** 27 июля 2026" in outcome.protocol_text


@pytest.mark.asyncio
async def test_title_with_a_dot_is_not_mistaken_for_a_command():
    """Название встречи может начинаться с чего угодно, кроме слэша."""
    repo = FakeRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42,
        raw_input="27 июля 2026\nПланёрка 2.0",
    )

    assert outcome.status == "ok"
    assert outcome.title == "Планёрка 2.0"


@pytest.mark.asyncio
async def test_rejected_input_keeps_the_dialog_open():
    """Отказ — не выход: пользователь остаётся в диалоге и может повторить."""
    receive = _handler("receive_header")
    state = FakeState(state="ProtocolHeaderEdit:waiting_for_header",
                      data={"header_history_id": 1})
    message = SimpleNamespace(
        text="https://disk.yandex.ru/i/abc",
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        bot=SimpleNamespace(),
        answer=AsyncMock(),
    )

    await receive(message, state)

    assert await state.get_state() is not None, "диалог обязан остаться открытым"
    assert message.answer.await_count == 1


# ---------------------------------------------------------------------------
# Кнопка «Отмена»
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_offers_a_way_out():
    ask = _handler("ask_header")
    state = FakeState()
    callback = SimpleNamespace(
        data="proto_header_7",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(answer=AsyncMock()),
        answer=AsyncMock(),
    )

    await ask(callback, state)

    markup = callback.message.answer.await_args.kwargs.get("reply_markup")
    assert markup is not None, "приглашение без выхода — дверь без ручки"
    datas = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "proto_header_cancel" in datas


@pytest.mark.asyncio
async def test_cancel_button_closes_the_dialog():
    cancel = _handler("cancel_header")
    state = FakeState(state="ProtocolHeaderEdit:waiting_for_header",
                      data={"header_history_id": 1})
    callback = SimpleNamespace(
        data="proto_header_cancel",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(answer=AsyncMock(), edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )

    await cancel(callback, state)

    assert await state.get_state() is None


# ---------------------------------------------------------------------------
# /cancel — общая команда, а не подстрока в одном хендлере
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_cancel_clears_any_dialog():
    from src.handlers.command_handlers import setup_command_handlers

    router = setup_command_handlers(AsyncMock(), AsyncMock())
    handler = next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "cancel_handler"
    )

    state = FakeState(state="ProtocolHeaderEdit:waiting_for_header",
                      data={"header_history_id": 1})
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42), answer=AsyncMock(),
    )

    await handler(message, state)

    assert await state.get_state() is None
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_cancel_outside_a_dialog_says_so():
    from src.handlers.command_handlers import setup_command_handlers

    router = setup_command_handlers(AsyncMock(), AsyncMock())
    handler = next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "cancel_handler"
    )
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())

    await handler(message, FakeState())

    assert message.answer.await_count == 1


def test_cancel_is_a_command_not_a_substring_check():
    """Подстрочная проверка жила в одном хендлере из пяти обещавших /cancel."""
    import inspect

    import src.handlers.participants_handlers as ph

    source = inspect.getsource(ph.setup_participants_handlers)
    assert "startswith('/cancel')" not in source
    assert 'startswith("/cancel")' not in source


def test_cancel_command_is_registered_before_the_card():
    """Роутер команд включён раньше карточки — иначе /cancel съест ловец имени."""
    import inspect

    from src.bot import EnhancedTelegramBot

    source = inspect.getsource(EnhancedTelegramBot._setup_handlers)
    assert source.index("command_router") < source.index("callback_router")
