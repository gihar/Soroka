"""Запуск обработки: принятая Запись + выбор пользователя → задача в Очереди.

Единственная точка, где запись ставится в Очередь обработки. Вход явный и
типизированный — без FSM-словаря aiogram: какую запись обработать (Telegram-
файл или внешняя запись), как выбран шаблон (конкретный или умный выбор),
участники и данные о встрече. Модуль сам собирает ``ProcessingRequest``
(LLM-путь задаёт активный пресет модели, ADR-0007), ставит задачу в очередь,
показывает позицию через канал и следит за ней до начала обработки.

Канал (Telegram) — за протоколом ``LaunchChannel``: модуль не знает ни бота,
ни сообщений с кнопками.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Union

from loguru import logger

from src.config import settings
from src.models.processing import ProcessingRequest
from src.models.task_queue import TaskPriority
from src.utils.request_diagnostics import log_meeting_inputs

# Имя провайдера в запросе историческое: модель и адрес определяет активный
# пресет модели в момент обработки (ADR-0007).
_LLM_PROVIDER = "openai"


# ---------------------------------------------------------------------------
# Ошибки входа
# ---------------------------------------------------------------------------


class LaunchInputError(Exception):
    """Вход запуска неполон: обработку не начать."""


class TemplateNotChosen(LaunchInputError):
    """Не выбран ни конкретный шаблон, ни умный выбор."""


class RecordLost(LaunchInputError):
    """Запись потеряна: нечего обрабатывать.

    ``external`` отличает внешнюю запись (ссылку) от Telegram-файла — тексты
    пользователю у них разные.
    """

    def __init__(self, *, external: bool):
        self.external = external
        kind = "внешняя запись" if external else "Telegram-файл"
        super().__init__(f"Запись потеряна: {kind}")


# ---------------------------------------------------------------------------
# Вход
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelegramRecord:
    """Запись, присланная файлом в Telegram."""

    file_id: str
    file_name: str

    def __post_init__(self):
        if not self.file_id or not self.file_name:
            raise RecordLost(external=False)


@dataclass(frozen=True)
class ExternalRecord:
    """Запись по ссылке, уже скачанная во временный файл."""

    file_path: str
    file_name: str
    file_url: Optional[str] = None

    def __post_init__(self):
        if not self.file_path or not self.file_name:
            raise RecordLost(external=True)


Record = Union[TelegramRecord, ExternalRecord]


@dataclass(frozen=True)
class SmartSelection:
    """Умный выбор: шаблон подберёт ИИ после транскрипции."""


SMART_SELECTION = SmartSelection()


@dataclass(frozen=True)
class SpecificTemplate:
    """Конкретный шаблон, выбранный пользователем."""

    template_id: int

    def __post_init__(self):
        if not self.template_id:
            raise TemplateNotChosen()


TemplateChoice = Union[SmartSelection, SpecificTemplate]


@dataclass(frozen=True)
class MeetingDetails:
    """Данные о встрече, известные до обработки."""

    topic: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    agenda: Optional[str] = None
    projects: Optional[str] = None


@dataclass(frozen=True)
class ProcessingChoice:
    """Выбор пользователя для одной обработки."""

    template: TemplateChoice
    participants: Optional[List[Dict[str, str]]] = None
    meeting: MeetingDetails = field(default_factory=MeetingDetails)


# ---------------------------------------------------------------------------
# Канал
# ---------------------------------------------------------------------------


class QueuePositionDisplay(Protocol):
    """Показанная пользователю позиция задачи в очереди."""

    message_id: Optional[int]
    is_active: bool

    async def update_position(self, position: int, total: int) -> None: ...

    async def delete_message(self) -> None: ...


class LaunchChannel(Protocol):
    """Канал, через который пользователь видит запуск."""

    async def dismiss_choice(self) -> None:
        """Убрать экран выбора, с которого запущена обработка."""

    async def show_queue_position(
        self, task_id: str, position: int, total: int,
    ) -> QueuePositionDisplay:
        """Показать позицию задачи в очереди."""


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------


def _build_request(record: Record, choice: ProcessingChoice, user_id: int) -> ProcessingRequest:
    is_external = isinstance(record, ExternalRecord)
    template_id = (
        choice.template.template_id if isinstance(choice.template, SpecificTemplate) else 0
    )
    return ProcessingRequest(
        file_id=None if is_external else record.file_id,
        file_path=record.file_path if is_external else None,
        file_name=record.file_name,
        file_url=record.file_url if is_external else None,
        template_id=template_id,
        llm_provider=_LLM_PROVIDER,
        user_id=user_id,
        language="ru",
        is_external_file=is_external,
        participants_list=choice.participants,
        meeting_topic=choice.meeting.topic,
        meeting_date=choice.meeting.date,
        meeting_time=choice.meeting.time,
        meeting_agenda=choice.meeting.agenda,
        project_list=choice.meeting.projects,
    )


async def launch_processing(
    record: Record,
    choice: ProcessingChoice,
    *,
    user_id: int,
    chat_id: int,
    channel,
    queue=None,
    queue_repo=None,
) -> str:
    """Поставить запись в Очередь обработки; вернуть id задачи.

    После постановки убирает экран выбора, показывает позицию в очереди,
    запоминает сообщение с позицией в задаче и запускает фоновый монитор
    позиции. Ошибка постановки пробрасывается — канал при этом не тронут.
    ``queue``/``queue_repo`` по умолчанию — глобальные очередь и репозиторий.
    """
    if queue is None:
        from src.services.task_queue_manager import task_queue_manager as queue
    if queue_repo is None:
        from src.database import queue_repo

    meeting = choice.meeting
    log_meeting_inputs(
        "очередь",
        participants_list=choice.participants,
        meeting_topic=meeting.topic,
        meeting_date=meeting.date,
        meeting_time=meeting.time,
        meeting_agenda=meeting.agenda,
        project_list=meeting.projects,
    )

    request = _build_request(record, choice, user_id)
    queued_task = await queue.add_task(
        request=request, chat_id=chat_id, priority=TaskPriority.NORMAL,
    )
    task_id = str(queued_task.task_id)

    await channel.dismiss_choice()

    position = await queue.get_queue_position(task_id)
    total_in_queue = await queue.get_queue_size()
    display = await channel.show_queue_position(
        task_id, position if position is not None else 0, total_in_queue,
    )

    if display.message_id:
        queued_task.message_id = display.message_id
        await queue_repo.update_queue_task_message_id(task_id, display.message_id)

    asyncio.create_task(_monitor_queue_position(display, task_id, queue))

    logger.info(f"Задача {task_id} поставлена в очередь")
    return task_id


async def _monitor_queue_position(display: QueuePositionDisplay, task_id: str, queue) -> None:
    """Следить за позицией задачи, пока она не уйдёт в работу."""
    try:
        while display.is_active:
            position = await queue.get_queue_position(task_id)

            # Задачи больше нет в очереди — обработка началась или завершена.
            if position is None:
                await display.delete_message()
                break

            total = await queue.get_queue_size()
            await display.update_position(position, total)
            await asyncio.sleep(settings.queue_update_interval)

    except asyncio.CancelledError:
        logger.debug(f"Мониторинг позиции задачи {task_id} отменен")
    except Exception as e:
        logger.error(f"Ошибка в мониторинге позиции задачи {task_id}: {e}")
