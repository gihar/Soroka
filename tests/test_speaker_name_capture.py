"""Характеризация ловли имени спикера в Карточке сопоставления (issue #98 → #99).

Тесты описывают наблюдаемое поведение через публичный интерфейс — роутер
сопоставления в окружении соседних роутеров (как в ``bot.py``), — не завязываясь
на механизм признака ожидания. В #98 признак жил в отдельном реестре и вход был
через ``sm_custom``; в #99 признак — поле сессии ``editing_speaker``, а вход в
под-вид — тап по спикеру (``sm_change``). Здесь зафиксированы РОУТИНГ (что ловится
роутером сопоставления, а что уходит мимо) и два ОСОЗНАННЫХ изменения поведения
#99, отмеченные комментариями у изменённых ожиданий:

- не-текст (файл/голос/фото) больше НЕ получает мягкий отказ «пришлите текстом»,
  а проваливается в обычный поток загрузки записи (ловец привязан только к тексту);
- истёкшая по TTL сессия при открытом под-виде больше НЕ отвечает «Состояние
  истекло», а проваливается в общий обработчик (под-вида нет без живой сессии).
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
from src.ux.speaker_mapping_callback_data import SmCancel, SmChange  # noqa: E402

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


def _registered_callback(router, cbdata_cls):
    for handler in router.callback_query.handlers:
        for flt in handler.filters:
            if getattr(flt.callback, "callback_data", None) is cbdata_cls:
                return handler.callback
    raise AssertionError(f"нет хендлера для {cbdata_cls.__name__}")


async def _open_subview(router, user_id, speaker_id="SPEAKER_1"):
    """Войти в под-вид спикера РОВНО как пользователь: тап по кнопке спикера."""
    handler = _registered_callback(router, SmChange)
    callback = _FakeCallback(
        f"sm_change:{speaker_id}:{user_id}", user_id=user_id,
        message=_FakeMessage(user_id),
    )
    await handler(callback, SmChange(speaker_id=speaker_id, user_id=user_id),
                  _make_fsm(user_id))


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
# Позитивный якорь: имя в открытом под-виде ловит роутер сопоставления
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_name_applies_to_speaker(_patch_card_render):
    session = _make_session(participants=None, speaker_mapping={}, user_id=42)
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)
    router = _mapping_router()
    await _open_subview(router, 42, "SPEAKER_1")

    message = _FakeMessage(42, text="Мария Сидорова")
    winner = await _deliver_message([router], message, _make_fsm(42))

    assert winner is router  # имя поймал роутер сопоставления
    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"
    assert any("Мария" in text for text in _patch_card_render)


# ---------------------------------------------------------------------------
# Осознанное изменение #99: не-текст больше не получает мягкий отказ, а уходит мимо
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_text_message_falls_through_no_soft_refusal():
    """В #98 не-текст в под-виде получал мягкий отказ «пришлите текстом» и
    удерживал ожидание. В #99 ловец привязан ТОЛЬКО к тексту: не-текст уходит
    мимо в обычный поток загрузки записи — отказа больше нет, под-вид цел."""
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=46
    )
    session.confirmation_message = _FakeMessage(46)
    mapping_sessions.save(46, session)
    router = _mapping_router()
    await _open_subview(router, 46, "SPEAKER_1")

    message = _FakeMessage(46, text=None)  # не-текстовый контент
    winner = await _deliver_message([router], message, _make_fsm(46))

    assert winner is None  # мимо роутера сопоставления
    assert message.replies == []  # мягкого отказа больше нет
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.editing_speaker == "SPEAKER_1"  # под-вид продолжает ждать имя


# ---------------------------------------------------------------------------
# Осознанное изменение #99: истёкшая сессия больше не отвечает «Состояние истекло»
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_session_falls_through_no_gone_text():
    """В #98 истёкшая по TTL сессия при открытом под-виде получала
    _SESSION_GONE_TEXT из хендлера имени (признак жил отдельно от сессии). В #99
    признак — поле сессии: нет живой сессии → нет под-вида → текст просто
    проваливается мимо в общий обработчик. Прежнего ответа «истекло» тут нет."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=48)
    session.confirmation_message = _FakeMessage(48)
    mapping_sessions.save(48, session)
    router = _mapping_router()
    await _open_subview(router, 48, "SPEAKER_1")
    mapping_sessions.discard(48)  # имитируем истечение TTL сессии

    message = _FakeMessage(48, text="Мария Сидорова")
    winner = await _deliver_message([router], message, _make_fsm(48))

    assert winner is None  # мимо роутера сопоставления
    assert message.replies == []  # «Состояние истекло» больше не шлём


# ---------------------------------------------------------------------------
# Закрытие под-вида «◀️ Назад» снимает ловлю следующего сообщения
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_capturing_the_next_message():
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=47
    )
    session.confirmation_message = _FakeMessage(47)
    mapping_sessions.save(47, session)
    router = _mapping_router()
    await _open_subview(router, 47, "SPEAKER_1")

    cancel = _registered_callback(router, SmCancel)
    cancel_cb = _FakeCallback("sm_cancel:47", user_id=47, message=_FakeMessage(47))
    await cancel(cancel_cb, SmCancel.unpack(cancel_cb.data), _make_fsm(47))

    message = _FakeMessage(47, text="Мария Сидорова")
    winner = await _deliver_message([router], message, _make_fsm(47))

    assert winner is None  # после «Назад» имя больше не ловится роутером карточки
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]


# ---------------------------------------------------------------------------
# Несущая стена: команды и кнопки reply-меню в под-виде идут своим роутерам
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
async def test_command_and_menu_bypass_name_capture_in_subview():
    session = _make_session(participants=None, speaker_mapping={}, user_id=49)
    session.confirmation_message = _FakeMessage(49)
    mapping_sessions.save(49, session)
    mapping_router = _mapping_router()
    await _open_subview(mapping_router, 49, "SPEAKER_1")
    routers, caught = _wall_routers(mapping_router)

    # Зарегистрированная команда в под-виде → роутер команд, не ловля имени.
    winner = await _deliver_message(routers, _FakeMessage(49, text="/start"), _make_fsm(49))
    assert winner is routers[0]
    assert caught["winner"] == "command"
    assert "SPEAKER_1" not in session.speaker_mapping

    # Кнопка reply-меню в под-виде → роутер quick-actions.
    caught["winner"] = None
    winner = await _deliver_message(
        routers, _FakeMessage(49, text="⚙️ Настройки"), _make_fsm(49)
    )
    assert winner is routers[1]
    assert caught["winner"] == "menu"
    assert "SPEAKER_1" not in session.speaker_mapping

    # Обычный текст-имя в под-виде → роутер сопоставления, имя применяется.
    winner = await _deliver_message(
        routers, _FakeMessage(49, text="Мария Сидорова"), _make_fsm(49)
    )
    assert winner is mapping_router
    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"
