"""Модуль «Запуск обработки» через его интерфейс.

Вход — принятая Запись и выбор пользователя; выход — задача в Очереди
обработки, показанная позиция и монитор позиции. Канал (Telegram) и очередь
подставляются фейками на границе.
"""

import asyncio
from types import SimpleNamespace

import pytest

from src.config import settings
from src.models.task_queue import TaskPriority
from src.services.processing_launch import (
    SMART_SELECTION,
    ExternalRecord,
    MeetingDetails,
    ProcessingChoice,
    RecordLost,
    SpecificTemplate,
    TelegramRecord,
    TemplateNotChosen,
    launch_processing,
)

USER_ID = 111
CHAT_ID = 222


class _FakeQueue:
    def __init__(self, positions=(0,), size=1):
        self.added = []
        self._positions = list(positions)
        self._size = size

    async def add_task(self, request, chat_id, priority):
        self.added.append(SimpleNamespace(request=request, chat_id=chat_id, priority=priority))
        return SimpleNamespace(task_id="TASK-1", message_id=None)

    async def get_queue_position(self, task_id):
        return self._positions.pop(0) if self._positions else None

    async def get_queue_size(self):
        return self._size


class _FakeDisplay:
    def __init__(self, message_id=None):
        self.message_id = message_id
        self.is_active = True
        self.updates = []
        self.deleted = False

    async def update_position(self, position, total):
        self.updates.append((position, total))

    async def delete_message(self):
        self.deleted = True
        self.is_active = False


class _FakeChannel:
    def __init__(self, message_id=None):
        self.events = []
        self.displays = []
        self._message_id = message_id

    async def dismiss_choice(self):
        self.events.append("dismiss")

    async def show_queue_position(self, task_id, position, total):
        self.events.append(("show", task_id, position, total))
        display = _FakeDisplay(self._message_id)
        self.displays.append(display)
        return display


class _FakeQueueRepo:
    def __init__(self):
        self.calls = []

    async def update_queue_task_message_id(self, task_id, message_id):
        self.calls.append((task_id, message_id))


@pytest.fixture(autouse=True)
def _fast_monitor(monkeypatch):
    monkeypatch.setattr(settings, "queue_update_interval", 0)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def _launch(record, choice, *, queue=None, channel=None, repo=None):
    queue = queue or _FakeQueue()
    channel = channel or _FakeChannel()
    repo = repo or _FakeQueueRepo()
    task_id = await launch_processing(
        record, choice,
        user_id=USER_ID, chat_id=CHAT_ID,
        channel=channel, queue=queue, queue_repo=repo,
    )
    await _settle()
    return SimpleNamespace(task_id=task_id, queue=queue, channel=channel, repo=repo)


async def test_telegram_record_with_specific_template_is_queued():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SpecificTemplate(7)),
    )

    assert run.task_id == "TASK-1"
    [added] = run.queue.added
    assert added.chat_id == CHAT_ID
    assert added.priority == TaskPriority.NORMAL
    r = added.request
    assert (r.file_id, r.file_path, r.file_url, r.is_external_file) == ("TG", None, None, False)
    assert r.file_name == "rec.mp3"
    assert r.template_id == 7
    assert r.llm_provider == "openai"
    assert r.user_id == USER_ID
    assert r.language == "ru"


async def test_external_record_is_queued_by_path_and_original_url():
    run = await _launch(
        ExternalRecord(
            file_path="temp/drive.mp3", file_name="drive.mp3",
            file_url="https://drive.google.com/file/d/abc/view",
        ),
        ProcessingChoice(template=SpecificTemplate(3)),
    )

    r = run.queue.added[0].request
    assert r.is_external_file is True
    assert r.file_id is None
    assert r.file_path == "temp/drive.mp3"
    assert r.file_url == "https://drive.google.com/file/d/abc/view"
    assert r.file_name == "drive.mp3"


