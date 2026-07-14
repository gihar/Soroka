"""Характеризация запуска обработки: «Быстрая обработка» и «Настроить» (#68).

Фиксирует текущее поведение двух callback-точек, запускающих обработку
принятой записи. Продуктовый код не меняется.

Точка 3: quick_process_file_callback — «🚀 Быстрая обработка» ставит задачу
    в очередь с сохранённым шаблоном пользователя либо умным выбором (0),
    провайдером 'openai', без участников; работает для обеих веток записи —
    Telegram-файл (file_id) и внешняя запись (file_path + is_external_file).

Точка 4: configure_file_processing_callback — «⚙️ Настроить» редактирует
    сообщение и показывает меню участников. Известный баг (чинится позже):
    меню строится по callback.message.from_user.id — это ID БОТА, поэтому
    кнопка «Использовать сохранённый» не появляется, даже если у реального
    пользователя сохранён список.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Legacy-модули внутри хендлеров используют голый `from services import ...`.
sys.path.insert(0, os.path.join(_root, "src"))

import src.handlers.callbacks.processing_callbacks as pc  # noqa: E402
import src.handlers.message_handlers as mh  # noqa: E402
import src.services.task_queue_manager as tqm_mod  # noqa: E402
import src.ux.queue_tracker as qt_mod  # noqa: E402


def _fresh_state():
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=222, user_id=111),
    )


def _find_callback(router, name):
    return next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == name
    )


def _make_callback(*, user_id=111, chat_id=222, message_from_user_id=999):
    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=user_id)
    callback.bot = MagicMock()
    message = MagicMock()
    message.chat = SimpleNamespace(id=chat_id)
    message.from_user = SimpleNamespace(id=message_from_user_id)
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    callback.message = message
    callback.answer = AsyncMock()
    return callback


def _callback_data_set(keyboard):
    return {
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data
    }


class _FakeQueueManager:
    """Мок task_queue_manager: копит запросы, кладёт «задачу» в очередь."""

    def __init__(self):
        self.add_task_calls = []

    async def add_task(self, request, chat_id, priority):
        self.add_task_calls.append(
            SimpleNamespace(request=request, chat_id=chat_id, priority=priority)
        )
        return SimpleNamespace(task_id="TASK-1", message_id=None)

    async def get_queue_position(self, task_id):
        return 0

    async def get_queue_size(self):
        return 1


class _FakeTrackerFactory:
    @staticmethod
    async def create_tracker(**kwargs):
        # message_id=None → блок обновления БД в _process_file пропускается.
        return SimpleNamespace(message_id=None, is_active=False)


class _FakeUserService:
    def __init__(self, user):
        self._user = user

    async def get_user_by_telegram_id(self, telegram_id):
        return self._user


def _patch_processing(monkeypatch):
    """Изолирует очередь/трекер/мониторинг от реальной инфраструктуры."""
    fake_qm = _FakeQueueManager()
    monkeypatch.setattr(tqm_mod, "task_queue_manager", fake_qm)
    monkeypatch.setattr(qt_mod, "QueueTrackerFactory", _FakeTrackerFactory)
    monkeypatch.setattr(mh, "_monitor_queue_position", AsyncMock())
    monkeypatch.setattr(pc, "safe_edit_text", AsyncMock())
    return fake_qm


async def _run_quick_process(monkeypatch, state, user):
    fake_qm = _patch_processing(monkeypatch)
    router = pc.setup_processing_callbacks(_FakeUserService(user), MagicMock(), MagicMock())
    handler = _find_callback(router, "quick_process_file_callback")
    callback = _make_callback()

    await handler(callback, state)
    # Даём отработать фоновому мониторингу (AsyncMock), чтобы не оставлять задачу висящей.
    await asyncio.sleep(0)
    return fake_qm, callback


# ---------------------------------------------------------------------------
# Точка 3: «Быстрая обработка»
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_process_telegram_file_smart_default(monkeypatch):
    """Telegram-файл без сохранённого шаблона → умный выбор (0), openai, без участников."""
    state = _fresh_state()
    await state.update_data(file_id="TG_FILE", file_name="rec.mp3")

    fake_qm, callback = await _run_quick_process(monkeypatch, state, user=None)

    assert len(fake_qm.add_task_calls) == 1
    request = fake_qm.add_task_calls[0].request
    assert request.file_id == "TG_FILE"
    assert request.file_path is None
    assert request.is_external_file is False
    assert request.file_name == "rec.mp3"
    assert request.template_id == 0
    assert request.llm_provider == "openai"
    assert request.participants_list is None
    assert request.user_id == callback.from_user.id
    assert fake_qm.add_task_calls[0].chat_id == callback.message.chat.id


@pytest.mark.asyncio
async def test_quick_process_uses_saved_default_template(monkeypatch):
    """Есть сохранённый шаблон → он и уходит в запрос (без умного выбора)."""
    state = _fresh_state()
    await state.update_data(file_id="TG_FILE", file_name="rec.mp3")
    user = SimpleNamespace(default_template_id=7)

    fake_qm, _ = await _run_quick_process(monkeypatch, state, user=user)

    request = fake_qm.add_task_calls[0].request
    assert request.template_id == 7
    assert request.llm_provider == "openai"
    assert request.participants_list is None


@pytest.mark.asyncio
async def test_quick_process_external_record(monkeypatch):
    """Внешняя запись (file_path + is_external_file) → запрос по пути и URL, без file_id."""
    state = _fresh_state()
    await state.update_data(
        file_path="temp/from_drive.mp3",
        file_name="from_drive.mp3",
        file_url="https://drive.google.com/file/d/abc/view",
        is_external_file=True,
    )

    fake_qm, _ = await _run_quick_process(monkeypatch, state, user=None)

    request = fake_qm.add_task_calls[0].request
    assert request.is_external_file is True
    assert request.file_path == "temp/from_drive.mp3"
    assert request.file_id is None
    assert request.file_url == "https://drive.google.com/file/d/abc/view"
    assert request.file_name == "from_drive.mp3"
    assert request.template_id == 0
    assert request.participants_list is None


@pytest.mark.asyncio
async def test_quick_process_without_file_does_not_queue(monkeypatch):
    """Нет записи в состоянии → предупреждение и никакой постановки в очередь."""
    state = _fresh_state()  # пустое состояние

    fake_qm, callback = await _run_quick_process(monkeypatch, state, user=None)

    assert fake_qm.add_task_calls == []
    callback.answer.assert_awaited()
    warn_text = callback.answer.call_args.args[0]
    assert "не найден" in warn_text.lower()


# ---------------------------------------------------------------------------
# Точка 4: «Настроить»
# ---------------------------------------------------------------------------


class _MapUserService:
    """Возвращает разных пользователей по telegram_id и пишет историю вызовов."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def get_user_by_telegram_id(self, telegram_id):
        self.calls.append(telegram_id)
        return self.mapping.get(telegram_id)


