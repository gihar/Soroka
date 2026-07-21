"""Ручное именование спикеров: универсальная карточка сопоставления.

Спикера можно назвать человеком, которого не было в переданном списке
участников — имя вводится прямо в карточке и становится полноценным
участником сессии (ADR-0002). Тесты описывают наблюдаемое поведение
через публичный интерфейс: хелпер участников, клавиатуру карточки,
callback ввода имени, message-хендлер и гейт показа карточки.
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.models.processing import ProcessingRequest, TranscriptionResult  # noqa: E402
from src.performance.metrics import ProcessingMetrics  # noqa: E402
from src.services.mapping_session import MappingSession, mapping_sessions  # noqa: E402
from src.services.participants_service import participants_service  # noqa: E402
from src.ux.speaker_mapping_ui import create_mapping_keyboard  # noqa: E402


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


class _FakeState:
    """Минимальный FSMContext для тестов: хранит состояние и данные."""

    def __init__(self):
        self._state = None
        self._data = {}

    async def set_state(self, state):
        self._state = state

    async def get_state(self):
        return self._state

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self._state = None
        self._data = {}


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
        self.replies = []

    async def answer(self, text=None, **kwargs):
        self.replies.append(text)


# ---------------------------------------------------------------------------
# A. Хелпер add_manual_participant — ручное имя как полноценный участник
# ---------------------------------------------------------------------------


def test_add_manual_participant_appends_new_name():
    """Валидное новое имя добавляется участником; вход не мутируется."""
    original = [{"name": "Иван Петров", "role": "менеджер"}]

    new_list, display_name = participants_service.add_manual_participant(
        original, "Мария Сидорова"
    )

    assert display_name == "Мария Сидорова"
    assert {"name": "Мария Сидорова", "role": ""} in new_list
    assert len(new_list) == 2
    # Иммутабельность: исходный список не тронут
    assert original == [{"name": "Иван Петров", "role": "менеджер"}]


def test_add_manual_participant_rejects_short_name():
    """Имя короче 2 символов после trim отклоняется как невалидное."""
    new_list, display_name = participants_service.add_manual_participant([], " И ")

    assert new_list is None
    assert display_name is None


def test_add_manual_participant_rejects_command_like_name():
    """Имя, начинающееся с «/», отклоняется — это команда, не имя."""
    new_list, display_name = participants_service.add_manual_participant(
        [], "/skip"
    )

    assert new_list is None
    assert display_name is None


def test_add_manual_participant_dedups_existing_participant():
    """Совпадение с уже имеющимся участником переиспользуется без дубля."""
    original = [{"name": "Тимченко Алексей Александрович", "role": "разработчик"}]

    new_list, display_name = participants_service.add_manual_participant(
        original, "Алексей Тимченко"
    )

    # Переиспользуем существующего участника: его короткое имя и тот же список
    assert display_name == "Алексей Тимченко"
    assert len(new_list) == 1
    assert new_list == original


def test_add_manual_participant_stores_raw_full_name_displays_short():
    """Полное ФИО хранится сырым; отображается «Имя Фамилия» без отчества.

    convert_full_name_to_short прогоняют format_participants_for_llm и UI сами,
    поэтому в списке участника логично хранить сырое ФИО.
    """
    new_list, display_name = participants_service.add_manual_participant(
        [], "Иванова Мария Петровна"
    )

    assert display_name == "Мария Иванова"
    assert new_list[-1]["name"] == "Иванова Мария Петровна"
    assert new_list[-1]["role"] == ""


# ---------------------------------------------------------------------------
# B. Клавиатура карточки — кнопка «Ввести имя вручную» в под-виде выбора
# ---------------------------------------------------------------------------


def test_subview_offers_manual_name_button_after_leave_unnamed():
    """В под-виде выбора участника есть кнопка ручного ввода имени спикера,
    сразу после «Оставить без имени», с callback sm_custom."""
    keyboard = create_mapping_keyboard(
        speaker_mapping={},
        diarization=_diarization_two_speakers(),
        participants=[{"name": "Иван Петров"}],
        user_id=42,
        current_editing_speaker="SPEAKER_1",
    )
    rows = keyboard.inline_keyboard

    leave_button = rows[0][0]
    manual_button = rows[1][0]

    assert leave_button.callback_data == "sm_select:SPEAKER_1:none:42"
    assert "вручную" in manual_button.text
    assert manual_button.callback_data == "sm_custom:SPEAKER_1:42"


# ---------------------------------------------------------------------------
# C. Callback sm_custom — переход в ожидание имени спикера
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    mapping_sessions.discard(42)


@pytest.mark.asyncio
async def test_sm_custom_enters_name_waiting_state(monkeypatch):
    """sm_custom переводит в FSM-ожидание имени с данными спикера и рисует
    подсказку «отправьте имя» с кнопкой отмены."""
    import src.utils.telegram_safe as ts
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        request_custom_speaker_name,
    )
    from src.handlers.participants_states import SpeakerNameInput
    from src.ux.speaker_mapping_callback_data import SmCustom

    edited = []

    async def fake_edit(message, text, **kwargs):
        edited.append((text, kwargs.get("reply_markup")))
        return True

    # Под-вид ожидания имени доставляется отправителем карточек (ADR-0005),
    # поэтому шов — telegram_safe.safe_edit_text.
    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    mapping_sessions.save(42, _make_session(participants=[{"name": "Иван Петров"}]))

    state = _FakeState()
    message = _FakeMessage(user_id=42)
    callback = _FakeCallback("sm_custom:SPEAKER_1:42", user_id=42, message=message)

    await request_custom_speaker_name(callback, SmCustom.unpack(callback.data), state)

    assert await state.get_state() == SpeakerNameInput.waiting
    data = await state.get_data()
    assert data["speaker_id"] == "SPEAKER_1"
    assert data["user_id"] == 42

    prompt_text, reply_markup = edited[-1]
    assert "SPEAKER_1" in prompt_text
    cancel_button = reply_markup.inline_keyboard[0][0]
    assert cancel_button.callback_data == "sm_cancel:42"


@pytest.mark.asyncio
async def test_sm_cancel_clears_name_waiting_state(monkeypatch):
    """Отмена из под-вида ожидания имени очищает FSM-состояние (иначе следующее
    сообщение будет ошибочно перехвачено как имя)."""
    import src.utils.telegram_safe as ts
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        speaker_mapping_cancel_callback,
    )
    from src.handlers.participants_states import SpeakerNameInput
    from src.ux.speaker_mapping_callback_data import SmCancel

    async def fake_edit(message, text, **kwargs):
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    mapping_sessions.save(42, _make_session(participants=[{"name": "Иван Петров"}]))

    state = _FakeState()
    await state.set_state(SpeakerNameInput.waiting)
    await state.update_data(speaker_id="SPEAKER_1", user_id=42)

    callback = _FakeCallback("sm_cancel:42", user_id=42, message=_FakeMessage(42))

    await speaker_mapping_cancel_callback(callback, SmCancel.unpack(callback.data), state)

    assert await state.get_state() is None


# ---------------------------------------------------------------------------
# D. Message-хендлер ожидания имени — применить имя, добавить участника
# ---------------------------------------------------------------------------


async def _enter_waiting(user_id, speaker_id="SPEAKER_1"):
    from src.handlers.participants_states import SpeakerNameInput

    state = _FakeState()
    await state.set_state(SpeakerNameInput.waiting)
    await state.update_data(speaker_id=speaker_id, user_id=user_id)
    return state


@pytest.mark.asyncio
async def test_receive_name_applies_to_speaker_and_adds_participant(monkeypatch):
    """Валидное имя применяется к спикеру, становится участником сессии,
    состояние очищается, карточка перерисовывается главным видом."""
    import src.utils.telegram_safe as ts
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        receive_custom_speaker_name,
    )

    edited = []

    async def fake_edit(message, text, **kwargs):
        edited.append(text)
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    session = _make_session(participants=None, speaker_mapping={})
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)

    state = await _enter_waiting(42)
    message = _FakeMessage(42, text="Мария Сидорова")

    await receive_custom_speaker_name(message, state)

    assert session.speaker_mapping["SPEAKER_1"] == "Мария Сидорова"
    assert any(
        p["name"] == "Мария Сидорова" for p in session.request.participants_list
    )
    assert await state.get_state() is None
    assert any("Мария Сидорова" in text for text in edited)


@pytest.mark.asyncio
async def test_receive_invalid_name_stays_in_state_and_reasks():
    """Невалидное имя не меняет сессию, остаётся в состоянии, мягко переспрашивает."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        receive_custom_speaker_name,
    )
    from src.handlers.participants_states import SpeakerNameInput

    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}
    )
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)

    state = await _enter_waiting(42)
    message = _FakeMessage(42, text="/skip")

    await receive_custom_speaker_name(message, state)

    assert await state.get_state() == SpeakerNameInput.waiting
    assert "SPEAKER_1" not in session.speaker_mapping
    assert session.request.participants_list == [{"name": "Иван Петров"}]
    assert message.replies  # переспросили


