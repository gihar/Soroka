"""Характеризация ловли имени спикера в Карточке сопоставления (issue #98).

Тесты описывают наблюдаемое поведение ручного ввода имени через публичный
интерфейс — регистрируемые хендлеры карточки и роутер сопоставления, — не
завязываясь на механизм признака ожидания (FSM-состояние или поле сессии).
Вход в ожидание идёт РОВНО через ``sm_custom``, доставка имени — через фильтры
зарегистрированного message-хендлера. Так тесты остаются зелёными и до, и после
переезда признака ожидания из FSM в сессию сопоставления.
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
from src.handlers.callbacks.speaker_mapping_callbacks import (  # noqa: E402
    request_custom_speaker_name,
    speaker_mapping_cancel_callback,
)
from src.models.diarization import Diarization, Segment  # noqa: E402
from src.models.processing import ProcessingRequest, TranscriptionResult  # noqa: E402
from src.performance.metrics import ProcessingMetrics  # noqa: E402
from src.services.mapping_session import MappingSession, mapping_sessions  # noqa: E402
from src.ux.speaker_mapping_callback_data import SmCancel, SmCustom  # noqa: E402

_SESSION_GONE_TEXT = cb._SESSION_GONE_TEXT
_BOT_ID = 123456


def _diarization_two_speakers() -> Diarization:
    return Diarization(segments=[
        Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="реплика первого"),
        Segment(start=6.0, end=9.0, speaker="SPEAKER_2", text="реплика второго"),
    ])


def _make_session(participants=None, speaker_mapping=None, user_id=42):
    request = ProcessingRequest(
        user_id=user_id, file_name="встреча.mp3", template_id=2,
        llm_provider="openai", participants_list=participants,
    )
    transcription = TranscriptionResult(
        transcription="текст",
        diarization=_diarization_two_speakers(),
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
    """Настоящий FSMContext на памяти: get_state отдаёт сырую строку состояния,
    поэтому StateFilter текущей регистрации работает без подмен."""
    key = StorageKey(bot_id=_BOT_ID, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=MemoryStorage(), key=key)


class _FakeCallback:
    def __init__(self, data, user_id, message):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.bot = SimpleNamespace()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


class _FakeMessage:
    def __init__(self, user_id, text=""):
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.bot = SimpleNamespace()
        self.replies = []

    async def answer(self, text=None, **kwargs):
        self.replies.append(text)


async def _deliver_message(routers, message, state):
    """Мини-диспетчер: гоняет сообщение по роутерам В ПОРЯДКЕ включения, отдаёт
    первому подошедшему message-хендлеру (как aiogram) и возвращает роутер-победитель.

    Контекст фильтров повторяет то, что кладёт FSM-middleware: ``raw_state`` для
    StateFilter и ``state`` для тела хендлера. Кастомный фильтр сессии читает
    ``message`` — тоже получает его.
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


def _mapping_router(processing_service=None):
    processing_service = processing_service or SimpleNamespace(
        continue_processing_after_mapping_confirmation=_noop
    )
    return cb.setup_speaker_mapping_callbacks(
        SimpleNamespace(), SimpleNamespace(), processing_service
    )


async def _noop(**kwargs):
    return None


async def _enter_naming(user_id, speaker_id="SPEAKER_1"):
    """Войти в ожидание имени РОВНО как пользователь: тап «Ввести имя вручную»."""
    state = _make_fsm(user_id)
    message = _FakeMessage(user_id)
    callback = _FakeCallback(
        f"sm_custom:{speaker_id}:{user_id}", user_id=user_id, message=message
    )
    await request_custom_speaker_name(callback, SmCustom.unpack(callback.data), state)
    return state


@pytest.fixture(autouse=True)
def _patch_card_render(monkeypatch):
    """Отправитель карточек ходит в Telegram — глушим терминальный шов рендера,
    оставляя поведение хендлеров нетронутым. Копим отрисованный текст."""
    rendered = []

    async def fake_safe_edit(message, text, **kwargs):
        rendered.append(text)
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_safe_edit)
    monkeypatch.setattr(cb, "safe_edit_text", fake_safe_edit)
    return rendered


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    for user_id in range(40, 60):
        mapping_sessions.discard(user_id)


# ---------------------------------------------------------------------------
# Валидное имя — применяется к спикеру, добавляет участника, перерисовывает карту
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_name_applies_to_speaker_and_adds_participant(_patch_card_render):
    session = _make_session(participants=None, speaker_mapping={}, user_id=42)
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)

    state = await _enter_naming(42)
    message = _FakeMessage(42, text="Мария Сидорова")

    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None  # имя поймал роутер сопоставления
    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"
    assert any(
        p["name"] == "Мария Сидорова" for p in session.request.participants_list
    )
    assert any("Мария" in text for text in _patch_card_render)


@pytest.mark.asyncio
async def test_valid_name_dedups_with_existing_participant():
    """Совпадение с уже имеющимся участником переиспользует его без дубля."""
    original = [{"name": "Тимченко Алексей Александрович", "role": "разработчик"}]
    session = _make_session(participants=original, speaker_mapping={}, user_id=43)
    session.confirmation_message = _FakeMessage(43)
    mapping_sessions.save(43, session)

    state = await _enter_naming(43)
    message = _FakeMessage(43, text="Алексей Тимченко")

    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None
    assert session.speaker_mapping["SPEAKER_1"] == "Алексей Тимченко"
    assert len(session.request.participants_list) == 1  # без дубля


