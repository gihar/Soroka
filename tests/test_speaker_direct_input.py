"""Прямой ввод имени в под-виде спикера Карточки сопоставления (issue #99).

Тап на спикера (``sm_change``) сразу открывает под-вид, готовый принять имя
сообщением — без промежуточной кнопки. Тесты описывают наблюдаемое поведение
через публичный интерфейс: зарегистрированные хендлеры/фильтры роутера
сопоставления и мини-диспетчер, повторяющий порядок роутеров из ``bot.py``.

Признак «какой спикер ждёт имя» — поле сессии ``editing_speaker`` (реестр
ожидания из #98 удалён). Фильтр ловца: живая сессия И ``editing_speaker`` задан
И content — текст без ссылки. Иначе апдейт проваливается дальше по цепочке
роутеров (в обычную обработку записи).
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram import Router
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
from src.models.processing import (  # noqa: E402
    ProcessingRequest,
    TranscriptionResult,
)
from src.performance.metrics import ProcessingMetrics  # noqa: E402
from src.services.mapping_session import (  # noqa: E402
    MappingSession,
    mapping_sessions,
)
from src.ux.speaker_mapping_callback_data import SmCancel, SmChange, SmSelect  # noqa: E402

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


def _registered_callback(router, cbdata_cls):
    """Найти зарегистрированный callback-хендлер по классу CallbackData-фильтра."""
    for handler in router.callback_query.handlers:
        for flt in handler.filters:
            if getattr(flt.callback, "callback_data", None) is cbdata_cls:
                return handler.callback
    raise AssertionError(f"нет хендлера для {cbdata_cls.__name__}")


async def _open_subview(router, user_id, speaker_id="SPEAKER_1"):
    """Открыть под-вид спикера ровно как пользователь: тап по кнопке спикера."""
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
# Тап на спикера → под-вид ждёт имя → текст становится именем этого спикера
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tap_then_text_names_the_tapped_speaker(_patch_card_render):
    session = _make_session(participants=None, speaker_mapping={}, user_id=42)
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)
    router = _mapping_router()

    await _open_subview(router, 42, "SPEAKER_2")
    message = _FakeMessage(42, text="Мария Сидорова")
    state = _make_fsm(42)

    winner = await _deliver_message([router], message, state)

    assert winner is router  # имя поймал роутер сопоставления
    assert session.speaker_mapping["SPEAKER_2"] == "Мария Сидорова"
    assert any(
        p["name"] == "Мария Сидорова" for p in session.request.participants_list
    )
    assert session.editing_speaker is None  # применили — вышли из под-вида


# ---------------------------------------------------------------------------
# Заголовок под-вида называет спикера и приглашает печатать (обе вариации)
# ---------------------------------------------------------------------------


def test_subview_header_names_speaker_without_participants():
    """Без списка участников заголовок под-вида зовёт отправить имя сообщением."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {}, _diarization_two_speakers(), participants=[],
        current_editing_speaker="SPEAKER_2",
    )

    assert "SPEAKER_2" in card.header
    assert "отправьте сообщением" in card.header
    assert "выберите ниже" not in card.header


def test_subview_header_names_speaker_with_participants():
    """Со списком участников заголовок ещё и указывает на выбор ниже."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {}, _diarization_two_speakers(), participants=[{"name": "Иван Петров"}],
        current_editing_speaker="SPEAKER_2",
    )

    assert "SPEAKER_2" in card.header
    assert "отправьте сообщением" in card.header
    assert "выберите ниже" in card.header


def test_main_view_header_ignores_editing_speaker_when_none():
    """Главный вид (editing_speaker=None) — прежний заголовок, без приглашения."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {}, _diarization_two_speakers(), participants=[{"name": "Иван Петров"}],
    )

    assert "Проверьте сопоставление" in card.header
    assert "отправьте сообщением" not in card.header


# ---------------------------------------------------------------------------
# Кнопки под-вида: «Ввести имя вручную» больше нет; остальные на месте
# ---------------------------------------------------------------------------