@pytest.mark.asyncio
async def test_receive_non_text_keeps_state_and_hints_text():
    """Не-текст (голосовое/аудио/видео/документ/фото) в под-виде ввода имени:
    остаёмся в состоянии, запись не теряем как «короткое имя», точечно просим
    прислать имя текстом."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        receive_custom_speaker_name,
    )
    from src.handlers.participants_states import SpeakerNameInput

    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}
    )
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)

    state = await _enter_waiting(42)
    message = _FakeMessage(42, text=None)  # не-текстовый контент

    await receive_custom_speaker_name(message, state)

    assert await state.get_state() == SpeakerNameInput.waiting
    assert message.replies
    hint = message.replies[-1]
    assert "текстом" in hint
    assert "Отмена" in hint
    # запись не превратилась в участника и сопоставление не тронуто
    assert session.request.participants_list == [{"name": "Иван Петров"}]
    assert "SPEAKER_1" not in session.speaker_mapping


@pytest.mark.asyncio
async def test_receive_short_text_keeps_old_copy():
    """Слишком короткое ТЕКСТОВОЕ имя оставляет прежнюю копию (не про «текстом»)."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        receive_custom_speaker_name,
    )
    from src.handlers.participants_states import SpeakerNameInput

    session = _make_session(
        participants=[{"name": "Иван Петров"}], speaker_mapping={}
    )
    session.confirmation_message = _FakeMessage(42)
    mapping_sessions.save(42, session)

    state = await _enter_waiting(42)
    message = _FakeMessage(42, text="И")

    await receive_custom_speaker_name(message, state)

    assert await state.get_state() == SpeakerNameInput.waiting
    hint = message.replies[-1]
    assert "короче" in hint
    assert "текстом" not in hint
    assert session.request.participants_list == [{"name": "Иван Петров"}]