async def test_smart_selection_is_queued_as_template_zero():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
    )

    assert run.queue.added[0].request.template_id == 0


async def test_participants_and_meeting_details_reach_the_request():
    participants = [{"name": "Иван Иванов", "role": "РП"}]
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(
            template=SpecificTemplate(7),
            participants=participants,
            meeting=MeetingDetails(
                topic="Бюджет", date="5 октября 2026", time="10:00",
                agenda="1. Итоги", projects="Альфа",
            ),
        ),
    )

    r = run.queue.added[0].request
    assert r.participants_list == participants
    assert (r.meeting_topic, r.meeting_date, r.meeting_time) == ("Бюджет", "5 октября 2026", "10:00")
    assert (r.meeting_agenda, r.project_list) == ("1. Итоги", "Альфа")


async def test_choice_without_details_queues_empty_meeting():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
    )

    r = run.queue.added[0].request
    assert r.participants_list is None
    assert (r.meeting_topic, r.meeting_date, r.meeting_time) == (None, None, None)
    assert (r.meeting_agenda, r.project_list) == (None, None)


# ---------------------------------------------------------------------------
# Ошибки входа
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("file_id,file_name", [(None, "rec.mp3"), ("TG", None), ("", "")])
def test_telegram_record_without_file_or_name_is_lost(file_id, file_name):
    with pytest.raises(RecordLost) as caught:
        TelegramRecord(file_id=file_id, file_name=file_name)
    assert caught.value.external is False


@pytest.mark.parametrize("file_path,file_name", [(None, "drive.mp3"), ("temp/d.mp3", None)])
def test_external_record_without_path_or_name_is_lost(file_path, file_name):
    with pytest.raises(RecordLost) as caught:
        ExternalRecord(file_path=file_path, file_name=file_name)
    assert caught.value.external is True


@pytest.mark.parametrize("template_id", [None, 0])
def test_specific_template_needs_real_id(template_id):
    with pytest.raises(TemplateNotChosen):
        SpecificTemplate(template_id)


# ---------------------------------------------------------------------------
# Канал: выбор убран, позиция показана, монитор следит
# ---------------------------------------------------------------------------


async def test_launch_dismisses_choice_then_shows_queue_position():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
        queue=_FakeQueue(positions=(2,), size=5),
    )

    assert run.channel.events == ["dismiss", ("show", "TASK-1", 2, 5)]


async def test_unknown_position_is_shown_as_zero():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
        queue=_FakeQueue(positions=(), size=1),
    )

    assert run.channel.events[-1] == ("show", "TASK-1", 0, 1)


async def test_position_message_is_remembered_by_the_queue_task():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
        channel=_FakeChannel(message_id=555),
    )

    assert run.repo.calls == [("TASK-1", 555)]


async def test_position_not_shown_leaves_queue_task_untouched():
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
        channel=_FakeChannel(message_id=None),
    )

    assert run.repo.calls == []


async def test_monitor_follows_position_until_processing_starts():
    # Постановка видит 3, монитор — 2 и 1, затем задача уходит в работу.
    run = await _launch(
        TelegramRecord(file_id="TG", file_name="rec.mp3"),
        ProcessingChoice(template=SMART_SELECTION),
        queue=_FakeQueue(positions=(3, 2, 1), size=4),
    )
    await _settle()

    display = run.channel.displays[0]
    assert display.updates == [(2, 4), (1, 4)]
    assert display.deleted is True


async def test_queue_failure_propagates_without_touching_channel():
    class _BrokenQueue(_FakeQueue):
        async def add_task(self, request, chat_id, priority):
            raise RuntimeError("queue down")

    channel = _FakeChannel()
    with pytest.raises(RuntimeError):
        await _launch(
            TelegramRecord(file_id="TG", file_name="rec.mp3"),
            ProcessingChoice(template=SMART_SELECTION),
            queue=_BrokenQueue(), channel=channel,
        )

    assert channel.events == []
