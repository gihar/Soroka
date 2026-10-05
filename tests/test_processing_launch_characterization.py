"""Характеризация запуска обработки из диалога (край хендлеров).

Снята с ``_process_file`` до выделения модуля «Запуск обработки» и
переведена на ``start_processing_from_dialog`` после переключения. Фиксирует:

- чтение FSM-словаря, сборку ``ProcessingRequest``, постановку в очередь,
  трекер позиции, ``message_id`` в БД, монитор позиции, очистку состояния;
  все ветки ошибок с их текстами (байт-в-байт);
- ``quick_process_file_callback`` — «Быстрая обработка»: шаблон по умолчанию
  или умный выбор, сохранённые участники;
- семь хендлеров выбора шаблона — каждый кладёт свой выбор и запускает
  обработку.

Осознанные изменения при переключении (раньше было иначе, см. историю):
``llm_provider`` в состоянии больше не нужен — его ставит запуск;
«умный выбор» — это ``template_id=0`` без флага ``use_smart_selection``.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.database as database_pkg
import src.handlers.callbacks.processing_callbacks as pc
import src.handlers.callbacks.template_callbacks as tc
import src.services.task_queue_manager as tqm_mod
import src.ux.queue_tracker as qt_mod
from src.config import settings
from src.models.task_queue import TaskPriority
from src.ux.message_builder import RECORD_LOST_FILE, RECORD_LOST_LINK

USER_ID = 111
CHAT_ID = 222

TEMPLATE_NOT_CHOSEN = (
    "❌ Шаблон не выбран.\n"
    "Отправьте запись заново и выберите шаблон."
)
LAUNCH_FAILED = (
    "❌ Не получилось запустить обработку.\n"
    "Отправьте запись заново."
)


# ---------------------------------------------------------------------------
# Фейки на границе: очередь, трекер, БД
# ---------------------------------------------------------------------------


class _FakeQueue:
    """Очередь обработки: копит запросы; позиции выдаёт по списку.

    Первый запрос позиции — момент постановки; следующие — опросы монитора.
    Когда список кончился, задача «ушла в работу» (позиция None).
    """

    def __init__(self, positions=(0,), size=1, fail=None):
        self.add_task_calls = []
        self._positions = list(positions)
        self._size = size
        self._fail = fail

    async def add_task(self, request, chat_id, priority):
        if self._fail:
            raise self._fail
        self.add_task_calls.append(
            SimpleNamespace(request=request, chat_id=chat_id, priority=priority)
        )
        return SimpleNamespace(task_id="TASK-1", message_id=None)

    async def get_queue_position(self, task_id):
        return self._positions.pop(0) if self._positions else None

    async def get_queue_size(self):
        return self._size


class _FakeTracker:
    def __init__(self, message_id):
        self.message_id = message_id
        self.is_active = True
        self.updates = []
        self.deleted = False

    async def update_position(self, position, total):
        self.updates.append((position, total))

    async def delete_message(self):
        self.deleted = True
        self.is_active = False


class _FakeTrackerFactory:
    def __init__(self, message_id=None):
        self.calls = []
        self.trackers = []
        self._message_id = message_id

    async def create_tracker(self, **kwargs):
        self.calls.append(kwargs)
        tracker = _FakeTracker(self._message_id)
        self.trackers.append(tracker)
        return tracker


class _FakeQueueRepo:
    def __init__(self):
        self.calls = []

    async def update_queue_task_message_id(self, task_id, message_id):
        self.calls.append((task_id, message_id))


class _FakeUserService:
    def __init__(self, user=None):
        self._user = user

    async def get_user_by_telegram_id(self, telegram_id):
        return self._user


class _FakeTemplateService:
    def __init__(self, templates=()):
        self._templates = {t.id: t for t in templates}
        self.defaults = []

    async def get_template_by_id(self, template_id):
        return self._templates.get(template_id)

    async def set_user_default_template(self, user_id, template_id):
        self.defaults.append((user_id, template_id))


def _fresh_state():
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=CHAT_ID, user_id=USER_ID),
    )


def _make_callback(data=""):
    callback = MagicMock()
    callback.data = data
    callback.from_user = SimpleNamespace(id=USER_ID)
    callback.bot = MagicMock(name="bot")
    message = MagicMock()
    message.chat = SimpleNamespace(id=CHAT_ID)
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    callback.message = message
    callback.answer = AsyncMock()
    return callback


class _Env(SimpleNamespace):
    """Подменённая инфраструктура одного прогона."""


@pytest.fixture
def env(monkeypatch):
    def build(*, positions=(0,), size=1, fail=None, tracker_message_id=None):
        queue = _FakeQueue(positions=positions, size=size, fail=fail)
        factory = _FakeTrackerFactory(message_id=tracker_message_id)
        repo = _FakeQueueRepo()
        edits = AsyncMock()
        monkeypatch.setattr(tqm_mod, "task_queue_manager", queue)
        monkeypatch.setattr(qt_mod, "QueueTrackerFactory", factory)
        monkeypatch.setattr(database_pkg, "queue_repo", repo)
        monkeypatch.setattr(pc, "safe_edit_text", edits)
        monkeypatch.setattr(tc, "safe_edit_text", edits)
        monkeypatch.setattr(settings, "queue_update_interval", 0)
        return _Env(queue=queue, factory=factory, repo=repo, edits=edits)

    return build


async def _settle():
    """Дать фоновому монитору позиции доработать до выхода."""
    for _ in range(5):
        await asyncio.sleep(0)


def _edited_texts(edits):
    return [c.args[1] for c in edits.await_args_list]


async def _run_launch(state, callback=None):
    callback = callback or _make_callback()
    await pc.start_processing_from_dialog(callback, state)
    await _settle()
    return callback


# ---------------------------------------------------------------------------
# Запуск из диалога: успешная постановка
# ---------------------------------------------------------------------------


async def test_telegram_record_with_template_builds_full_request(env):
    e = env()
    state = _fresh_state()
    participants = [{"name": "Иван Иванов", "role": "РП"}]
    await state.update_data(
        file_id="TG_FILE", file_name="rec.mp3",
        template_id=7,
        participants_list=participants,
        meeting_topic="Бюджет", meeting_date="5 октября 2026", meeting_time="10:00",
        protocol_info={"meeting_agenda": "1. Итоги", "project_list": "Альфа"},
    )

    await _run_launch(state)

    assert len(e.queue.add_task_calls) == 1
    call = e.queue.add_task_calls[0]
    assert call.chat_id == CHAT_ID
    assert call.priority == TaskPriority.NORMAL
    r = call.request
    assert (r.file_id, r.file_path, r.file_url, r.is_external_file) == ("TG_FILE", None, None, False)
    assert r.file_name == "rec.mp3"
    assert r.template_id == 7
    assert r.llm_provider == "openai"
    assert r.user_id == USER_ID
    assert r.language == "ru"
    assert r.participants_list == participants
    assert (r.meeting_topic, r.meeting_date, r.meeting_time) == ("Бюджет", "5 октября 2026", "10:00")
    assert (r.meeting_agenda, r.project_list) == ("1. Итоги", "Альфа")
    assert r.model_preset_key is None
    assert r.speaker_mapping is None


async def test_external_record_goes_by_path_and_url_without_file_id(env):
    e = env()
    state = _fresh_state()
    await state.update_data(
        file_id="STALE", file_path="temp/drive.mp3", file_name="drive.mp3",
        file_url="https://drive.google.com/file/d/abc/view", is_external_file=True,
        template_id=3,
    )

    await _run_launch(state)

    r = e.queue.add_task_calls[0].request
    assert r.is_external_file is True
    assert r.file_id is None
    assert r.file_path == "temp/drive.mp3"
    assert r.file_url == "https://drive.google.com/file/d/abc/view"
    assert r.file_name == "drive.mp3"


async def test_telegram_record_ignores_stale_external_path(env):
    e = env()
    state = _fresh_state()
    await state.update_data(
        file_id="TG", file_path="temp/old.mp3", file_name="rec.mp3",
        template_id=3,
    )

    await _run_launch(state)

    r = e.queue.add_task_calls[0].request
    assert (r.file_id, r.file_path, r.is_external_file) == ("TG", None, False)


async def test_smart_selection_queues_template_zero(env):
    e = env()
    state = _fresh_state()
    await state.update_data(
        file_id="TG", file_name="rec.mp3",
        template_id=0,
    )

    await _run_launch(state)

    assert e.queue.add_task_calls[0].request.template_id == 0


async def test_meeting_details_absent_stay_none(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)

    r = e.queue.add_task_calls[0].request
    assert r.participants_list is None
    assert (r.meeting_topic, r.meeting_date, r.meeting_time) == (None, None, None)
    assert (r.meeting_agenda, r.project_list) == (None, None)


async def test_successful_launch_dismisses_choice_shows_position_and_clears_state(env):
    e = env(positions=(2,), size=5)
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)
    callback = _make_callback()

    await _run_launch(state, callback)

    callback.message.delete.assert_awaited_once()
    assert e.factory.calls == [dict(
        bot=callback.bot, chat_id=CHAT_ID, task_id="TASK-1",
        initial_position=2, total_in_queue=5,
    )]
    assert await state.get_data() == {}
    e.edits.assert_not_awaited()


async def test_unknown_position_shown_as_zero(env):
    e = env(positions=(), size=1)
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)

    assert e.factory.calls[0]["initial_position"] == 0


async def test_failed_dismiss_does_not_stop_launch(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)
    callback = _make_callback()
    callback.message.delete = AsyncMock(side_effect=RuntimeError("message gone"))

    await _run_launch(state, callback)

    assert len(e.queue.add_task_calls) == 1
    assert len(e.factory.calls) == 1
    assert await state.get_data() == {}


async def test_tracker_message_id_is_saved_to_queue_task(env):
    e = env(tracker_message_id=555)
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)

    assert e.repo.calls == [("TASK-1", 555)]


async def test_tracker_without_message_skips_db_update(env):
    e = env(tracker_message_id=None)
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)

    assert e.repo.calls == []


async def test_monitor_follows_position_until_task_leaves_queue(env):
    # Постановка видит 3, монитор — 2 и 1, затем задача уходит в работу.
    e = env(positions=(3, 2, 1), size=4)
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)
    await _settle()

    tracker = e.factory.trackers[0]
    assert tracker.updates == [(2, 4), (1, 4)]
    assert tracker.deleted is True


# ---------------------------------------------------------------------------
# Запуск из диалога: ветки ошибок
# ---------------------------------------------------------------------------


async def _assert_rejected(e, state, expected_text):
    assert e.queue.add_task_calls == []
    assert _edited_texts(e.edits) == [expected_text]
    assert await state.get_data() == {}


async def test_llm_provider_is_not_needed_in_state(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)

    await _run_launch(state)

    assert e.queue.add_task_calls[0].request.llm_provider == "openai"


async def test_missing_template_rejected(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3")

    await _run_launch(state)

    await _assert_rejected(e, state, TEMPLATE_NOT_CHOSEN)


async def test_smart_flag_without_template_id_is_not_a_choice(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", use_smart_selection=True)

    await _run_launch(state)

    await _assert_rejected(e, state, TEMPLATE_NOT_CHOSEN)


@pytest.mark.parametrize("record", [
    {"file_name": "rec.mp3"},
    {"file_id": "TG"},
    {},
])
async def test_lost_telegram_record_rejected(env, record):
    e = env()
    state = _fresh_state()
    await state.update_data(**record, template_id=2)

    await _run_launch(state)

    await _assert_rejected(e, state, RECORD_LOST_FILE)


@pytest.mark.parametrize("record", [
    {"file_name": "drive.mp3"},
    {"file_path": "temp/drive.mp3"},
    {"file_id": "TG", "file_name": "drive.mp3"},
])
async def test_lost_external_record_rejected(env, record):
    e = env()
    state = _fresh_state()
    await state.update_data(**record, is_external_file=True, template_id=2)

    await _run_launch(state)

    await _assert_rejected(e, state, RECORD_LOST_LINK)


async def test_template_checked_before_record(env):
    e = env()
    state = _fresh_state()  # ни шаблона, ни записи

    await _run_launch(state)

    await _assert_rejected(e, state, TEMPLATE_NOT_CHOSEN)


async def test_queue_failure_reports_launch_failed(env):
    e = env(fail=RuntimeError("queue down"))
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", template_id=2)
    callback = _make_callback()

    await _run_launch(state, callback)

    assert _edited_texts(e.edits) == [LAUNCH_FAILED]
    assert await state.get_data() == {}
    callback.message.delete.assert_not_awaited()
    assert e.factory.calls == []


# ---------------------------------------------------------------------------
# «Быстрая обработка»
# ---------------------------------------------------------------------------


def _find_callback(router, name):
    return next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == name
    )


async def _run_quick(state, user=None):
    router = pc.setup_processing_callbacks(_FakeUserService(user), MagicMock(), MagicMock())
    callback = _make_callback("quick_process_file")
    await _find_callback(router, "quick_process_file_callback")(callback, state)
    await _settle()
    return callback


async def test_quick_process_brings_saved_participants(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3")
    user = SimpleNamespace(
        default_template_id=None,
        saved_participants='[{"name": "Иван Иванов", "role": "РП"}]',
    )

    await _run_quick(state, user)

    r = e.queue.add_task_calls[0].request
    assert r.participants_list == [{"name": "Иван Иванов", "role": "РП"}]
    assert r.template_id == 0
    assert r.llm_provider == "openai"


async def test_quick_process_broken_saved_participants_go_as_none(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3")
    user = SimpleNamespace(default_template_id=4, saved_participants="{битый json")

    await _run_quick(state, user)

    r = e.queue.add_task_calls[0].request
    assert r.participants_list is None
    assert r.template_id == 4


async def test_quick_process_announces_start_then_clears_state(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", meeting_topic="Старая тема")

    callback = await _run_quick(state)

    assert _edited_texts(e.edits) == ["<b>Быстрая обработка</b>\n\n⏳ Начинаю обработку..."]
    callback.message.delete.assert_awaited_once()
    assert await state.get_data() == {}


async def test_quick_process_keeps_meeting_details_from_state(env):
    e = env()
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3", meeting_topic="Бюджет")

    await _run_quick(state)

    assert e.queue.add_task_calls[0].request.meeting_topic == "Бюджет"


async def test_quick_process_without_file_answers_and_does_not_queue(env):
    e = env()
    state = _fresh_state()

    callback = await _run_quick(state)

    assert e.queue.add_task_calls == []
    callback.answer.assert_awaited_once_with("❌ Файл не найден. Отправьте файл заново.")
    e.edits.assert_not_awaited()


async def test_quick_process_external_record_without_flag_is_lost_file(env):
    # Путь есть, но флага внешней записи нет — проверка «есть файл» пропускает,
    # а запуск считает запись Telegram-файлом без file_id.
    e = env()
    state = _fresh_state()
    await state.update_data(file_path="temp/x.mp3", file_name="x.mp3")

    await _run_quick(state)

    assert e.queue.add_task_calls == []
    assert _edited_texts(e.edits)[-1] == RECORD_LOST_FILE


# ---------------------------------------------------------------------------
# Хендлеры выбора шаблона
# ---------------------------------------------------------------------------


async def _run_template_handler(name, data, *, user=None, templates=()):
    template_service = _FakeTemplateService(templates)
    router = tc.setup_template_callbacks(_FakeUserService(user), template_service, MagicMock())
    state = _fresh_state()
    await state.update_data(file_id="TG", file_name="rec.mp3")
    callback = _make_callback(data)
    await _find_callback(router, name)(callback, state)
    await _settle()
    return SimpleNamespace(state=state, callback=callback, templates=template_service)


_TEMPLATE = SimpleNamespace(id=7, name="Планёрка")


@pytest.mark.parametrize("name,data,user,expected_template", [
    ("select_template_id_callback", "select_template_id_7", None, 7),
    ("select_template_callback", "select_template_7", None, 7),
    ("use_default_template_callback", "use_default_template_7", None, 7),
    ("smart_template_selection_callback", "smart_template_selection", None, 0),
    ("quick_smart_selection_callback", "quick_smart_select", None, 0),
    ("use_saved_default_callback", "use_saved_default", SimpleNamespace(default_template_id=7), 7),
    ("quick_template_callback", "quick_template_7", None, 7),
    ("quick_template_callback", "quick_template_smart", None, 0),
])
async def test_template_handler_queues_its_choice(env, name, data, user, expected_template):
    e = env()

    run = await _run_template_handler(name, data, user=user, templates=[_TEMPLATE])

    assert len(e.queue.add_task_calls) == 1
    r = e.queue.add_task_calls[0].request
    assert r.template_id == expected_template
    assert r.llm_provider == "openai"
    assert r.file_id == "TG"
    assert await run.state.get_data() == {}


async def test_saved_default_smart_launches_smart_selection(env):
    # Меню записи показывает «Протокол: Умный выбор (по умолчанию)», когда
    # default_template_id == 0, — и эта кнопка обязана запускать умный выбор,
    # а не отвечать «не установлен».
    e = env()

    run = await _run_template_handler(
        "use_saved_default_callback", "use_saved_default",
        user=SimpleNamespace(default_template_id=0),
    )

    assert len(e.queue.add_task_calls) == 1
    assert e.queue.add_task_calls[0].request.template_id == 0
    assert "Умный выбор" in _edited_texts(e.edits)[0]
    assert await run.state.get_data() == {}


async def test_saved_default_absent_is_reported(env):
    e = env()

    await _run_template_handler(
        "use_saved_default_callback", "use_saved_default",
        user=SimpleNamespace(default_template_id=None),
    )

    assert e.queue.add_task_calls == []
    assert "У вас не установлен шаблон по умолчанию." in _edited_texts(e.edits)[-1]


async def test_quick_template_saves_default_before_launch(env):
    e = env()

    run = await _run_template_handler("quick_template_callback", "quick_template_7", templates=[_TEMPLATE])

    assert run.templates.defaults == [(USER_ID, 7)]
    assert len(e.queue.add_task_calls) == 1


@pytest.mark.parametrize("name,data", [
    ("select_template_id_callback", "select_template_id_99"),
    ("quick_template_callback", "quick_template_99"),
])
async def test_unknown_template_does_not_queue(env, name, data):
    e = env()

    run = await _run_template_handler(name, data)

    assert e.queue.add_task_calls == []
    assert "Шаблон не найден." in _edited_texts(e.edits)[-1]
    assert (await run.state.get_data())["file_id"] == "TG"