@pytest.mark.asyncio
async def test_configure_shows_participants_menu(monkeypatch):
    """«Настроить» редактирует сообщение и показывает меню участников."""
    monkeypatch.setattr(pc, "safe_edit_text", AsyncMock())
    user_service = _MapUserService({999: SimpleNamespace(saved_participants=None)})
    router = pc.setup_processing_callbacks(user_service, MagicMock(), MagicMock())
    handler = _find_callback(router, "configure_file_processing_callback")
    callback = _make_callback(user_id=111, message_from_user_id=999)

    await handler(callback)

    # Показано меню участников (реальный show_participants_menu через callback.message).
    assert callback.message.answer.await_count == 1
    text = callback.message.answer.call_args.args[0]
    assert "Участники встречи" in text
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_configure_looks_up_bot_id_hides_saved_button(monkeypatch):
    """Баг текущего кода: поиск идёт по ID бота, поэтому «Использовать сохранённый» не появляется."""
    monkeypatch.setattr(pc, "safe_edit_text", AsyncMock())
    real_user_id = 111
    bot_id = 999
    user_service = _MapUserService({
        # У реального пользователя список ЕСТЬ…
        real_user_id: SimpleNamespace(saved_participants='[{"name": "Иван Иванов"}]'),
        # …но callback.message.from_user.id — это бот, у него ничего нет.
        bot_id: SimpleNamespace(saved_participants=None),
    })
    router = pc.setup_processing_callbacks(user_service, MagicMock(), MagicMock())
    handler = _find_callback(router, "configure_file_processing_callback")
    callback = _make_callback(user_id=real_user_id, message_from_user_id=bot_id)

    await handler(callback)

    # Поиск выполнен по ID бота, а не по реальному пользователю.
    assert user_service.calls == [bot_id]

    # Кнопка сохранённого списка отсутствует — виден только ввод и пропуск.
    keyboard = callback.message.answer.call_args.kwargs["reply_markup"]
    data = _callback_data_set(keyboard)
    assert "use_saved_participants" not in data
    assert data == {"input_new_participants", "skip_participants"}