# ---------------------------------------------------------------------------
# Невалидное имя — мягкий отказ, ожидание держится
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_name_reasks_and_keeps_waiting():
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=44
    )
    session.confirmation_message = _FakeMessage(44)
    mapping_sessions.save(44, session)

    state = await _enter_naming(44)
    message = _FakeMessage(44, text="И")

    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]
    hint = message.replies[-1]
    assert "короче" in hint
    assert "текстом" not in hint  # это про длину, не про тип контента

    # Ожидание держится: следующее валидное имя всё ещё ловится и применяется.
    followup = _FakeMessage(44, text="Мария Сидорова")
    winner2 = await _deliver_message([_mapping_router()], followup, state)
    assert winner2 is not None
    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"


@pytest.mark.asyncio
async def test_slash_name_reasks_within_naming_subview():
    """Имя с «/» (не зарегистрированная команда) в под-виде ввода — мягкий отказ
    тем же хендлером имени; сопоставление и список участников не тронуты."""
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=45
    )
    session.confirmation_message = _FakeMessage(45)
    mapping_sessions.save(45, session)

    state = await _enter_naming(45)
    message = _FakeMessage(45, text="/skip")

    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]
    assert "/" in message.replies[-1]  # переспрос называет запрет на «/»


@pytest.mark.asyncio
async def test_non_text_message_soft_refuses_and_keeps_waiting():
    """Не-текст (голосовое/документ/фото): мягкий отказ «пришлите текстом»,
    запись НЕ теряется мимо и НЕ трактуется как короткое имя."""
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=46
    )
    session.confirmation_message = _FakeMessage(46)
    mapping_sessions.save(46, session)

    state = await _enter_naming(46)
    message = _FakeMessage(46, text=None)  # не-текстовый контент

    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None  # хендлер имени поймал не-текст, не пропустил мимо
    hint = message.replies[-1]
    assert "текстом" in hint
    assert "Отмена" in hint
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]


# ---------------------------------------------------------------------------
# Отмена из под-вида — ожидание снимается, следующее сообщение не ловится
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_capturing_the_next_message():
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=47
    )
    session.confirmation_message = _FakeMessage(47)
    mapping_sessions.save(47, session)

    state = await _enter_naming(47)

    cancel_cb = _FakeCallback("sm_cancel:47", user_id=47, message=_FakeMessage(47))
    await speaker_mapping_cancel_callback(
        cancel_cb, SmCancel.unpack(cancel_cb.data), state
    )

    message = _FakeMessage(47, text="Мария Сидорова")
    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is None  # после отмены имя больше не ловится хендлером карточки
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]


# ---------------------------------------------------------------------------
# Истёкшая сессия — сообщение об истёкшем состоянии
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_session_reports_gone():
    session = _make_session(participants=None, speaker_mapping={}, user_id=48)
    session.confirmation_message = _FakeMessage(48)
    mapping_sessions.save(48, session)

    state = await _enter_naming(48)
    mapping_sessions.discard(48)  # имитируем истечение TTL сессии

    message = _FakeMessage(48, text="Мария Сидорова")
    winner = await _deliver_message([_mapping_router()], message, state)

    assert winner is not None
    assert message.replies[-1] == _SESSION_GONE_TEXT


# ---------------------------------------------------------------------------
# Несущая стена: команды и кнопки reply-меню в ожидании имени идут своим роутерам
# ---------------------------------------------------------------------------


def _wall_routers(mapping_router):
    """Роутеры в порядке bot.py вокруг роутера сопоставления: команды и
    quick-actions ДО него, общий текстовый — ПОСЛЕ."""
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

    @general_router.message(StateFilter(None), F.content_type == "text")
    async def _general(message):
        caught["winner"] = "general"

    routers = [command_router, quick_actions_router, mapping_router, general_router]
    return routers, caught


@pytest.mark.asyncio
async def test_command_and_menu_bypass_name_capture_during_waiting():
    session = _make_session(participants=None, speaker_mapping={}, user_id=49)
    session.confirmation_message = _FakeMessage(49)
    mapping_sessions.save(49, session)

    state = await _enter_naming(49)
    mapping_router = _mapping_router()
    routers, caught = _wall_routers(mapping_router)

    # Зарегистрированная команда во время ожидания → роутер команд, не ловля имени.
    winner = await _deliver_message(routers, _FakeMessage(49, text="/start"), state)
    assert winner is routers[0]
    assert caught["winner"] == "command"
    assert "SPEAKER_1" not in session.speaker_mapping

    # Кнопка reply-меню во время ожидания → роутер quick-actions.
    caught["winner"] = None
    winner = await _deliver_message(
        routers, _FakeMessage(49, text="⚙️ Настройки"), state
    )
    assert winner is routers[1]
    assert caught["winner"] == "menu"
    assert "SPEAKER_1" not in session.speaker_mapping

    # Обычный текст-имя во время ожидания → роутер сопоставления, имя применяется.
    winner = await _deliver_message(
        routers, _FakeMessage(49, text="Мария Сидорова"), state
    )
    assert winner is mapping_router
    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"
