"""Характеризация приёма записи: файл и ссылка (#68).

Фиксирует текущее поведение двух входных точек приёма записи —
до выравнивания меню действий в последующих задачах. Продуктовый код
не меняется; тесты описывают то, что бот делает СЕЙЧАС.

Точка 1: media_handler — файл (аудио/видео/голос/видеосообщение/документ)
    → сохранение file_id/file_name в состояние и меню «📎 Файл получен»
    с кнопками «🚀 Быстрая обработка» и «⚙️ Настроить»; ошибки валидации
    (размер/формат) показывают сообщение и меню НЕ показывают.

Точка 2: _process_url — ссылка Google Drive / Яндекс.Диск → проверка
    поддержки, показ имени и размера, скачивание, сохранение внешней
    записи в состояние и показ меню действий с записью (после #71 — то же
    меню «📎 Файл получен», что и для файла; раньше открывалось меню участников).
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Legacy-модули внутри хендлеров используют голый `from services import ...`.
sys.path.insert(0, os.path.join(_root, "src"))

import src.handlers.message_handlers as mh  # noqa: E402
from src.exceptions.file import FileSizeError, FileTypeError  # noqa: E402

# --- Реальный формат ответа FileService.get_supported_formats() ---
_SUPPORTED_FORMATS = {
    "audio": ["MP3", "WAV", "M4A", "OGG"],
    "video": ["MP4", "AVI", "MOV", "MKV"],
    "content_types": ["Аудио сообщения", "Видео сообщения", "Видео заметки", "Документы"],
}


def _fresh_state():
    """Настоящий FSMContext с in-memory хранилищем aiogram."""
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=111, user_id=111),
    )


def _media_handler_with_service(file_service):
    router = mh.setup_message_handlers(file_service, MagicMock(), MagicMock())
    return next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "media_handler"
    )


def _make_media_message(content_type, file_obj, message_id=555):
    """Message только с одним заполненным медиа-полем (как в Telegram)."""
    message = MagicMock()
    message.message_id = message_id
    message.chat = SimpleNamespace(id=111)
    message.from_user = SimpleNamespace(id=111)
    message.audio = None
    message.voice = None
    message.video = None
    message.video_note = None
    message.document = None
    setattr(message, content_type, file_obj)
    message.answer = AsyncMock()
    return message


def _callback_data_set(keyboard):
    return {
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data
    }


def _menu_calls(safe_answer_mock):
    """Вызовы safe_answer с клавиатурой — отправки меню, не статусные тексты.

    Все отправки идут через safe-обёртки (рендер Markdown -> HTML на границе),
    поэтому меню ищем среди вызовов safe_answer, а не прямого message.answer.
    """
    return [
        call for call in safe_answer_mock.await_args_list
        if call.kwargs.get("reply_markup") is not None
    ]


# ---------------------------------------------------------------------------
# Точка 1: приём файла
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_intake_saves_file_and_shows_action_menu(monkeypatch):
    """Документ → file_id/file_name в состоянии + меню с двумя кнопками."""
    safe_answer = AsyncMock()
    monkeypatch.setattr(mh, "safe_answer", safe_answer)
    file_service = MagicMock()
    file_service.validate_file = MagicMock(return_value=None)
    media_handler = _media_handler_with_service(file_service)

    document = SimpleNamespace(file_id="DOC_FILE_ID", file_name="meeting.mp3", file_size=1024)
    message = _make_media_message("document", document)
    state = _fresh_state()

    await media_handler(message, state)

    # Состояние: сохранён file_id и исходное имя документа.
    data = await state.get_data()
    assert data["file_id"] == "DOC_FILE_ID"
    assert data["file_name"] == "meeting.mp3"

    # Показано меню действий одной отправкой с клавиатурой.
    menu = _menu_calls(safe_answer)
    assert len(menu) == 1
    text = menu[0].args[1]
    assert "📎 **Файл получен**" in text
    keyboard = menu[0].kwargs["reply_markup"]
    assert _callback_data_set(keyboard) == {"quick_process_file", "configure_file_processing"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type, file_obj",
    [
        ("audio", SimpleNamespace(file_id="AUD1", file_name="rec.mp3", file_size=1000, mime_type="audio/mpeg")),
        ("voice", SimpleNamespace(file_id="VOICE1", file_size=1000)),
        ("video", SimpleNamespace(file_id="VID1", file_name="clip.mp4", file_size=1000)),
        ("video_note", SimpleNamespace(file_id="VN1", file_size=1000)),
        ("document", SimpleNamespace(file_id="DOC1", file_name="a.wav", file_size=1000)),
    ],
)
async def test_all_media_types_show_action_menu(monkeypatch, content_type, file_obj):
    """Любой тип записи-файла ведёт к тому же меню действий, file_id сохранён."""
    safe_answer = AsyncMock()
    monkeypatch.setattr(mh, "safe_answer", safe_answer)
    file_service = MagicMock()
    file_service.validate_file = MagicMock(return_value=None)
    media_handler = _media_handler_with_service(file_service)

    message = _make_media_message(content_type, file_obj)
    state = _fresh_state()

    await media_handler(message, state)

    data = await state.get_data()
    assert data["file_id"] == file_obj.file_id
    assert data.get("file_name")  # имя всегда проставлено

    keyboard = _menu_calls(safe_answer)[0].kwargs["reply_markup"]
    assert _callback_data_set(keyboard) == {"quick_process_file", "configure_file_processing"}


@pytest.mark.asyncio
async def test_file_size_error_shows_error_without_menu(monkeypatch):
    """FileSizeError → сообщение об ошибке через safe_answer, меню не показано."""
    safe_answer = AsyncMock()
    monkeypatch.setattr(mh, "safe_answer", safe_answer)

    file_service = MagicMock()
    file_service.validate_file = MagicMock(
        side_effect=FileSizeError(30 * 1024 * 1024, 20 * 1024 * 1024)
    )
    media_handler = _media_handler_with_service(file_service)

    document = SimpleNamespace(file_id="BIG", file_name="big.mp3", file_size=30 * 1024 * 1024)
    message = _make_media_message("document", document)
    state = _fresh_state()

    await media_handler(message, state)

    # Ошибка ушла через safe_answer; меню (message.answer) не показано.
    assert safe_answer.await_count == 1
    error_text = safe_answer.call_args.args[1]
    assert "слишком большой" in error_text.lower()
    message.answer.assert_not_called()

    # В состоянии нет данных о файле.
    data = await state.get_data()
    assert "file_id" not in data


@pytest.mark.asyncio
async def test_file_type_error_shows_error_without_menu(monkeypatch):
    """FileTypeError → сообщение о формате через safe_answer, меню не показано."""
    safe_answer = AsyncMock()
    monkeypatch.setattr(mh, "safe_answer", safe_answer)

    file_service = MagicMock()
    file_service.validate_file = MagicMock(
        side_effect=FileTypeError("application/pdf", ["MP3", "WAV"])
    )
    file_service.get_supported_formats = MagicMock(return_value=_SUPPORTED_FORMATS)
    media_handler = _media_handler_with_service(file_service)

    document = SimpleNamespace(file_id="PDF", file_name="doc.pdf", file_size=1000)
    message = _make_media_message("document", document)
    state = _fresh_state()

    await media_handler(message, state)

    assert safe_answer.await_count == 1
    error_text = safe_answer.call_args.args[1]
    assert "формат" in error_text.lower()
    message.answer.assert_not_called()

    data = await state.get_data()
    assert "file_id" not in data


# ---------------------------------------------------------------------------
# Точка 2: приём ссылки (_process_url)
# ---------------------------------------------------------------------------


class _FakeURLService:
    """Мок URLService — асинхронный контекст-менеджер."""

    def __init__(self, *, supported=True,
                 file_info=("meeting.mp3", 5 * 1024 * 1024, "https://direct/url"),
                 download_path="temp/meeting.mp3",
                 validate_exc=None):
        self._supported = supported
        self._file_info = file_info
        self._download_path = download_path
        self._validate_exc = validate_exc
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def is_supported_url(self, url):
        self.calls.append(("is_supported_url", url))
        return self._supported

    async def get_file_info(self, url):
        self.calls.append(("get_file_info", url))
        return self._file_info

    def validate_file_by_info(self, filename, size):
        self.calls.append(("validate_file_by_info", filename, size))
        if self._validate_exc:
            raise self._validate_exc

    async def download_file(self, url, filename):
        self.calls.append(("download_file", url, filename))
        return self._download_path

    def _call_names(self):
        return [c[0] for c in self.calls]


def _patch_url_flow(monkeypatch, fake_service):
    """Общие патчи для _process_url: URLService, safe_*, меню участников."""
    monkeypatch.setattr(mh, "URLService", lambda: fake_service)
    safe_answer = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(mh, "safe_answer", safe_answer)
    monkeypatch.setattr(mh, "safe_edit_text", AsyncMock())
    show_menu = AsyncMock()
    import src.handlers.participants_handlers as ph
    monkeypatch.setattr(ph, "show_participants_menu", show_menu)
    return show_menu, safe_answer


@pytest.mark.asyncio
async def test_supported_link_downloads_and_shows_record_actions_menu(monkeypatch):
    """Поддерживаемая ссылка → скачивание, внешняя запись в состоянии, меню действий с записью.

    После #71 ссылка получает то же меню «📎 Файл получен», что и файл, вместо
    прежнего немедленного меню участников — единая точка входа в обработку.
    """
    fake = _FakeURLService()
    show_menu, safe_answer = _patch_url_flow(monkeypatch, fake)

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111)
    message.chat = SimpleNamespace(id=222)
    message.answer = AsyncMock()
    state = _fresh_state()
    url = "https://drive.google.com/file/d/abc123/view"

    await mh._process_url(message, url, state, MagicMock())

    # Пройдены проверка, получение инфо, скачивание — в этом порядке.
    assert fake._call_names() == [
        "is_supported_url", "get_file_info", "validate_file_by_info", "download_file",
    ]

    # Внешняя запись сохранена в состояние.
    data = await state.get_data()
    assert data["file_path"] == "temp/meeting.mp3"
    assert data["file_name"] == "meeting.mp3"
    assert data["file_url"] == url
    assert data["is_external_file"] is True

    # Новое поведение: меню участников сразу НЕ открывается.
    show_menu.assert_not_awaited()

    # Показано меню действий с записью одной отправкой с двумя кнопками.
    menu = _menu_calls(safe_answer)
    assert len(menu) == 1
    menu_text = menu[0].args[1]
    assert "📎 **Файл получен**" in menu_text
    keyboard = menu[0].kwargs["reply_markup"]
    assert _callback_data_set(keyboard) == {"quick_process_file", "configure_file_processing"}


@pytest.mark.asyncio
async def test_unsupported_link_stops_before_download(monkeypatch):
    """Неподдерживаемая ссылка → ошибка, без скачивания и без меню участников."""
    fake = _FakeURLService(supported=False)
    show_menu, _ = _patch_url_flow(monkeypatch, fake)

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111)
    message.chat = SimpleNamespace(id=222)
    state = _fresh_state()

    await mh._process_url(message, "https://example.com/file", state, MagicMock())

    # Только проверка поддержки; ни инфо, ни скачивания.
    assert fake._call_names() == ["is_supported_url"]
    # Состояние не тронуто внешней записью.
    data = await state.get_data()
    assert "file_path" not in data
    assert "is_external_file" not in data
    # Меню участников не показано.
    show_menu.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_size_error_stops_before_download(monkeypatch):
    """FileSizeError при валидации → ошибка, без скачивания, без записи, без меню."""
    fake = _FakeURLService(
        file_info=("huge.mp4", 900 * 1024 * 1024, "https://direct/huge"),
        validate_exc=FileSizeError(900 * 1024 * 1024, 300 * 1024 * 1024),
    )
    show_menu, _ = _patch_url_flow(monkeypatch, fake)
    edit = mh.safe_edit_text  # AsyncMock из _patch_url_flow

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111)
    message.chat = SimpleNamespace(id=222)
    state = _fresh_state()

    await mh._process_url(message, "https://yadi.sk/i/abc123", state, MagicMock())

    # Дошли до валидации, но не до скачивания.
    assert fake._call_names() == ["is_supported_url", "get_file_info", "validate_file_by_info"]
    # Ни записи в состояние, ни меню участников.
    data = await state.get_data()
    assert "file_path" not in data
    show_menu.assert_not_awaited()
    # Последнее редактирование статуса — про размер файла.
    last_error = edit.call_args.args[1]
    assert "слишком большой" in last_error.lower()