def test_subview_has_no_manual_name_button():
    """В под-виде нет кнопки «Ввести имя вручную» (sm_custom): «Оставить без
    имени», участники и «◀️ Назад» остаются."""
    from src.ux.speaker_mapping_ui import create_mapping_keyboard

    keyboard = create_mapping_keyboard(
        speaker_mapping={},
        diarization=_diarization_two_speakers(),
        participants=[{"name": "Иван Петров"}],
        user_id=42,
        current_editing_speaker="SPEAKER_1",
    )
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]

    assert not any(c.startswith("sm_custom") for c in callbacks)
    assert "sm_select:SPEAKER_1:none:42" in callbacks  # «Оставить без имени»
    assert "sm_select:SPEAKER_1:0:42" in callbacks  # кнопка участника
    assert "sm_cancel:42" in callbacks  # «◀️ Назад»


def test_sm_custom_class_is_gone():
    """Фабрика callback-данных SmCustom удалена вместе с промежуточным экраном."""
    import src.ux.speaker_mapping_callback_data as cd

    assert not hasattr(cd, "SmCustom")


# ---------------------------------------------------------------------------
# Фильтр ловца: ссылка, не-текст и истёкшая сессия проваливаются мимо
# ---------------------------------------------------------------------------


def _wall_routers(mapping_router):
    """Роутеры в порядке bot.py: команды ДО роутера сопоставления, общий
    текстовый (обрабатывает запись/ссылку) — ПОСЛЕ."""
    caught = {"winner": None}

    command_router = Router()

    def _is_command(message) -> bool:
        text = getattr(message, "text", None)
        return bool(text) and text.startswith("/")

    @command_router.message(_is_command)
    async def _command(message):
        caught["winner"] = "command"

    general_router = Router()

    @general_router.message(StateFilter(None))
    async def _general(message):
        caught["winner"] = "general"

    routers = [command_router, mapping_router, general_router]
    return routers, caught


@pytest.mark.asyncio
async def test_link_in_subview_falls_through_to_general_flow():
    """Текст со ссылкой в открытом под-виде уходит в обычную обработку записи;
    имя не применяется, под-вид остаётся открытым (editing_speaker цел)."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=50)
    session.confirmation_message = _FakeMessage(50)
    mapping_sessions.save(50, session)
    router = _mapping_router()
    await _open_subview(router, 50, "SPEAKER_1")

    routers, caught = _wall_routers(router)
    message = _FakeMessage(50, text="https://disk.yandex.ru/d/abc встреча")
    winner = await _deliver_message(routers, message, _make_fsm(50))

    assert caught["winner"] == "general"  # ссылка — в обычный поток
    assert winner is routers[-1]
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.editing_speaker == "SPEAKER_1"  # под-вид продолжает ждать имя


@pytest.mark.asyncio
async def test_non_text_in_subview_falls_through():
    """Не-текст (файл/голос/фото) в под-виде уходит мимо ловца — прежний мягкий
    отказ «отправьте текстом» исчез (ADR-0006)."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=51)
    session.confirmation_message = _FakeMessage(51)
    mapping_sessions.save(51, session)
    router = _mapping_router()
    await _open_subview(router, 51, "SPEAKER_1")

    routers, caught = _wall_routers(router)
    message = _FakeMessage(51, text=None)  # не-текстовый контент
    winner = await _deliver_message(routers, message, _make_fsm(51))

    assert winner is routers[-1]  # не пойман роутером сопоставления
    assert message.replies == []  # мягкого отказа больше нет
    assert session.editing_speaker == "SPEAKER_1"


