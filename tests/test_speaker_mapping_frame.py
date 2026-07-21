"""Каркас callback-хендлеров Карточки сопоставления (``card_handler``).

Единый шов снимает с хендлеров повторяющуюся обвязку: снятие «загрузки»,
проверку владельца по типизированному callback_data, чтение/атомарное изъятие
Сессии сопоставления, «сессия истекла» и лог исключений — оставляя телу
предметную суть. Тесты описывают наблюдаемое поведение шва.
"""

import os
import sys
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402

from src.services.mapping_session import mapping_sessions  # noqa: E402
from src.ux.speaker_mapping_callback_data import SmChange  # noqa: E402

USER = 7777


class _FakeState:
    def __init__(self):
        self._state = "some-state"
        self._data = {"k": "v"}

    async def clear(self):
        self._state = None
        self._data = {}

    async def get_state(self):
        return self._state


class _FakeCallback:
    def __init__(self, from_user_id):
        self.from_user = SimpleNamespace(id=from_user_id)
        self.message = SimpleNamespace()
        self.bot = SimpleNamespace()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    mapping_sessions.discard(USER)


def _cbdata():
    return SmChange(speaker_id="SPEAKER_1", user_id=USER)


@pytest.mark.asyncio
async def test_frame_rejects_foreign_user():
    """Чужой user_id в callback_data → «не ваш запрос», тело не вызвано."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    called = []

    @cb.card_handler(session="peek")
    async def handler(callback, callback_data, state, user_id, session):
        called.append(user_id)

    callback = _FakeCallback(from_user_id=9999)  # != USER в callback_data
    await handler(callback, _cbdata(), _FakeState())

    assert called == []
    assert "❌ Это не ваш запрос" in callback.answers


@pytest.mark.asyncio
async def test_frame_reports_expired_when_session_gone(monkeypatch):
    """peek без сессии → _SESSION_GONE_TEXT, тело не вызвано."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    edited = []

    async def fake_edit(message, text, **kwargs):
        edited.append(text)
        return True

    monkeypatch.setattr(cb, "safe_edit_text", fake_edit)
    mapping_sessions.discard(USER)

    called = []

    @cb.card_handler(session="peek")
    async def handler(callback, callback_data, state, user_id, session):
        called.append(user_id)

    await handler(_FakeCallback(from_user_id=USER), _cbdata(), _FakeState())

    assert called == []
    assert edited == [cb._SESSION_GONE_TEXT]


@pytest.mark.asyncio
async def test_frame_peek_passes_session_to_body():
    """Владелец + живая сессия (peek) → тело получает user_id и сессию, сессия остаётся."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    sentinel = SimpleNamespace(name="session")
    mapping_sessions.save(USER, sentinel)

    seen = {}

    @cb.card_handler(session="peek")
    async def handler(callback, callback_data, state, user_id, session):
        seen["user_id"] = user_id
        seen["session"] = session

    await handler(_FakeCallback(from_user_id=USER), _cbdata(), _FakeState())

    assert seen["user_id"] == USER
    assert seen["session"] is sentinel
    assert mapping_sessions.peek(USER) is sentinel  # peek не изымает


@pytest.mark.asyncio
async def test_frame_take_removes_session():
    """take-режим отдаёт сессию телу и изымает её (двойной тап получит None)."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    sentinel = SimpleNamespace(name="session")
    mapping_sessions.save(USER, sentinel)

    seen = {}

    @cb.card_handler(session="take", on_error="edit")
    async def handler(callback, callback_data, state, user_id, session):
        seen["session"] = session

    await handler(_FakeCallback(from_user_id=USER), _cbdata(), _FakeState())

    assert seen["session"] is sentinel
    assert mapping_sessions.peek(USER) is None  # take изъял


@pytest.mark.asyncio
async def test_frame_answer_error_on_body_exception():
    """Исключение сути при on_error='answer' → лог + «Произошла ошибка» тостом."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    mapping_sessions.save(USER, SimpleNamespace())

    @cb.card_handler(session="peek")
    async def handler(callback, callback_data, state, user_id, session):
        raise RuntimeError("boom")

    callback = _FakeCallback(from_user_id=USER)
    await handler(callback, _cbdata(), _FakeState())  # не пробрасывает

    assert "❌ Произошла ошибка" in callback.answers


@pytest.mark.asyncio
async def test_frame_edit_error_on_body_exception(monkeypatch):
    """Исключение сути при on_error='edit' → лог + правка сообщения об ошибке."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    edited = []

    async def fake_edit(message, text, **kwargs):
        edited.append(text)
        return True

    monkeypatch.setattr(cb, "safe_edit_text", fake_edit)
    mapping_sessions.save(USER, SimpleNamespace())

    @cb.card_handler(session="take", on_error="edit")
    async def handler(callback, callback_data, state, user_id, session):
        raise RuntimeError("boom")

    await handler(_FakeCallback(from_user_id=USER), _cbdata(), _FakeState())

    assert edited and "ошибка при продолжении обработки" in edited[-1]


@pytest.mark.asyncio
async def test_frame_clear_state_clears_even_when_session_gone(monkeypatch):
    """clear_state=True очищает FSM до разрешения сессии — даже если она истекла."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    async def fake_edit(message, text, **kwargs):
        return True

    monkeypatch.setattr(cb, "safe_edit_text", fake_edit)
    mapping_sessions.discard(USER)

    @cb.card_handler(session="peek", clear_state=True)
    async def handler(callback, callback_data, state, user_id, session):
        pass

    state = _FakeState()
    await handler(_FakeCallback(from_user_id=USER), _cbdata(), state)

    assert await state.get_state() is None
