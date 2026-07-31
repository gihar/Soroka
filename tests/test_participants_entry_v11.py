"""Критика v11: экран «Участники встречи» держит своё обещание.

Экран писал «Введите имена в любом формате — по одному на строку», но
FSM-состояние при его показе не выставлялось вовсе. Выполнивший инструкцию
дословно попадал в общий text_handler со StateFilter(None) и получал
«Отправьте файл (аудио или видео) или ссылку… для обработки» — предложение
сделать то, что он сделал минуту назад. Это первый экран настроенного пути.

Ввод текстом работает прямо на экране, поэтому отдельная кнопка «Добавить
участников» из меню ушла: одним шагом меньше. Как экран «Назад» приглашение
осталось.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.handlers.participants_handlers as ph
from src.handlers.participants_states import ParticipantsInput


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


def _message(chat_id=42):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=chat_id),
        chat=SimpleNamespace(id=chat_id),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )


def _user_service(saved=None):
    return SimpleNamespace(
        get_user_by_telegram_id=AsyncMock(
            return_value=SimpleNamespace(saved_participants=saved)
        )
    )


async def _show(monkeypatch, *, saved=None, state=None):
    """Показать меню участников, вернув (текст, клавиатура, состояние)."""
    captured = {}

    async def fake_answer(message, text, **kwargs):
        captured["text"] = text
        captured["markup"] = kwargs.get("reply_markup")
        return SimpleNamespace(message_id=777, chat=SimpleNamespace(id=42))

    monkeypatch.setattr(ph, "safe_answer", fake_answer)
    state = state if state is not None else FakeState()
    await ph.show_participants_menu(
        _message(), _user_service(saved), user_id=42, state=state,
    )
    return captured.get("text", ""), captured.get("markup"), state


def _datas(markup):
    if markup is None:
        return set()
    return {
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data
    }


# ---------------------------------------------------------------------------
# Обещание выполнимо
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_menu_opens_the_input_step(monkeypatch):
    """Главная находка: экран обещает ввод текстом — значит, ждёт его."""
    _, _, state = await _show(monkeypatch)

    assert await state.get_state() == ParticipantsInput.waiting_for_participants


@pytest.mark.asyncio
async def test_menu_survives_a_missing_state(monkeypatch):
    """Часть вызовов приходит без FSMContext — экран обязан показаться."""
    captured = {}

    async def fake_answer(message, text, **kwargs):
        captured["text"] = text
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=42))

    monkeypatch.setattr(ph, "safe_answer", fake_answer)
    await ph.show_participants_menu(_message(), _user_service(), user_id=42)

    assert "Участники встречи" in captured["text"]


@pytest.mark.asyncio
async def test_menu_explains_what_to_send(monkeypatch):
    """Раньше это объяснял отдельный экран за кнопкой — теперь всё здесь."""
    text, _, _ = await _show(monkeypatch)

    assert "приглашение" in text.lower(), "приглашение целиком — самый ценный ввод"
    assert "дат" in text.lower(), "дата в аудио отсутствует, о ней надо сказать"


@pytest.mark.asyncio
async def test_menu_no_longer_offers_a_button_for_typing(monkeypatch):
    _, markup, _ = await _show(monkeypatch)

    assert "input_new_participants" not in _datas(markup)


@pytest.mark.asyncio
async def test_menu_keeps_skip(monkeypatch):
    _, markup, _ = await _show(monkeypatch)

    assert "skip_participants" in _datas(markup)


@pytest.mark.asyncio
async def test_menu_keeps_saved_participants(monkeypatch):
    _, markup, _ = await _show(monkeypatch)
    assert "use_saved_participants" not in _datas(markup)

    _, markup, _ = await _show(
        monkeypatch, saved='[{"name": "Иван Петров"}]'
    )
    assert "use_saved_participants" in _datas(markup)


@pytest.mark.asyncio
async def test_menu_has_at_most_four_options(monkeypatch):
    """Точка решения не должна выходить за рабочую память."""
    _, markup, _ = await _show(monkeypatch, saved='[{"name": "Иван Петров"}]')

    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) <= 4


# ---------------------------------------------------------------------------
# Приглашение за «Назад» осталось живым
# ---------------------------------------------------------------------------


def test_back_from_confirmation_still_has_a_screen():
    """«⬅️ Назад» с экрана подтверждения ведёт в input_new_participants."""
    import inspect

    source = inspect.getsource(ph.setup_participants_handlers)
    assert 'F.data == "input_new_participants"' in source


# ---------------------------------------------------------------------------
# Устаревшая клавиатура гасится
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_menu_remembers_itself_for_later_dismissal(monkeypatch):
    _, _, state = await _show(monkeypatch)

    assert (await state.get_data()).get("participants_menu") == {
        "chat_id": 42, "message_id": 777,
    }


@pytest.mark.asyncio
async def test_dismiss_clears_the_old_keyboard():
    """Меню участников не должно оставаться нажимаемым после ухода вперёд."""
    bot = SimpleNamespace(edit_message_reply_markup=AsyncMock())
    state = FakeState(data={"participants_menu": {"chat_id": 42, "message_id": 777}})

    await ph.dismiss_participants_menu(bot, state)

    bot.edit_message_reply_markup.assert_awaited_once()
    kwargs = bot.edit_message_reply_markup.await_args.kwargs
    assert kwargs["chat_id"] == 42 and kwargs["message_id"] == 777
    assert kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_dismiss_forgets_the_menu():
    """Повторный вызов не должен дёргать Telegram второй раз."""
    bot = SimpleNamespace(edit_message_reply_markup=AsyncMock())
    state = FakeState(data={"participants_menu": {"chat_id": 42, "message_id": 777}})

    await ph.dismiss_participants_menu(bot, state)
    await ph.dismiss_participants_menu(bot, state)

    assert bot.edit_message_reply_markup.await_count == 1


@pytest.mark.asyncio
async def test_dismiss_without_a_menu_is_a_noop():
    bot = SimpleNamespace(edit_message_reply_markup=AsyncMock())

    await ph.dismiss_participants_menu(bot, FakeState())

    bot.edit_message_reply_markup.assert_not_awaited()


@pytest.mark.asyncio
async def test_dismiss_survives_telegram_refusal():
    """Сообщение могли удалить — гашение не имеет права ронять поток."""
    bot = SimpleNamespace(
        edit_message_reply_markup=AsyncMock(side_effect=RuntimeError("нет такого"))
    )
    state = FakeState(data={"participants_menu": {"chat_id": 42, "message_id": 777}})

    await ph.dismiss_participants_menu(bot, state)

    assert (await state.get_data()).get("participants_menu") is None


@pytest.mark.asyncio
async def test_dismiss_survives_a_missing_state():
    bot = SimpleNamespace(edit_message_reply_markup=AsyncMock())
    await ph.dismiss_participants_menu(bot, None)
    bot.edit_message_reply_markup.assert_not_awaited()


def test_template_step_dismisses_the_menu():
    """Переход к выбору шаблона — общая дверь всех веток участников."""
    import inspect

    from src.handlers.message_handlers import _show_template_selection_step2

    source = inspect.getsource(_show_template_selection_step2)
    assert "dismiss_participants_menu" in source
