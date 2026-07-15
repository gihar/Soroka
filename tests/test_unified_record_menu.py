"""Единое меню действий с записью для файла и ссылки (#71).

Запись, присланная ссылкой (Google Drive / Яндекс.Диск), после успешного
скачивания получает то же меню действий с записью — «🚀 Быстрая обработка /
⚙️ Настроить», — что и запись файлом. Меню строится одной общей функцией-
билдером; обе точки приёма используют её (единая точка правды для текста и
кнопок).
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
from src.ux.quick_actions import QuickActionsUI  # noqa: E402

_DRIVE_URL = "https://drive.google.com/file/d/abc123/view"


def _callback_data_set(keyboard):
    return {
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data
    }


# ---------------------------------------------------------------------------
# Билдер: единая точка правды для текста и кнопок
# ---------------------------------------------------------------------------


def test_record_actions_menu_builder_text_and_buttons():
    """Билдер отдаёт текст «Файл получен» и ровно две кнопки быстрой обработки."""
    text, keyboard = QuickActionsUI.create_record_actions_menu()

    assert "📎 **Файл получен**" in text
    assert _callback_data_set(keyboard) == {
        "quick_process_file",
        "configure_file_processing",
    }


# ---------------------------------------------------------------------------
# Инфраструктура: реальные хендлеры на общем FSMContext
# ---------------------------------------------------------------------------


def _fresh_state():
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=222, user_id=111),
    )


class _FakeURLService:
    """Мок URLService — асинхронный контекст-менеджер."""

    def __init__(self, *, filename="meeting.mp3", download_path="temp/meeting.mp3"):
        self._file_info = (filename, 5 * 1024 * 1024, "https://direct/url")
        self._download_path = download_path

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def is_supported_url(self, url):
        return True

    async def get_file_info(self, url):
        return self._file_info

    def validate_file_by_info(self, filename, size):
        return None

    async def download_file(self, url, filename):
        return self._download_path


def _make_message():
    message = MagicMock()
    message.from_user = SimpleNamespace(id=111)
    message.chat = SimpleNamespace(id=222)
    message.answer = AsyncMock()
    return message


async def _accept_link(monkeypatch, state, message, *, url=_DRIVE_URL):
    """Провести реальный приём ссылки через _process_url."""
    monkeypatch.setattr(mh, "URLService", lambda: _FakeURLService())
    monkeypatch.setattr(mh, "safe_answer", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(mh, "safe_edit_text", AsyncMock())
    show_menu = AsyncMock()
    import src.handlers.participants_handlers as ph
    monkeypatch.setattr(ph, "show_participants_menu", show_menu)
    await mh._process_url(message, url, state, MagicMock())
    return show_menu


def _media_handler_with_service(file_service):
    router = mh.setup_message_handlers(file_service, MagicMock(), MagicMock())
    return next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "media_handler"
    )


def _make_document_message(file_id="TG1", file_name="rec.mp3"):
    message = MagicMock()
    message.message_id = 555
    message.chat = SimpleNamespace(id=222)
    message.from_user = SimpleNamespace(id=111)
    message.audio = None
    message.voice = None
    message.video = None
    message.video_note = None
    message.document = SimpleNamespace(file_id=file_id, file_name=file_name, file_size=1024)
    message.answer = AsyncMock()
    return message


async def _accept_file(monkeypatch, state, message):
    """Провести реальный приём файла через media_handler."""
    monkeypatch.setattr(mh, "safe_answer", AsyncMock())
    file_service = MagicMock()
    file_service.validate_file = MagicMock(return_value=None)
    media_handler = _media_handler_with_service(file_service)
    await media_handler(message, state)


# ---------------------------------------------------------------------------
# Ссылка после скачивания показывает меню действий с записью
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_shows_record_actions_menu_after_download(monkeypatch):
    """Ссылка → скачивание → меню действий с записью; меню участников не открывается."""
    state = _fresh_state()
    message = _make_message()

    show_menu = await _accept_link(monkeypatch, state, message)

    # Меню участников больше не открывается сразу — теперь показывается меню действий.
    show_menu.assert_not_awaited()

    # Отправлено меню действий с записью одним message.answer.
    assert message.answer.await_count == 1
    text = message.answer.call_args.args[0]
    assert "📎 **Файл получен**" in text
    keyboard = message.answer.call_args.kwargs["reply_markup"]
    assert _callback_data_set(keyboard) == {
        "quick_process_file",
        "configure_file_processing",
    }


# ---------------------------------------------------------------------------
# Единая точка правды: оба потока строят меню общим билдером
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_flows_build_menu_via_shared_builder(monkeypatch):
    """И файл, и ссылка строят меню одним билдером и шлют ровно его вывод."""
    sentinel_text = "SENTINEL-RECORD-MENU"
    sentinel_keyboard = object()
    builder = MagicMock(return_value=(sentinel_text, sentinel_keyboard))
    monkeypatch.setattr(QuickActionsUI, "create_record_actions_menu", builder)

    file_message = _make_document_message()
    await _accept_file(monkeypatch, _fresh_state(), file_message)

    link_message = _make_message()
    await _accept_link(monkeypatch, _fresh_state(), link_message)

    # Общий билдер вызван обоими потоками.
    assert builder.call_count == 2
    for msg in (file_message, link_message):
        assert msg.answer.await_count == 1
        assert msg.answer.call_args.args[0] == sentinel_text
        assert msg.answer.call_args.kwargs["reply_markup"] is sentinel_keyboard


@pytest.mark.asyncio
async def test_link_and_file_show_identical_record_menu(monkeypatch):
    """Меню для ссылки идентично меню для файла — сравнение выводов обоих потоков."""
    file_message = _make_document_message()
    await _accept_file(monkeypatch, _fresh_state(), file_message)

    link_message = _make_message()
    await _accept_link(monkeypatch, _fresh_state(), link_message)

    file_text = file_message.answer.call_args.args[0]
    link_text = link_message.answer.call_args.args[0]
    assert link_text == file_text

    file_kb = file_message.answer.call_args.kwargs["reply_markup"]
    link_kb = link_message.answer.call_args.kwargs["reply_markup"]
    # Полное равенство клавиатур (pydantic-модели сравниваются по значению).
    assert link_kb == file_kb


# ---------------------------------------------------------------------------
# E2E: ссылка → меню → «Быстрая обработка» ставит внешнюю запись в очередь
# ---------------------------------------------------------------------------


class _FakeQueueManager:
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
        return SimpleNamespace(message_id=None, is_active=False)


class _FakeUserService:
    def __init__(self, user=None):
        self._user = user

    async def get_user_by_telegram_id(self, telegram_id):
        return self._user


def _make_callback(*, user_id=111, chat_id=222):
    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=user_id)
    callback.bot = MagicMock()
    message = MagicMock()
    message.chat = SimpleNamespace(id=chat_id)
    message.from_user = SimpleNamespace(id=999)
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    callback.message = message
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_link_then_quick_process_enqueues_external_record(monkeypatch):
    """Ссылка → меню → «Быстрая обработка»: в очередь уходит внешняя запись."""
    state = _fresh_state()
    link_message = _make_message()

    # Ссылка принята и показано меню с кнопкой быстрой обработки.
    await _accept_link(monkeypatch, state, link_message)
    keyboard = link_message.answer.call_args.kwargs["reply_markup"]
    assert "quick_process_file" in _callback_data_set(keyboard)

    # Нажатие кнопки «Быстрая обработка» = вызов её колбэка на общем состоянии.
    fake_qm = _FakeQueueManager()
    monkeypatch.setattr(tqm_mod, "task_queue_manager", fake_qm)
    monkeypatch.setattr(qt_mod, "QueueTrackerFactory", _FakeTrackerFactory)
    monkeypatch.setattr(mh, "_monitor_queue_position", AsyncMock())
    monkeypatch.setattr(pc, "safe_edit_text", AsyncMock())

    router = pc.setup_processing_callbacks(_FakeUserService(), MagicMock(), MagicMock())
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "quick_process_file_callback"
    )
    await handler(_make_callback(), state)
    await asyncio.sleep(0)  # дать отработать фоновому мониторингу (AsyncMock)

    # Задача поставлена: внешняя запись с file_path и оригинальным URL.
    assert len(fake_qm.add_task_calls) == 1
    request = fake_qm.add_task_calls[0].request
    assert request.is_external_file is True
    assert request.file_path == "temp/meeting.mp3"
    assert request.file_url == _DRIVE_URL
    assert request.file_id is None
