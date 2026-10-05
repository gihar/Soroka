"""Кнопки карточки закрывают паузу ровно один раз.

Подтверждение и пропуск атомарно изымают сессию (take): двойной тап не
запускает второе возобновление, а устаревшая карточка честно говорит, что
протокол уже доставлен. Сбой возобновления правит карточку текстом из
классификатора (ADR-0010).
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.models.diarization import Diarization, Segment
from src.models.processing import ProcessingRequest, TranscriptionResult
from src.performance.metrics import ProcessingMetrics
from src.services.mapping_session import MappingSession, MappingSessionStore

RAW_403 = (
    "Error code: 403 - {'error': {'type': 'AccessDenied.Unpurchased', "
    "'message': 'Access to model denied.'}}"
)


def _session(*, mapping=None, participants=None):
    return MappingSession(
        request=ProcessingRequest(
            user_id=42, file_name="встреча.mp3", template_id=5,
            llm_provider="openai", participants_list=participants,
        ),
        transcription_result=TranscriptionResult(
            transcription="текст",
            diarization=Diarization(segments=[
                Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="привет"),
                Segment(start=6.0, end=9.0, speaker="SPEAKER_2", text="да"),
            ]),
        ),
        speaker_mapping=dict(mapping or {}),
        meeting_type="general",
        temp_file_path=None,
        cache_key=None,
        task_id="task-1",
        metrics=ProcessingMetrics(
            file_name="встреча.mp3", user_id=42, start_time=datetime.now()
        ),
    )


class _State:
    async def clear(self):
        return None

    async def get_state(self):
        return None


class _Callback:
    def __init__(self):
        self.from_user = SimpleNamespace(id=42)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=4242))
        self.bot = SimpleNamespace()

    async def answer(self, *args, **kwargs):
        return None


class _ClosingSpy:
    """Пауза на карточке: записывает, с каким поводом её закрыли."""

    def __init__(self, error=None):
        self.closes = []
        self.error = error

    async def close(self, session, reason, *, channel):

        self.closes.append(SimpleNamespace(
            session=session,
            reason=reason,
            chat_id=channel.chat_id,
        ))
        if self.error:
            raise self.error


def _router(spy):
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    return cb.setup_speaker_mapping_callbacks(SimpleNamespace(), SimpleNamespace(), spy)


def _handler(router, cbdata_cls):
    for handler in router.callback_query.handlers:
        for flt in handler.filters:
            if getattr(flt.callback, "callback_data", None) is cbdata_cls:
                return handler.callback
    raise AssertionError(f"нет хендлера для {cbdata_cls.__name__}")


@pytest.fixture
def store(monkeypatch):
    import src.handlers.callbacks.speaker_mapping_callbacks as cb
    import src.services.mapping_session as ms

    fresh = MappingSessionStore()
    monkeypatch.setattr(ms, "mapping_sessions", fresh)
    monkeypatch.setattr(cb, "mapping_sessions", fresh)
    return fresh


@pytest.fixture
def card(monkeypatch):
    """Тексты, которыми правилась карточка."""
    import src.handlers.callbacks.speaker_mapping_callbacks as cb

    edits = []

    async def fake_edit(message, text, **kwargs):
        edits.append(str(text))
        return True

    monkeypatch.setattr(cb, "safe_edit_text", fake_edit)
    return edits


async def test_double_tap_on_confirm_closes_once(store, card):
    from src.ux.speaker_mapping_callback_data import SmConfirm

    session = _session(mapping={"SPEAKER_1": "Иван"})
    store.save(42, session)
    spy = _ClosingSpy()
    confirm = _handler(_router(spy), SmConfirm)

    await confirm(_Callback(), SmConfirm(user_id=42), _State())
    await confirm(_Callback(), SmConfirm(user_id=42), _State())

    assert len(spy.closes) == 1
    assert spy.closes[0].session is session
    assert spy.closes[0].reason.value == "confirmed"
    assert spy.closes[0].chat_id == 4242
    assert "уже доставлен" in card[-1]


async def test_double_tap_on_skip_closes_once(store, card):
    from src.ux.speaker_mapping_callback_data import SmSkip

    # Кто-то назван — пропуск без переспроса, имена не применяются.
    store.save(42, _session(mapping={"SPEAKER_1": "Иван"}))
    spy = _ClosingSpy()
    skip = _handler(_router(spy), SmSkip)

    await skip(_Callback(), SmSkip(user_id=42), _State())
    await skip(_Callback(), SmSkip(user_id=42), _State())

    assert len(spy.closes) == 1
    assert spy.closes[0].reason.value == "skipped"


async def test_confirmed_skip_of_an_empty_run_closes_once(store, card):
    from src.ux.speaker_mapping_callback_data import SmSkipConfirm

    store.save(42, _session())
    spy = _ClosingSpy()
    skip_ok = _handler(_router(spy), SmSkipConfirm)

    await skip_ok(_Callback(), SmSkipConfirm(user_id=42), _State())
    await skip_ok(_Callback(), SmSkipConfirm(user_id=42), _State())

    assert len(spy.closes) == 1
    assert spy.closes[0].reason.value == "skipped"


async def test_failed_resume_rewrites_the_card_from_the_classifier(store, card):
    from src.ux.speaker_mapping_callback_data import SmConfirm

    store.save(42, _session())
    spy = _ClosingSpy(error=RuntimeError(RAW_403))
    confirm = _handler(_router(spy), SmConfirm)

    await confirm(_Callback(), SmConfirm(user_id=42), _State())

    assert "файл менять не нужно" in card[-1]