@pytest.mark.asyncio
async def test_expired_session_falls_through_no_gone_text():
    """Сессия истекла по TTL, пока под-вид был открыт → текст проваливается в
    общий обработчик; прежнего ответа «Состояние истекло» в этом крае больше нет
    (осознанное изменение #99: под-вида нет без живой сессии)."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=52)
    session.confirmation_message = _FakeMessage(52)
    mapping_sessions.save(52, session)
    router = _mapping_router()
    await _open_subview(router, 52, "SPEAKER_1")
    mapping_sessions.discard(52)  # имитируем истечение TTL

    routers, caught = _wall_routers(router)
    message = _FakeMessage(52, text="Мария Сидорова")
    winner = await _deliver_message(routers, message, _make_fsm(52))

    assert winner is routers[-1]
    assert caught["winner"] == "general"
    assert _SESSION_GONE_NOT_SENT(message)


def _SESSION_GONE_NOT_SENT(message) -> bool:
    return all("истекл" not in (r or "") for r in message.replies)


@pytest.mark.asyncio
async def test_main_view_text_not_captured():
    """В главном виде (editing_speaker=None) текст ловцом не съедается — уходит в
    обычный поток (прямой ввод из главного вида — уже #100, не #99)."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=53)
    session.confirmation_message = _FakeMessage(53)
    mapping_sessions.save(53, session)  # сессия жива, но под-вид не открыт
    router = _mapping_router()

    routers, caught = _wall_routers(router)
    message = _FakeMessage(53, text="Мария Сидорова")
    winner = await _deliver_message(routers, message, _make_fsm(53))

    assert winner is routers[-1]
    assert "SPEAKER_1" not in session.speaker_mapping


# ---------------------------------------------------------------------------
# Отказы в под-виде: несколько имён и имя вне планки — ничего не применяем
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_names_refused_with_hint():
    """Несколько имён (через запятую) → отказ с подсказкой про общий вид; ничего
    не применяется, под-вид остаётся открытым."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=54)
    session.confirmation_message = _FakeMessage(54)
    mapping_sessions.save(54, session)
    router = _mapping_router()
    await _open_subview(router, 54, "SPEAKER_1")

    message = _FakeMessage(54, text="Мария Сидорова, Иван Петров")
    winner = await _deliver_message([router], message, _make_fsm(54))

    assert winner is router
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list in (None, [])
    hint = message.replies[-1]
    assert "одно имя" in hint
    assert "Назад" in hint
    assert session.editing_speaker == "SPEAKER_1"  # ждём дальше


@pytest.mark.asyncio
async def test_name_over_limit_refused_without_partial_apply():
    """Имя длиннее 50 символов → отказ, ничего не применяем (всё или ничего)."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=55)
    session.confirmation_message = _FakeMessage(55)
    mapping_sessions.save(55, session)
    router = _mapping_router()
    await _open_subview(router, 55, "SPEAKER_1")

    message = _FakeMessage(55, text="Я" * 51)
    winner = await _deliver_message([router], message, _make_fsm(55))

    assert winner is router
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list in (None, [])
    assert "2–50" in message.replies[-1]


@pytest.mark.asyncio
async def test_slash_name_refused_in_subview():
    """Имя с «/» (не команда — команды перехватит роутер команд раньше) → отказ,
    ничего не применяем."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=56)
    session.confirmation_message = _FakeMessage(56)
    mapping_sessions.save(56, session)
    router = _mapping_router()
    await _open_subview(router, 56, "SPEAKER_1")

    message = _FakeMessage(56, text="/notacommand")
    winner = await _deliver_message([router], message, _make_fsm(56))

    assert winner is router
    assert "SPEAKER_1" not in session.speaker_mapping


# ---------------------------------------------------------------------------
# Закрытие под-вида снимает editing_speaker (следующее сообщение не ловится)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_button_clears_editing_speaker():
    """«◀️ Назад» (sm_cancel) снимает editing_speaker: следующий текст уходит
    мимо ловца в обычный поток."""
    session = _make_session(participants=None, speaker_mapping={}, user_id=57)
    session.confirmation_message = _FakeMessage(57)
    mapping_sessions.save(57, session)
    router = _mapping_router()
    await _open_subview(router, 57, "SPEAKER_1")

    cancel = _registered_callback(router, SmCancel)
    await cancel(_FakeCallback("sm_cancel:57", 57, _FakeMessage(57)),
                 SmCancel(user_id=57), _make_fsm(57))

    assert session.editing_speaker is None
    routers, caught = _wall_routers(router)
    winner = await _deliver_message(
        routers, _FakeMessage(57, text="Мария Сидорова"), _make_fsm(57)
    )
    assert winner is routers[-1]  # больше не ловим
    assert "SPEAKER_1" not in session.speaker_mapping


@pytest.mark.asyncio
async def test_selecting_participant_clears_editing_speaker():
    """Выбор участника (sm_select) закрывает под-вид: editing_speaker снят."""
    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}, user_id=58
    )
    session.confirmation_message = _FakeMessage(58)
    mapping_sessions.save(58, session)
    router = _mapping_router()
    await _open_subview(router, 58, "SPEAKER_1")

    select = _registered_callback(router, SmSelect)
    await select(
        _FakeCallback("sm_select:SPEAKER_1:0:58", 58, _FakeMessage(58)),
        SmSelect(speaker_id="SPEAKER_1", participant_idx="0", user_id=58),
        _make_fsm(58),
    )

    assert session.speaker_mapping["SPEAKER_1"] == "Иван Петров"
    assert session.editing_speaker is None
