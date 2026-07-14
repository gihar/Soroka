"""Приём новой записи вытесняет предыдущую из состояния (#70).

Сценарии переключения записи прогоняются через реальные хендлеры на общем
FSMContext с in-memory хранилищем aiogram:

    _process_url / media_handler (приём) → quick_process_file_callback (запуск).

Ожидаемое поведение: в обработку уходит ПОСЛЕДНЯЯ присланная запись, а ключи
прежней записи (file_id / file_path / file_url / is_external_file) в состоянии
не остаются. До #70 первая точка приёма только дописывала данные, поэтому
«ссылка → файл» обрабатывался как старая скачанная запись под именем нового
файла.
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

_DRIVE_URL = "https://drive.google.com/file/d/abc123/view"


# --- Общий FSMContext ------------------------------------------------------


def _fresh_state():
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=222, user_id=111),
    )


# --- Точка приёма: файл (media_handler) ------------------------------------


def _media_handler_with_service(file_service):
    router = mh.setup_message_handlers(file_service, MagicMock(), MagicMock())
    return next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "media_handler"
    )


def _make_document_message(file_id, file_name, message_id=555):
    """Message-документ с единственным заполненным медиа-полем."""
    message = MagicMock()
    message.message_id = message_id
    message.chat = SimpleNamespace(id=222)
    message.from_user = SimpleNamespace(id=111)
    message.audio = None
    message.voice = None
    message.video = None
    message.video_note = None
    message.document = SimpleNamespace(file_id=file_id, file_name=file_name, file_size=1024)
    message.answer = AsyncMock()
    return message


async def _accept_file(monkeypatch, state, *, file_id, file_name):
    """Провести реальный приём файла через media_handler."""
    monkeypatch.setattr(mh, "safe_answer", AsyncMock())
    file_service = MagicMock()
    file_service.validate_file = MagicMock(return_value=None)
    media_handler = _media_handler_with_service(file_service)
    await media_handler(_make_document_message(file_id, file_name), state)


# --- Точка приёма: ссылка (_process_url) -----------------------------------


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


async def _accept_link(monkeypatch, state, *, url=_DRIVE_URL,
                       filename="meeting.mp3", download_path="temp/meeting.mp3"):
    """Провести реальный приём ссылки через _process_url."""
    fake = _FakeURLService(filename=filename, download_path=download_path)
    monkeypatch.setattr(mh, "URLService", lambda: fake)
    monkeypatch.setattr(mh, "safe_answer", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(mh, "safe_edit_text", AsyncMock())
    import src.handlers.participants_handlers as ph
    monkeypatch.setattr(ph, "show_participants_menu", AsyncMock())

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111)
    message.chat = SimpleNamespace(id=222)
    await mh._process_url(message, url, state, MagicMock())


# --- Запуск: «Быстрая обработка» --------------------------------------------


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
    def __init__(self, user):
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


async def _run_quick_process(monkeypatch, state, user=None):
    """Запустить реальный quick_process_file_callback на общем state."""
    fake_qm = _FakeQueueManager()
    monkeypatch.setattr(tqm_mod, "task_queue_manager", fake_qm)
    monkeypatch.setattr(qt_mod, "QueueTrackerFactory", _FakeTrackerFactory)
    monkeypatch.setattr(mh, "_monitor_queue_position", AsyncMock())
    monkeypatch.setattr(pc, "safe_edit_text", AsyncMock())

    router = pc.setup_processing_callbacks(_FakeUserService(user), MagicMock(), MagicMock())
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "quick_process_file_callback"
    )
    await handler(_make_callback(), state)
    await asyncio.sleep(0)  # дать отработать фоновому мониторингу (AsyncMock)
    return fake_qm


# ---------------------------------------------------------------------------
# Сценарий A: ссылка → файл → Быстрая обработка
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_then_file_processes_the_file(monkeypatch):
    """После ссылки присланный файл вытесняет внешнюю запись из состояния."""
    state = _fresh_state()

    await _accept_link(monkeypatch, state)  # сначала ссылка (скачана)
    await _accept_file(monkeypatch, state, file_id="TG_NEW", file_name="new.mp3")

    # Состояние описывает только новый файл; внешние ключи вытеснены.
    data = await state.get_data()
    assert data["file_id"] == "TG_NEW"
    assert data["file_name"] == "new.mp3"
    assert data.get("file_path") is None
    assert data.get("file_url") is None
    assert data["is_external_file"] is False

    # В обработку уходит новый файл, а не прежняя скачанная запись.
    fake_qm = await _run_quick_process(monkeypatch, state)
    request = fake_qm.add_task_calls[0].request
    assert request.file_id == "TG_NEW"
    assert request.file_path is None
    assert request.is_external_file is False
    assert request.file_name == "new.mp3"


# ---------------------------------------------------------------------------
# Сценарий B: файл → ссылка → Быстрая обработка
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_then_link_processes_the_link(monkeypatch):
    """После файла принятая ссылка вытесняет прежний file_id из состояния."""
    state = _fresh_state()

    await _accept_file(monkeypatch, state, file_id="TG_OLD", file_name="old.mp3")
    await _accept_link(monkeypatch, state)  # затем ссылка (скачана)

    # Состояние описывает только запись по ссылке; file_id прежнего файла вытеснен.
    data = await state.get_data()
    assert data["is_external_file"] is True
    assert data["file_path"] == "temp/meeting.mp3"
    assert data["file_url"] == _DRIVE_URL
    assert data["file_name"] == "meeting.mp3"
    assert data.get("file_id") is None

    # В обработку уходит запись по ссылке, а не прежний Telegram-файл.
    fake_qm = await _run_quick_process(monkeypatch, state)
    request = fake_qm.add_task_calls[0].request
    assert request.is_external_file is True
    assert request.file_path == "temp/meeting.mp3"
    assert request.file_url == _DRIVE_URL
    assert request.file_id is None