@pytest.mark.asyncio
async def test_receive_name_without_session_reports_expired():
    """Нет сессии → сообщение об истёкшем состоянии, состояние очищено."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        receive_custom_speaker_name,
    )

    mapping_sessions.discard(42)
    state = await _enter_waiting(42)
    message = _FakeMessage(42, text="Мария Сидорова")

    await receive_custom_speaker_name(message, state)

    assert await state.get_state() is None
    assert message.replies


# ---------------------------------------------------------------------------
# E. Гейт показа карточки — при диаризации с ≥ 1 спикером (ADR-0002)
# ---------------------------------------------------------------------------


def test_should_show_mapping_card_true_with_speakers():
    """Карточка показывается, когда диаризация нашла хотя бы одного спикера."""
    from src.services.processing.processing_service import _should_show_mapping_card

    assert _should_show_mapping_card(_diarization_two_speakers()) is True


def test_should_show_mapping_card_true_with_single_speaker():
    """Порог — ≥ 1 спикер: одноголосая запись тоже показывает карточку."""
    from src.services.processing.processing_service import _should_show_mapping_card

    diarization = Diarization(segments=[
        Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="монолог"),
    ])
    assert _should_show_mapping_card(diarization) is True


def test_should_show_mapping_card_false_without_diarization():
    """Без диаризации карточки нет."""
    from src.services.processing.processing_service import _should_show_mapping_card

    assert _should_show_mapping_card(None) is False


def test_should_show_mapping_card_false_without_speakers():
    """Диаризация без спикеров карточку не показывает."""
    from src.services.processing.processing_service import _should_show_mapping_card

    assert _should_show_mapping_card(Diarization(segments=[])) is False


# ---------------------------------------------------------------------------
# F. Безопасность и копия карточки без переданного списка участников
# ---------------------------------------------------------------------------


def test_card_header_shifts_to_naming_without_participants():
    """Без списка участников заголовок смещается на «назовите спикеров»."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card({}, _diarization_two_speakers(), participants=[])

    assert "Назовите спикеров" in card.header
    assert "Проверьте сопоставление" not in card.header


