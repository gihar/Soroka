"""Критика v10: новая запись сбрасывает висящий шаг диалога.

Файл, присланный посреди ввода участников, ловил `media_handler` (его роутер
включён раньше participants_router). Запись регистрировалась, а FSM-состояние
``waiting_for_participants`` оставалось висеть — и следующий текст пользователя
разбирался как список участников, хотя он уже начал новый прогон.

Ключи записи сбрасывались, шаг диалога — нет.
"""

import pytest

from src.handlers.participants_states import ParticipantsInput
from src.handlers.record_state import register_new_record


class FakeState:
    """FSMContext ровно в той части, что нужна хелперу."""

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


@pytest.mark.asyncio
async def test_new_record_clears_hanging_participants_step():
    state = FakeState(
        state=ParticipantsInput.waiting_for_participants,
        data={"file_id": "старый"},
    )

    await register_new_record(state, file_id="новый")

    assert await state.get_state() is None, "шаг диалога обязан сброситься"


@pytest.mark.asyncio
async def test_new_record_applies_its_values():
    state = FakeState(state=ParticipantsInput.waiting_for_participants)

    await register_new_record(state, file_id="новый", is_external_file=False)

    data = await state.get_data()
    assert data["file_id"] == "новый"
    assert data["file_path"] is None


@pytest.mark.asyncio
async def test_record_without_hanging_state_is_untouched():
    state = FakeState(state=None, data={"meeting_topic": "Смета"})

    await register_new_record(state, file_id="новый")

    assert await state.get_state() is None
    # Контекст встречи не относится к шагу диалога и переживает новую запись.
    assert (await state.get_data())["meeting_topic"] == "Смета"


@pytest.mark.asyncio
async def test_unrelated_state_is_also_cleared():
    """Любой висящий шаг мешает новой записи, не только ввод участников."""
    from src.handlers.participants_states import ProtocolHeaderEdit

    state = FakeState(state=ProtocolHeaderEdit.waiting_for_header)

    await register_new_record(state, file_id="новый")

    assert await state.get_state() is None
