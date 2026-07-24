"""Имена одним сообщением в главном виде Карточки сопоставления (issue #100).

Финальный слайс прямого ввода: при открытой карточке в ГЛАВНОМ виде (сессия жива,
``editing_speaker`` не задан) текстовое сообщение раскладывается по неназванным
спикерам. Тесты описывают наблюдаемое поведение через публичный интерфейс —
чистую функцию разбора имён и роутер сопоставления в окружении соседних роутеров
(как в ``bot.py``), — не завязываясь на внутренний механизм.

Разложены по разделам: РАЗБОР (чистая функция парс+валидация), РАСКЛАДКА
(наблюдаемое применение через хендлер), ТЕКСТЫ (строка-приглашение карточки).
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram import F, Router
from aiogram.filters import StateFilter

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402

from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.storage.base import StorageKey  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

import src.handlers.callbacks.speaker_mapping_callbacks as cb  # noqa: E402
import src.utils.telegram_safe as ts  # noqa: E402
from src.models.diarization import Diarization, Segment  # noqa: E402
from src.models.processing import ProcessingRequest, TranscriptionResult  # noqa: E402
from src.performance.metrics import ProcessingMetrics  # noqa: E402
from src.services.mapping_session import MappingSession, mapping_sessions  # noqa: E402
from src.services.participants_service import participants_service  # noqa: E402

_BOT_ID = 123456


# ---------------------------------------------------------------------------
# РАЗБОР: чистая функция парсинга + валидации имён (всё или ничего)
# ---------------------------------------------------------------------------


def test_parse_splits_comma_separated_names():
    """«Аня, Тимур, Лена» → три триммленных имени по порядку."""
    assert participants_service.parse_manual_names("Аня, Тимур, Лена") == [
        "Аня",
        "Тимур",
        "Лена",
    ]


def test_parse_keeps_single_name_with_internal_space():
    """Без разделителей — одно имя; пробел внутри законен («Анна Петровна»)."""
    assert participants_service.parse_manual_names("Анна Петровна") == ["Анна Петровна"]


def test_parse_splits_on_newlines():
    """Перенос строки — тоже разделитель; пустые строки отбрасываются."""
    assert participants_service.parse_manual_names("Аня\nТимур\n\nЛена") == [
        "Аня",
        "Тимур",
        "Лена",
    ]


def test_name_bar_accepts_normal_and_rejects_out_of_range():
    """Планка имени: 2–50 символов, не начинается с «/»."""
    from src.services.participants_service import is_valid_manual_name

    assert is_valid_manual_name("Аня") is True
    assert is_valid_manual_name("И") is False  # короче двух
    assert is_valid_manual_name("Я" * 51) is False  # длиннее пятидесяти
    assert is_valid_manual_name("/start") is False  # начинается с «/»


# ---------------------------------------------------------------------------
# Инфраструктура: сессия, фейковые сообщения, мини-диспетчер (как в bot.py)
# ---------------------------------------------------------------------------


def _diarization(*speakers: str) -> Diarization:
    """Диаризация по одному сегменту на спикера — порядок появления = порядок строк."""
    return Diarization(segments=[
        Segment(start=float(i), end=float(i) + 1, speaker=s, text=f"реплика {s}")
        for i, s in enumerate(speakers)
    ])


def _make_session(participants=None, speaker_mapping=None, user_id=42, speakers=None):
    speakers = speakers or ("SPEAKER_1", "SPEAKER_2", "SPEAKER_3")
    request = ProcessingRequest(
        user_id=user_id, file_name="встреча.mp3", template_id=2,
        llm_provider="openai", participants_list=participants,
    )
    transcription = TranscriptionResult(
        transcription="текст",
        diarization=_diarization(*speakers),
        compression_info=None,
    )
    return MappingSession(
        request=request,
        transcription_result=transcription,
        speaker_mapping=dict(speaker_mapping or {}),
        meeting_type="general",
        temp_file_path=None,
        cache_key=None,
        task_id=None,
        metrics=ProcessingMetrics(
            file_name="встреча.mp3", user_id=user_id, start_time=datetime.now()
        ),
    )


def _make_fsm(user_id: int) -> FSMContext:
    key = StorageKey(bot_id=_BOT_ID, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=MemoryStorage(), key=key)


class _FakeMessage:
    def __init__(self, user_id, text=""):
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.bot = SimpleNamespace()
        self.replies = []

    async def answer(self, text=None, **kwargs):
        self.replies.append(text)


async def _noop(**kwargs):
    return None


def _mapping_router(processing_service=None):
    processing_service = processing_service or SimpleNamespace(
        continue_processing_after_mapping_confirmation=_noop
    )
    return cb.setup_speaker_mapping_callbacks(
        SimpleNamespace(), SimpleNamespace(), processing_service
    )


async def _deliver_message(routers, message, state):
    """Мини-диспетчер: гоняет сообщение по роутерам В ПОРЯДКЕ включения, отдаёт
    первому подошедшему message-хендлеру (как aiogram) и возвращает роутер-победитель.
    """
    raw_state = await state.get_state()
    ctx = {
        "state": state,
        "raw_state": raw_state,
        "event_from_user": getattr(message, "from_user", None),
    }
    for router in routers:
        for handler in router.message.handlers:
            matched, data = await handler.check(message, **ctx)
            if matched:
                await handler.call(message, **data)
                return router
    return None


def _wall_routers(mapping_router):
    """Роутеры в порядке bot.py: команды и quick-actions ДО роутера сопоставления,
    общий текстовый (обрабатывает запись/ссылку) — ПОСЛЕ."""
    caught = {"winner": None}

    command_router = Router()

    def _is_command(message) -> bool:
        text = getattr(message, "text", None)
        return bool(text) and text.startswith("/")

    @command_router.message(_is_command)
    async def _command(message):
        caught["winner"] = "command"

    quick_actions_router = Router()

    @quick_actions_router.message(F.text == "⚙️ Настройки")
    async def _menu(message):
        caught["winner"] = "menu"

    general_router = Router()

    @general_router.message(StateFilter(None))
    async def _general(message):
        caught["winner"] = "general"

    routers = [command_router, quick_actions_router, mapping_router, general_router]
    return routers, caught


@pytest.fixture(autouse=True)
def _patch_card_render(monkeypatch):
    """Отправитель карточек ходит в Telegram — глушим терминальный шов рендера,
    оставляя поведение хендлеров нетронутым. Копим отрисованный текст."""
    rendered = []

    async def fake_safe_edit(message, text, **kwargs):
        rendered.append(text)
        return True

    async def fake_edit_card(message, content, keyboard):
        rendered.append(content.to_plain())
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_safe_edit)
    monkeypatch.setattr(cb, "safe_edit_text", fake_safe_edit)
    monkeypatch.setattr(cb, "edit_card", fake_edit_card)
    return rendered


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    for user_id in range(40, 60):
        mapping_sessions.discard(user_id)


# ---------------------------------------------------------------------------
# РАСКЛАДКА: несколько имён по неназванным спикерам в порядке появления
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_names_fill_three_unnamed_in_order():
    """«Аня, Тимур, Лена» на три неназванных → три строки по порядку появления."""
    session = _make_session(speaker_mapping={}, user_id=42)
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)
    router = _mapping_router()

    message = _FakeMessage(42, text="Аня, Тимур, Лена")
    winner = await _deliver_message([router], message, _make_fsm(42))

    assert winner is router  # текст в главном виде теперь ловит роутер карточки
    assert session.speaker_mapping == {
        "SPEAKER_1": "Аня",
        "SPEAKER_2": "Тимур",
        "SPEAKER_3": "Лена",
    }
    assert session.editing_speaker is None  # главный вид, под-вид не открывали


@pytest.mark.asyncio
async def test_single_name_goes_to_first_unnamed_and_keeps_full_name():
    """Одно имя без разделителей → первому неназванному; «Анна Петровна» — одно имя."""
    session = _make_session(speaker_mapping={}, user_id=43)
    session.confirmation_message = _FakeMessage(43)
    mapping_sessions.save(43, session)
    router = _mapping_router()

    message = _FakeMessage(43, text="Анна Петровна")
    winner = await _deliver_message([router], message, _make_fsm(43))

    assert winner is router
    assert session.speaker_mapping == {"SPEAKER_1": "Анна Петровна"}
    assert "SPEAKER_2" not in session.speaker_mapping  # остальные не тронуты


@pytest.mark.asyncio
async def test_named_speakers_not_touched_or_shifted():
    """Уже названного спикера раскладка не трогает: имена ложатся на неназванных
    по порядку, названный остаётся на месте."""
    session = _make_session(
        participants=[{"name": "Пётр Иванов"}],
        speaker_mapping={"SPEAKER_1": "Пётр Иванов"},
        user_id=44,
    )
    session.confirmation_message = _FakeMessage(44)
    mapping_sessions.save(44, session)
    router = _mapping_router()

    message = _FakeMessage(44, text="Аня, Тимур")
    winner = await _deliver_message([router], message, _make_fsm(44))

    assert winner is router
    assert session.speaker_mapping == {
        "SPEAKER_1": "Пётр Иванов",  # названный не тронут
        "SPEAKER_2": "Аня",
        "SPEAKER_3": "Тимур",
    }


@pytest.mark.asyncio
async def test_more_names_than_unnamed_applies_nothing_and_reasks_with_numbers():
    """Имён больше, чем неназванных → ничего не применяем, переспрос с числами."""
    session = _make_session(
        speaker_mapping={}, user_id=45, speakers=("SPEAKER_1", "SPEAKER_2")
    )
    session.confirmation_message = _FakeMessage(45)
    mapping_sessions.save(45, session)
    router = _mapping_router()

    message = _FakeMessage(45, text="Аня, Тимур, Лена, Дима")
    winner = await _deliver_message([router], message, _make_fsm(45))

    assert winner is router  # текст пойман, но ничего не применено
    assert session.speaker_mapping == {}
    assert session.request.participants_list in (None, [])
    reply = message.replies[-1]
    assert "2" in reply and "4" in reply  # переспрос несёт числа (неназванных/имён)


@pytest.mark.asyncio
async def test_one_bad_name_blocks_the_whole_message():
    """Всё или ничего: одно имя вне планки 2–50 → не применяется ни одно."""
    session = _make_session(speaker_mapping={}, user_id=46)
    session.confirmation_message = _FakeMessage(46)
    mapping_sessions.save(46, session)
    router = _mapping_router()

    message = _FakeMessage(46, text="Аня, " + "Я" * 51)  # второе имя длиннее 50
    winner = await _deliver_message([router], message, _make_fsm(46))

    assert winner is router
    assert session.speaker_mapping == {}  # даже валидная «Аня» не применена
    assert session.request.participants_list in (None, [])
    assert "2–50" in message.replies[-1]


@pytest.mark.asyncio
async def test_text_when_all_named_changes_nothing_and_points_to_confirm():
    """Все спикеры уже названы, а пришёл текст → раскладывать некуда: ничего не
    меняем и подсказываем нажать «Подтвердить»."""
    session = _make_session(
        participants=[{"name": "Пётр Иванов"}, {"name": "Аня Ли"}],
        speaker_mapping={"SPEAKER_1": "Пётр Иванов", "SPEAKER_2": "Аня Ли"},
        user_id=49,
        speakers=("SPEAKER_1", "SPEAKER_2"),
    )
    session.confirmation_message = _FakeMessage(49)
    mapping_sessions.save(49, session)
    router = _mapping_router()

    message = _FakeMessage(49, text="Мария Сидорова")
    winner = await _deliver_message([router], message, _make_fsm(49))

    assert winner is router
    assert session.speaker_mapping == {"SPEAKER_1": "Пётр Иванов", "SPEAKER_2": "Аня Ли"}
    assert "Подтвердить" in message.replies[-1]


class _ContinueSpy:
    """Наблюдатель за продолжением обработки: раскладка НЕ должна его звать."""

    def __init__(self):
        self.called = False

    async def continue_processing_after_mapping_confirmation(self, **kwargs):
        self.called = True


@pytest.mark.asyncio
async def test_layout_does_not_continue_processing():
    """После раскладки обработка не продолжается сама — только по «Подтвердить»."""
    session = _make_session(speaker_mapping={}, user_id=47)
    session.confirmation_message = _FakeMessage(47)
    mapping_sessions.save(47, session)
    spy = _ContinueSpy()
    router = _mapping_router(spy)

    message = _FakeMessage(47, text="Аня, Тимур, Лена")
    await _deliver_message([router], message, _make_fsm(47))

    assert spy.called is False  # необратимый шаг — только кнопка
    assert mapping_sessions.peek(47) is not None  # сессия жива, карточка открыта


# ---------------------------------------------------------------------------
# Пропуск мимо карточки: ссылка при открытом главном виде → обычная обработка
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_in_main_view_falls_through_card_stays_open():
    """Ссылка при открытой карточке (главный вид) → обычная обработка записи,
    карточка остаётся открытой; раскладка не применяется."""
    session = _make_session(speaker_mapping={}, user_id=48)
    session.confirmation_message = _FakeMessage(48)
    mapping_sessions.save(48, session)
    router = _mapping_router()

    routers, caught = _wall_routers(router)
    message = _FakeMessage(48, text="https://disk.yandex.ru/d/abc встреча")
    winner = await _deliver_message(routers, message, _make_fsm(48))

    assert caught["winner"] == "general"  # ссылка — в обычный поток
    assert winner is routers[-1]
    assert session.speaker_mapping == {}  # раскладка не тронула сопоставление
    assert mapping_sessions.peek(48) is not None  # карточка осталась открытой


# ---------------------------------------------------------------------------
# ТЕКСТЫ: строка-приглашение видна, пока есть неназванные (только главный вид)
# ---------------------------------------------------------------------------


def test_main_view_card_carries_name_prompt_above_nudge():
    """Главный вид с неназванными → две строки подсказки: приглашение СВЕРХУ,
    затем «Участник N»."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card({}, _diarization("SPEAKER_1", "SPEAKER_2"), participants=[])

    assert card.hint is not None
    assert "Отправьте имена одним сообщением" in card.hint
    assert "Участник" in card.hint
    assert card.hint.index("Отправьте имена") < card.hint.index("Участник")


def test_both_hint_lines_disappear_when_all_named():
    """Названы все → обе строки подсказки исчезают (как исчезала одна)."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {"SPEAKER_1": "Пётр Иванов", "SPEAKER_2": "Аня Ли"},
        _diarization("SPEAKER_1", "SPEAKER_2"),
        participants=[{"name": "Пётр Иванов"}, {"name": "Аня Ли"}],
    )

    assert card.hint is None


def test_subview_card_keeps_nudge_without_name_prompt():
    """Под-вид с неназванными → nudge про «Участник N» есть, приглашения главного
    вида нет («через запятую» противоречило бы одному имени под-вида)."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {}, _diarization("SPEAKER_1", "SPEAKER_2"), participants=[],
        current_editing_speaker="SPEAKER_1",
    )

    assert card.hint is not None
    assert "Участник" in card.hint
    assert "Отправьте имена одним сообщением" not in card.hint