def test_card_header_confirms_with_participants():
    """Со списком участников заголовок остаётся про проверку сопоставления."""
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card(
        {}, _diarization_two_speakers(), participants=[{"name": "Иван Петров"}]
    )

    assert "Проверьте сопоставление" in card.header


def test_subview_keyboard_survives_empty_participants():
    """Под-вид выбора участника не падает при пустом списке (enumerate([]))."""
    keyboard = create_mapping_keyboard(
        speaker_mapping={},
        diarization=_diarization_two_speakers(),
        participants=[],
        user_id=42,
        current_editing_speaker="SPEAKER_1",
    )
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    # Есть «Оставить без имени» и «Ввести имя вручную», без кнопок участников
    assert "sm_select:SPEAKER_1:none:42" in callbacks
    assert "sm_custom:SPEAKER_1:42" in callbacks


@pytest.mark.asyncio
async def test_confirmation_pause_defaults_participants_and_stores_card(monkeypatch):
    """Без списка участников карточка всё равно показывается (participants=[]),
    пауза происходит, ссылка на карточку кладётся в сессию для правки на месте."""
    import types

    import src.utils.telegram_safe as ts
    import src.ux.speaker_audio_preview as preview
    import src.ux.speaker_mapping_ui as ui
    from src.services.processing.processing_service import ProcessingService

    captured = {}
    sentinel_card = _FakeMessage(42)

    async def fake_show(**kwargs):
        captured["participants"] = kwargs.get("participants")
        return sentinel_card

    async def fake_previews(**kwargs):
        return set()

    async def fake_edit(message, text, **kwargs):
        return True

    monkeypatch.setattr(ui, "show_mapping_confirmation", fake_show)
    monkeypatch.setattr(preview, "send_speaker_audio_previews", fake_previews)
    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    service = ProcessingService.__new__(ProcessingService)

    request = ProcessingRequest(
        user_id=42, file_name="a.mp3", llm_provider="openai",
        participants_list=None,
    )
    transcription = TranscriptionResult(
        transcription="текст", diarization=_diarization_two_speakers(),
        compression_info=None,
    )
    metrics = ProcessingMetrics(
        file_name="a.mp3", user_id=42, start_time=datetime.now()
    )
    progress_tracker = types.SimpleNamespace(
        update_task=None, message=_FakeMessage(42),
        bot=SimpleNamespace(), chat_id=42,
    )

    result = await service._handle_speaker_mapping_confirmation(
        request, transcription, {}, None, None, metrics, progress_tracker,
    )

    assert result is None  # обработка приостановлена
    assert captured["participants"] == []
    session = mapping_sessions.peek(42)
    assert session is not None
    assert session.confirmation_message is sentinel_card
