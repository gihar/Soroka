"""Пауза на карточке сопоставления: открыть и закрыть с поводом.

Жизненный цикл Сессии сопоставления от начала до конца:

* **открыть** — заглушить трекер, прислать фрагменты записи, довести
  вытесненную предыдущую сессию, сохранить новую, показать карточку последним
  сообщением, завести таймер; карточку отправить не удалось — сказать об этом и
  продолжать без паузы;
* **закрыть с поводом** — подтверждение, пропуск, истёк срок, вытеснение новой
  записью; любой повод ведёт в единый хвост «Завершение обработки» (ADR-0003);
* **сбой после паузы** — тот же, что в воркере: пользователь, администратор,
  статус задачи очереди (ADR-0010).

Telegram здесь — фейковый чат: тесты смотрят на то, что увидел бы
пользователь (сообщения, карточка, фрагменты, протокол) и на учёт (хранилище
сессий, статус задачи, алерт администратору).
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.diarization import Diarization, Segment
from src.models.processing import ProcessingRequest, TranscriptionResult
from src.performance.metrics import ProcessingMetrics
from src.services.mapping_session import MappingSession, MappingSessionStore

RAW_UNKNOWN = (
    "Error code: 451 - {'error': {'message': 'Model unavailable in your region'}}"
)
_ADMIN_BOT = object()


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------


def _diarization() -> Diarization:
    return Diarization(segments=[
        Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="привет всем"),
        Segment(start=6.0, end=9.0, speaker="SPEAKER_2", text="да, начнём"),
    ])


def _session(
    *, user_id=42, task_id="task-1", mapping=None, participants=None,
    file_name="встреча.mp3", cache_key="ck",
) -> MappingSession:
    return MappingSession(
        request=ProcessingRequest(
            user_id=user_id, file_name=file_name, template_id=5,
            llm_provider="openai", participants_list=participants,
        ),
        transcription_result=TranscriptionResult(
            transcription="текст", diarization=_diarization(),
        ),
        speaker_mapping=dict(mapping or {}),
        meeting_type="general",
        temp_file_path="temp/встреча.mp3",
        cache_key=cache_key,
        task_id=task_id,
        metrics=ProcessingMetrics(
            file_name=file_name, user_id=user_id, start_time=datetime.now()
        ),
        template=SimpleNamespace(id=5, name="Дейли"),
    )


# ---------------------------------------------------------------------------
# Фейковый чат: всё, что видит пользователь
# ---------------------------------------------------------------------------


class FakeChat:
    """Запись того, что ушло пользователю в чат."""

    def __init__(self):
        self.chat_id = 42
        self.events = []
        self.previews = []
        self.cards = []
        self.said = []
        self.failures = []
        self.delivered = []
        self.resume_trackers = []
        # Настройки поведения
        self.card_message = SimpleNamespace(name="карточка")
        self.previews_result = {"SPEAKER_1"}
        self.previews_raise = False
        self.deliver_ok = True


def _resume_tracker():
    return SimpleNamespace(
        start_stage=AsyncMock(), complete_all=AsyncMock(),
        bot=SimpleNamespace(), chat_id=42,
    )


class LegacyDriver:
    """Старый интерфейс: ProcessingService + mapping_timeout + патчи модулей."""

    def __init__(self, monkeypatch, chat, store, deps):
        import src.services.mapping_session as ms
        import src.services.mapping_timeout as mt
        import src.services.processing.processing_service as pss
        import src.services.result_sender as rs
        import src.utils.telegram_safe as ts
        import src.ux.progress_tracker as pt_mod
        import src.ux.speaker_audio_preview as preview
        import src.ux.speaker_mapping_ui as ui
        from src.services.processing.processing_service import ProcessingService

        self.chat = chat
        self.store = store
        self.scheduled = []
        self.tracker_message = SimpleNamespace(name="трекер")

        monkeypatch.setattr(ms, "mapping_sessions", store)

        async def fake_edit(message, text, **kwargs):
            if message is self.tracker_message:
                chat.events.append("silence")
            return True

        monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

        async def fake_previews(**kwargs):
            chat.events.append("previews")
            chat.previews.append(kwargs)
            if chat.previews_raise:
                raise RuntimeError("фрагменты не нарезались")
            return set(chat.previews_result)

        monkeypatch.setattr(preview, "send_speaker_audio_previews", fake_previews)

        async def fake_show(**kwargs):
            chat.events.append("card")
            chat.cards.append(kwargs)
            return chat.card_message

        monkeypatch.setattr(ui, "show_mapping_confirmation", fake_show)

        async def fake_failure_notice(bot=None, chat_id=None, text=None, **kwargs):
            chat.events.append("failure")
            chat.failures.append(text)

        monkeypatch.setattr(pss, "safe_send_message", fake_failure_notice)

        async def fake_tracker(bot=None, chat_id=None, *args, **kwargs):
            tracker = _resume_tracker()
            chat.resume_trackers.append(tracker)
            return tracker

        monkeypatch.setattr(
            pt_mod.ProgressFactory, "create_file_processing_tracker", fake_tracker
        )

        async def fake_deliver(**kwargs):
            chat.events.append("deliver")
            chat.delivered.append(kwargs["result"])
            return chat.deliver_ok

        monkeypatch.setattr(rs, "send_result_to_user", fake_deliver)

        async def bot_send(chat_id=None, text=None, **kwargs):
            chat.events.append("say")
            chat.said.append(text)

        self.bot = SimpleNamespace(send_message=bot_send)

        proxy = SimpleNamespace(
            CancelledError=asyncio.CancelledError,
            gather=asyncio.gather,
            create_task=self.scheduled.append,
        )
        monkeypatch.setattr(pss, "asyncio", proxy)
        self.delay = 0
        monkeypatch.setattr(mt, "auto_deliver_delay_seconds", lambda store: self.delay)

        self.service = ProcessingService()
        self.service.llm_gen = deps.llm_gen
        self.service.formatter = deps.formatter
        self.service.history = deps.history

    def _tracker(self):
        return SimpleNamespace(
            update_task=None, message=self.tracker_message,
            bot=self.bot, chat_id=self.chat.chat_id,
        )

    async def open(self, session, *, with_tracker=True) -> bool:
        """Открыть паузу. True — обработка приостановлена на карточке."""
        result = await self.service._handle_speaker_mapping_confirmation(
            session.request, session.transcription_result,
            session.speaker_mapping, session.meeting_type,
            session.temp_file_path, session.metrics,
            self._tracker() if with_tracker else None,
            cache_key=session.cache_key, task_id=session.task_id,
            template=session.template,
        )
        return result is None

    async def close(self, session, reason: str):
        mapping = {} if reason == "skipped" else session.speaker_mapping
        return await self.service.continue_processing_after_mapping_confirmation(
            session=session, confirmed_mapping=mapping,
            bot=self.bot, chat_id=self.chat.chat_id,
        )

    async def run_pipeline(self, request, *, transcription, monkeypatch) -> bool:
        """Прогнать конвейер записи. True — прогон встал на паузу."""
        import src.services.processing.processing_service as pss

        _quiet_pipeline(monkeypatch, pss)
        _fake_pipeline_world(self.service, transcription)
        tracker = self._tracker()
        tracker.start_stage = AsyncMock()
        tracker.complete_all = AsyncMock()
        result = await self.service.process_file(request, tracker, task_id="task-9")
        return result is None

    async def fire_timers(self):
        while self.scheduled:
            await self.scheduled.pop(0)

    def timers(self):
        return list(self.scheduled)


def _quiet_pipeline(monkeypatch, pss):
    """Конвейер без фоновых мониторов и без процессного кеша."""
    from src.performance.memory_management import memory_optimizer
    from src.performance.metrics import metrics_collector

    monkeypatch.setattr(metrics_collector, "is_monitoring", True)
    monkeypatch.setattr(memory_optimizer, "is_optimizing", True)
    monkeypatch.setattr(
        pss, "performance_cache",
        SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock()),
    )


def _fake_pipeline_world(service, transcription):
    """Внешний мир конвейера: распознавание речи, пользователи, шаблоны."""
    template = SimpleNamespace(id=5, name="Дейли")
    service.transcription_service = SimpleNamespace(
        transcribe_with_diarization=AsyncMock(return_value=transcription)
    )
    service.user_service = SimpleNamespace(
        get_user_by_telegram_id=AsyncMock(
            return_value=SimpleNamespace(speaker_mapping_enabled=True)
        )
    )
    service.template_service = SimpleNamespace(
        get_template_by_id=AsyncMock(return_value=template)
    )


def _external_request(tmp_path) -> ProcessingRequest:
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"data")
    return ProcessingRequest(
        file_name="rec.mp3", llm_provider="openai", user_id=42, template_id=5,
        is_external_file=True, file_path=str(audio),
    )


@pytest.fixture
def chat():
    return FakeChat()


@pytest.fixture
def store():
    return MappingSessionStore()


@pytest.fixture
def generation():
    """Генерация протокола: по умолчанию успешна, тест может уронить её."""
    return SimpleNamespace(
        llm_gen=SimpleNamespace(
            optimized_llm_generation=AsyncMock(return_value={"meeting_title": "Планёрка"}),
            resolve_model_display_name=AsyncMock(return_value="GPT"),
        ),
        formatter=SimpleNamespace(format_protocol=lambda *a, **k: "# Протокол"),
        history=SimpleNamespace(
            save_processing_history=AsyncMock(return_value=99),
            cleanup_temp_file=AsyncMock(),
            calculate_file_hash=AsyncMock(return_value="hash"),
            generate_result_cache_key=lambda request, file_hash: f"result:{file_hash}",
        ),
    )


@pytest.fixture
def queue(monkeypatch):
    """Статусы задач очереди, проставленные обработкой."""
    import src.services.processing.completion as completion
    from src.database import queue_repo

    statuses = []

    async def fake_update(task_id, status, *args, error_message=None, **kwargs):
        statuses.append((task_id, status))

    monkeypatch.setattr(queue_repo, "update_queue_task_status", fake_update)
    monkeypatch.setattr(
        completion, "performance_cache", SimpleNamespace(set=AsyncMock())
    )
    return statuses


@pytest.fixture
def admin(monkeypatch):
    """Алерты администратору: тексты без похода в Telegram."""
    import src.utils.telegram_safe as telegram_safe
    from src.config import settings
    from src.services import admin_alerts

    texts = []
    original = telegram_safe.safe_send_message

    async def route(bot, chat_id, text=None, *args, **kwargs):
        if bot is _ADMIN_BOT:
            texts.append(str(text))
            return SimpleNamespace(message_id=1)
        return await original(bot, chat_id, text, *args, **kwargs)

    monkeypatch.setattr(telegram_safe, "safe_send_message", route)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: _ADMIN_BOT)
    monkeypatch.setattr(settings, "admins", [111])
    return texts


@pytest.fixture
def pause(monkeypatch, chat, store, generation, queue, admin):
    import src.utils.telegram_safe as ts

    driver = LegacyDriver(monkeypatch, chat, store, generation)

    # Уведомление «карточка не ушла» — обычное сообщение в чат пользователя.
    routed = ts.safe_send_message

    async def say_or_route(bot=None, chat_id=None, text=None, *args, **kwargs):
        if bot is _ADMIN_BOT:
            return await routed(bot, chat_id, text, *args, **kwargs)
        chat.events.append("say")
        chat.said.append(text)
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(ts, "safe_send_message", say_or_route)
    yield driver
    for timer in driver.timers():  # невыстреленные таймеры не текут в другие тесты
        timer.close()


# ---------------------------------------------------------------------------
# Открыть паузу
# ---------------------------------------------------------------------------


async def test_opening_pauses_and_puts_the_card_last(pause, chat):
    """Трекер замолкает, фрагменты уходят до карточки, карточка — последней."""
    paused = await pause.open(_session(mapping={"SPEAKER_1": "Иван"}))

    assert paused is True
    assert chat.events == ["silence", "previews", "card"]


async def test_opening_keeps_the_session_for_the_card(pause, chat, store):
    session = _session(mapping={"SPEAKER_1": "Иван"})

    await pause.open(session)

    kept = store.peek(42)
    assert kept is not None
    assert kept.request is session.request
    assert kept.speaker_mapping == {"SPEAKER_1": "Иван"}
    assert kept.task_id == "task-1"
    assert kept.cache_key == "ck"
    assert kept.template is session.template
    # Ссылка на карточку — для правки на месте при ручном вводе имени.
    assert kept.confirmation_message is chat.card_message


async def test_previews_cover_every_speaker_of_the_recording(pause, chat):
    await pause.open(_session())

    sent = chat.previews[0]
    assert sent["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert sent["temp_file_path"] == "temp/встреча.mp3"
    assert sent["user_id"] == 42


async def test_delivered_fragments_reach_the_card_and_the_session(pause, chat, store):
    """Цитата показывается один раз: кому дошёл фрагмент, тому в карточке не нужна."""
    chat.previews_result = {"SPEAKER_1"}

    await pause.open(_session())

    assert chat.cards[0]["speakers_with_audio"] == {"SPEAKER_1"}
    assert store.peek(42).speakers_with_audio == {"SPEAKER_1"}


async def test_failed_fragments_do_not_block_the_pause(pause, chat):
    chat.previews_raise = True

    paused = await pause.open(_session())

    assert paused is True
    assert chat.cards[0]["speakers_with_audio"] == set()


async def test_card_lists_unnamed_speakers_and_names_the_recording(pause, chat):
    await pause.open(_session(mapping={"SPEAKER_1": "Иван"}, file_name="Планёрка.mp3"))

    card = chat.cards[0]
    assert card["unmapped_speakers"] == ["SPEAKER_2"]
    assert card["speaker_mapping"] == {"SPEAKER_1": "Иван"}
    assert card["record_name"] == "Планёрка.mp3"
    assert card["user_id"] == 42


async def test_card_with_everyone_named_has_no_unnamed_list(pause, chat):
    await pause.open(_session(mapping={"SPEAKER_1": "Иван", "SPEAKER_2": "Аня"}))

    assert chat.cards[0]["unmapped_speakers"] is None


async def test_card_without_participants_list_gets_an_empty_list(pause, chat):
    """Список не передан — карточка всё равно открывается (ADR-0002)."""
    await pause.open(_session(participants=None))

    assert chat.cards[0]["participants"] == []


async def test_card_that_failed_to_send_continues_without_pause(pause, chat, store):
    """Карточка не ушла — пользователь узнаёт об этом, обработка идёт дальше."""
    chat.card_message = None

    paused = await pause.open(_session())

    assert paused is False
    assert any("Не удалось отправить" in text for text in chat.said)
    assert store.peek(42) is None
    # Протокола не было — устаревшей карточке нельзя врать про доставку.
    assert store.was_recently_closed(42) is False
    assert pause.timers() == []


async def test_no_chat_means_no_pause(pause, chat, store):
    """Без канала к пользователю ставить паузу некуда — обработка идёт дальше."""
    paused = await pause.open(_session(), with_tracker=False)

    assert paused is False
    assert chat.events == []
    assert store.peek(42) is None


# ---------------------------------------------------------------------------
# Конвейер: прогон встаёт на паузу или доходит до протокола
# ---------------------------------------------------------------------------


async def test_pipeline_with_speakers_stops_at_the_card(
    pause, chat, store, tmp_path, monkeypatch, queue,
):
    paused = await pause.run_pipeline(
        _external_request(tmp_path),
        transcription=TranscriptionResult(transcription="текст", diarization=_diarization()),
        monkeypatch=monkeypatch,
    )

    assert paused is True
    assert chat.cards and chat.delivered == []
    assert store.peek(42).task_id == "task-9"
    assert store.peek(42).cache_key == "result:hash"
    assert queue == []  # статус задачи проставит закрытие паузы


async def test_pipeline_without_speakers_goes_straight_to_the_protocol(
    pause, chat, tmp_path, monkeypatch, queue,
):
    paused = await pause.run_pipeline(
        _external_request(tmp_path),
        transcription=TranscriptionResult(transcription="текст"),
        monkeypatch=monkeypatch,
    )

    assert paused is False
    assert chat.cards == []
    assert len(chat.delivered) == 1
    assert queue == [("task-9", "completed")]


# ---------------------------------------------------------------------------
# Закрыть с поводом: подтверждение и пропуск
# ---------------------------------------------------------------------------


async def test_confirmation_delivers_the_protocol_with_the_names(pause, chat, queue):
    session = _session(mapping={"SPEAKER_1": "Иван"})

    result = await pause.close(session, "confirmed")

    assert chat.delivered == [result]
    assert result.protocol_text == "# Протокол"
    assert result.history_id == 99
    assert session.request.speaker_mapping == {"SPEAKER_1": "Иван"}
    assert queue == [("task-1", "completed")]


async def test_skip_delivers_without_names(pause, chat):
    session = _session(mapping={"SPEAKER_1": "Иван"})

    await pause.close(session, "skipped")

    assert len(chat.delivered) == 1
    assert session.request.speaker_mapping == {}


async def test_resume_reuses_the_template_chosen_before_the_pause(pause, generation):
    session = _session()

    await pause.close(session, "confirmed")

    template = generation.llm_gen.optimized_llm_generation.await_args.args[1]
    assert template is session.template
    assert session.request.template_id == 5


async def test_resume_shows_its_own_progress_and_finishes_it(pause, chat):
    """Возобновление ведёт свой трекер и гасит его сам (утечка прода 27.07)."""
    await pause.close(_session(), "confirmed")

    tracker = chat.resume_trackers[0]
    tracker.start_stage.assert_awaited_with("analysis")
    tracker.complete_all.assert_awaited()


async def test_undelivered_protocol_marks_the_task_failed(pause, chat, queue):
    chat.deliver_ok = False

    await pause.close(_session(), "confirmed")

    assert queue == [("task-1", "failed")]


# ---------------------------------------------------------------------------
# Истёк срок: таймер против ручного подтверждения
# ---------------------------------------------------------------------------


async def test_timer_delivers_what_was_named_and_says_why_first(pause, chat, store):
    await pause.open(_session(mapping={"SPEAKER_1": "Иван"}))
    chat.events.clear()

    await pause.fire_timers()

    assert chat.events[0] == "say"
    assert "Участник N" in chat.said[-1]
    assert chat.events[-1] == "deliver"
    assert chat.delivered[0].speaker_mapping is not None
    assert store.peek(42) is None
    assert store.was_recently_closed(42) is True


async def test_timer_is_silent_after_the_user_confirmed(pause, chat, store):
    """Двойной доставки нет: подтверждение изъяло сессию раньше таймера."""
    await pause.open(_session())
    store.take(42)  # пользователь нажал «Подтвердить»
    chat.events.clear()

    await pause.fire_timers()

    assert chat.events == []


async def test_timer_waits_its_delay(pause, chat):
    """Раньше срока таймер не забирает карточку у пользователя."""
    pause.delay = 30
    await pause.open(_session())
    chat.events.clear()

    task = asyncio.ensure_future(pause.timers()[0])
    await asyncio.sleep(0)
    try:
        assert chat.events == []
    finally:
        task.cancel()
        pause.scheduled.clear()


async def test_timer_failure_still_reaches_the_user_and_the_admin(
    pause, chat, generation, queue, admin,
):
    generation.llm_gen.optimized_llm_generation.side_effect = RuntimeError(RAW_UNKNOWN)
    await pause.open(_session())

    await pause.fire_timers()  # фоновая задача не падает наружу

    assert len(chat.failures) == 1
    assert len(admin) == 1
    assert ("task-1", "failed") in queue


def test_timer_fires_before_the_store_forgets_the_session():
    from src.services.mapping_timeout import auto_deliver_delay_seconds

    assert auto_deliver_delay_seconds(MappingSessionStore(ttl_seconds=3600)) < 3600


# ---------------------------------------------------------------------------
# Вытеснение новой записью
# ---------------------------------------------------------------------------


async def test_new_recording_finishes_the_previous_one_first(pause, chat, store):
    first = _session(task_id="task-1", mapping={"SPEAKER_1": "Иван"})
    await pause.open(first)
    chat.events.clear()

    second = _session(task_id="task-2", file_name="вторая.mp3")
    await pause.open(second)

    # Сначала объяснение и протокол предыдущей записи, потом новая карточка.
    assert chat.events.index("say") < chat.events.index("deliver")
    assert "Участник N" in chat.said[-1]
    assert len(chat.said[-1].splitlines()) <= 2
    assert chat.events.index("deliver") < chat.events.index("card")
    assert first.request.speaker_mapping == {"SPEAKER_1": "Иван"}
    assert store.peek(42).request is second.request


async def test_superseded_timer_does_not_touch_the_new_recording(pause, chat, store):
    await pause.open(_session(task_id="task-1"))
    second = _session(task_id="task-2")
    await pause.open(second)
    first_timer = pause.timers()[0]
    pause.scheduled.remove(first_timer)
    chat.events.clear()

    await first_timer

    assert chat.events == []
    assert store.peek(42).request is second.request


async def test_failed_previous_recording_does_not_block_the_new_pause(
    pause, chat, generation, store, admin,
):
    await pause.open(_session(task_id="task-1"))
    generation.llm_gen.optimized_llm_generation.side_effect = RuntimeError(RAW_UNKNOWN)

    paused = await pause.open(_session(task_id="task-2"))

    assert paused is True
    assert len(chat.failures) == 1
    assert store.peek(42).task_id == "task-2"


async def test_nothing_to_supersede_says_nothing(pause, chat):
    await pause.open(_session())

    assert "say" not in chat.events


# ---------------------------------------------------------------------------
# Сбой после паузы: пользователь, администратор, статус задачи (ADR-0010)
# ---------------------------------------------------------------------------


async def test_failure_after_the_pause_reaches_user_admin_and_queue(
    pause, chat, generation, queue, admin,
):
    from src.exceptions.processing import ProcessingError

    generation.llm_gen.optimized_llm_generation.side_effect = RuntimeError(RAW_UNKNOWN)

    with pytest.raises(ProcessingError):
        await pause.close(_session(), "confirmed")

    assert len(chat.failures) == 1
    assert len(admin) == 1 and "451" in admin[0]
    assert ("task-1", "failed") in queue
    assert chat.delivered == []


async def test_broken_admin_alert_does_not_swallow_the_failure(
    pause, chat, generation, monkeypatch,
):
    from src.exceptions.processing import ProcessingError
    from src.services import provider_failure

    monkeypatch.setattr(
        provider_failure, "report_llm_failure",
        AsyncMock(side_effect=RuntimeError("telegram down")),
    )
    generation.llm_gen.optimized_llm_generation.side_effect = RuntimeError(RAW_UNKNOWN)

    with pytest.raises(ProcessingError):
        await pause.close(_session(), "confirmed")

    assert len(chat.failures) == 1


async def test_processing_error_passes_through_unchanged(pause, generation):
    from src.exceptions.processing import ProcessingError

    original = ProcessingError("LLM вернул пустой результат", "a.mp3", "llm_empty_result")
    generation.llm_gen.optimized_llm_generation.side_effect = original

    with pytest.raises(ProcessingError) as caught:
        await pause.close(_session(), "confirmed")

    assert caught.value is original


# ---------------------------------------------------------------------------
# Трекер основного прогона замолкает на паузе
# ---------------------------------------------------------------------------


async def test_pause_stops_tracker_autoupdates_and_rewrites_its_message(
    pause, monkeypatch,
):
    import src.utils.telegram_safe as ts

    edits = []

    async def fake_edit(message, text, **kwargs):
        edits.append((message, text))
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    async def forever():
        await asyncio.sleep(3600)

    update_task = asyncio.ensure_future(forever())
    tracker = pause._tracker()
    tracker.update_task = update_task
    pause._tracker = lambda: tracker

    await pause.open(_session())
    await asyncio.sleep(0)

    assert tracker.update_task is None
    assert update_task.cancelled()
    assert edits[0][0] is pause.tracker_message
    assert "Транскрипция завершена" in edits[0][1]
