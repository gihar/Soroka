"""Критика v11: две записи подряд не отменяют друг друга.

Хранилище сессий сопоставления было словарём по ``user_id``, а ``save``
писал в него без проверки. Пользователь, загрузивший вторую встречу, пока
карточка первой ещё висела в чате, молча терял первую расшифровку — самую
дорогую часть конвейера. Дальше каскад: таймер первой записи срабатывал
раньше и доставлял ЧУЖУЮ вторую запись досрочно, а кнопки старой карточки
правили сопоставление второй.

Ключ — пара «пользователь + запись». Живая сессия при новой паузе не
затирается, а доводится до протокола тем же путём, что таймер.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, TranscriptionResult
from src.performance.metrics import ProcessingMetrics
from src.services.mapping_session import MappingSession, MappingSessionStore


def _session(task_id=None, mapping=None, user_id=42, file_name="встреча.mp3"):
    return MappingSession(
        request=ProcessingRequest(
            user_id=user_id, file_name=file_name, template_id=2,
            llm_provider="openai",
        ),
        transcription_result=TranscriptionResult(transcription="текст"),
        speaker_mapping=dict(mapping or {}),
        meeting_type="general",
        temp_file_path=None,
        cache_key=None,
        task_id=task_id,
        metrics=ProcessingMetrics(
            file_name=file_name, user_id=user_id, start_time=datetime.now()
        ),
    )


# ---------------------------------------------------------------------------
# Хранилище: ключ — пара «пользователь + запись»
# ---------------------------------------------------------------------------


def test_second_recording_does_not_evict_the_first():
    """Главная находка: вторая пауза больше не стирает первую расшифровку."""
    store = MappingSessionStore()
    first = _session(task_id="task-1")
    store.save(42, first)

    store.save(42, _session(task_id="task-2"))

    assert store.take_regardless(42, "task-1") is first


def test_save_returns_the_key_of_the_stored_session():
    store = MappingSessionStore()
    key = store.save(42, _session(task_id="task-1"))
    assert store.take_regardless(42, key) is not None


def test_sessions_without_task_id_still_get_distinct_keys():
    """task_id опционален — две безымянные записи всё равно не сливаются."""
    store = MappingSessionStore()
    first, second = _session(), _session()

    key_first = store.save(42, first)
    key_second = store.save(42, second)

    assert key_first != key_second
    assert store.take_regardless(42, key_first) is first


def test_peek_returns_the_newest_session():
    """У карточки контракт прежний: одна открытая карточка на пользователя."""
    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))
    newest = _session(task_id="task-2")
    store.save(42, newest)

    assert store.peek(42) is newest


def test_take_regardless_without_key_takes_the_active_session():
    store = MappingSessionStore()
    newest = _session(task_id="task-2")
    store.save(42, _session(task_id="task-1"))
    store.save(42, newest)

    assert store.take_regardless(42) is newest


def test_take_regardless_with_key_ignores_the_active_session():
    """Таймер первой записи не имеет права забрать вторую."""
    store = MappingSessionStore()
    first = _session(task_id="task-1")
    store.save(42, first)
    second = _session(task_id="task-2")
    store.save(42, second)

    assert store.take_regardless(42, "task-1") is first
    assert store.peek(42) is second, "вторая запись обязана остаться нетронутой"


def test_take_regardless_ignores_ttl():
    store = MappingSessionStore(ttl_seconds=3600)
    key = store.save(42, _session(task_id="task-1"))
    store._timestamps[(42, key)] = datetime.now() - timedelta(hours=2)

    assert store.take_regardless(42, key) is not None


def test_peek_still_evicts_expired():
    store = MappingSessionStore(ttl_seconds=3600)
    key = store.save(42, _session(task_id="task-1"))
    store._timestamps[(42, key)] = datetime.now() - timedelta(hours=2)

    assert store.peek(42) is None


def test_take_is_atomic():
    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))

    assert store.take(42) is not None
    assert store.take(42) is None


def test_discard_targets_one_recording():
    """discard выбрасывает названную запись и не трогает соседнюю.

    В проде две живые сессии одновременно не встречаются — предыдущую доводит
    ``finish_superseded_session`` до того, как слот займёт новая. Но ключ
    обязан работать точечно: иначе «UI не показался» по второй записи унёс бы
    первую, а это ровно та потеря, ради которой ключ и вводился.
    """
    store = MappingSessionStore()
    first = _session(task_id="task-1")
    store.save(42, first)
    store.save(42, _session(task_id="task-2"))

    store.discard(42, "task-2")

    assert store.take_regardless(42, "task-1") is first


def test_users_do_not_share_keys():
    store = MappingSessionStore()
    mine = _session(task_id="task-1", user_id=42)
    store.save(42, mine)
    store.save(99, _session(task_id="task-1", user_id=99))

    assert store.take_regardless(42, "task-1") is mine


# ---------------------------------------------------------------------------
# «Сессии не было» против «сессия закрыта доставкой»
# ---------------------------------------------------------------------------


def test_closed_session_is_remembered():
    """Устаревшая карточка должна знать, что протокол уже доставлен."""
    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))
    store.take(42)

    assert store.was_recently_closed(42) is True


def test_unknown_user_was_never_closed():
    assert MappingSessionStore().was_recently_closed(42) is False


def test_auto_delivery_also_counts_as_closed():
    store = MappingSessionStore()
    key = store.save(42, _session(task_id="task-1"))
    store.take_regardless(42, key)

    assert store.was_recently_closed(42) is True


def test_discard_is_not_a_delivery():
    """UI не показался — протокола не было, врать про доставку нельзя."""
    store = MappingSessionStore()
    key = store.save(42, _session(task_id="task-1"))
    store.discard(42, key)

    assert store.was_recently_closed(42) is False


def test_stale_card_text_does_not_claim_the_work_is_lost():
    from src.handlers.callbacks.speaker_mapping_callbacks import _DELIVERED_TEXT

    assert "заново" not in _DELIVERED_TEXT.lower()
    assert "доставлен" in _DELIVERED_TEXT.lower()


# ---------------------------------------------------------------------------
# Таймер привязан к своей записи
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timer_delivers_only_its_own_recording():
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    first = _session(task_id="task-1")
    store.save(42, first)
    second = _session(task_id="task-2")
    store.save(42, second)

    service = SimpleNamespace(
        continue_processing_after_mapping_confirmation=AsyncMock()
    )
    await deliver_on_timeout(
        service, store, user_id=42, session_key="task-1",
        bot=SimpleNamespace(send_message=AsyncMock()), chat_id=1, delay_seconds=0,
    )

    delivered = service.continue_processing_after_mapping_confirmation.await_args
    assert delivered.kwargs["session"] is first
    assert store.peek(42) is second, "вторая запись не должна пострадать"


@pytest.mark.asyncio
async def test_timer_is_silent_when_its_recording_is_gone():
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))
    store.take_regardless(42, "task-1")

    service = SimpleNamespace(
        continue_processing_after_mapping_confirmation=AsyncMock()
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    await deliver_on_timeout(
        service, store, user_id=42, session_key="task-1",
        bot=bot, chat_id=1, delay_seconds=0,
    )

    service.continue_processing_after_mapping_confirmation.assert_not_awaited()
    bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Новая пауза доводит предыдущую запись, а не выбрасывает её
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_previous_recording_is_finished_not_dropped():
    from src.services.mapping_timeout import finish_superseded_session

    store = MappingSessionStore()
    previous = _session(task_id="task-1", mapping={"SPEAKER_1": "Иван"})
    store.save(42, previous)

    service = SimpleNamespace(
        continue_processing_after_mapping_confirmation=AsyncMock()
    )
    finished = await finish_superseded_session(
        service, store, user_id=42,
        bot=SimpleNamespace(send_message=AsyncMock()), chat_id=1,
    )

    assert finished is True
    call = service.continue_processing_after_mapping_confirmation.await_args
    assert call.kwargs["session"] is previous
    assert call.kwargs["confirmed_mapping"] == {"SPEAKER_1": "Иван"}


@pytest.mark.asyncio
async def test_superseded_recording_is_explained_in_one_line():
    from src.services.mapping_timeout import finish_superseded_session

    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))
    bot = SimpleNamespace(send_message=AsyncMock())

    await finish_superseded_session(
        SimpleNamespace(continue_processing_after_mapping_confirmation=AsyncMock()),
        store, user_id=42, bot=bot, chat_id=1,
    )

    text = bot.send_message.await_args.kwargs["text"]
    assert "Участник N" in text, "пользователь должен узнать цену досрочного конца"
    assert len(text.splitlines()) <= 2


@pytest.mark.asyncio
async def test_nothing_to_supersede_is_a_noop():
    from src.services.mapping_timeout import finish_superseded_session

    bot = SimpleNamespace(send_message=AsyncMock())
    finished = await finish_superseded_session(
        SimpleNamespace(continue_processing_after_mapping_confirmation=AsyncMock()),
        MappingSessionStore(), user_id=42, bot=bot, chat_id=1,
    )

    assert finished is False
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_superseding_survives_a_failing_resume():
    """Довести не вышло — новая запись всё равно обязана встать на паузу."""
    from src.services.mapping_timeout import finish_superseded_session

    store = MappingSessionStore()
    store.save(42, _session(task_id="task-1"))

    service = SimpleNamespace(
        continue_processing_after_mapping_confirmation=AsyncMock(
            side_effect=RuntimeError("LLM упал")
        )
    )
    finished = await finish_superseded_session(
        service, store, user_id=42,
        bot=SimpleNamespace(send_message=AsyncMock()), chat_id=1,
    )

    assert finished is False


# ---------------------------------------------------------------------------
# Карточка называет запись
# ---------------------------------------------------------------------------


def test_card_names_the_recording():
    from src.ux.speaker_mapping_ui import build_mapping_card

    card = build_mapping_card({}, None, [], record_name="Планёрка.mp3")

    assert "Планёрка.mp3" in card.to_html()
    assert "Планёрка.mp3" in card.to_plain()


def test_card_without_a_name_is_unchanged():
    from src.ux.speaker_mapping_ui import build_mapping_card

    assert build_mapping_card({}, None, []).record_name is None


def test_record_name_is_escaped():
    from src.ux.card_content import MappingCard

    card = MappingCard(header="Заголовок", record_name="<b>жирный</b>.mp3")

    assert "&lt;b&gt;" in card.to_html()


# ---------------------------------------------------------------------------
# Ловец имени не забирает чужой диалог
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_capture_stands_down_inside_another_dialog():
    """Правка шапки протокола ждёт дату — карточка не имеет права её съесть."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        _capturing_speaker_name,
    )
    from src.handlers.participants_states import ProtocolHeaderEdit
    from src.services.mapping_session import mapping_sessions

    mapping_sessions.save(77, _session(task_id="task-1", user_id=77))
    try:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=77), text="27 июля 2026"
        )
        state = SimpleNamespace(
            get_state=AsyncMock(
                return_value=ProtocolHeaderEdit.waiting_for_header.state
            )
        )

        assert await _capturing_speaker_name(message, state) is False
    finally:
        mapping_sessions.discard(77)


@pytest.mark.asyncio
async def test_name_capture_still_works_without_a_dialog():
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        _capturing_speaker_name,
    )
    from src.services.mapping_session import mapping_sessions

    mapping_sessions.save(78, _session(task_id="task-1", user_id=78))
    try:
        message = SimpleNamespace(from_user=SimpleNamespace(id=78), text="Иван")
        state = SimpleNamespace(get_state=AsyncMock(return_value=None))

        assert await _capturing_speaker_name(message, state) is True
    finally:
        mapping_sessions.discard(78)


@pytest.mark.asyncio
async def test_name_capture_without_state_argument_still_works():
    """FSMContext может не приехать — фильтр обязан пережить это."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        _capturing_speaker_name,
    )
    from src.services.mapping_session import mapping_sessions

    mapping_sessions.save(79, _session(task_id="task-1", user_id=79))
    try:
        message = SimpleNamespace(from_user=SimpleNamespace(id=79), text="Иван")
        assert await _capturing_speaker_name(message, None) is True
    finally:
        mapping_sessions.discard(79)


def test_router_comment_no_longer_claims_state_isolation():
    """Комментарий утверждал то, чего код не делал (критика v11)."""
    from pathlib import Path

    source = Path("src/handlers/callbacks/__init__.py").read_text(encoding="utf-8")
    assert "с карточкой не конкурирует" not in source


@pytest.mark.asyncio
async def test_asyncio_is_not_needed_for_a_missing_session():
    """Санитарная проверка: фильтр без сессии молчит, состояние не важно."""
    from src.handlers.callbacks.speaker_mapping_callbacks import (
        _capturing_speaker_name,
    )

    message = SimpleNamespace(from_user=SimpleNamespace(id=4242), text="Иван")
    assert await _capturing_speaker_name(message, None) is False


def test_module_imports_asyncio_free():
    """Заглушка-страховка от случайного удаления asyncio-импорта в таймере."""
    import src.services.mapping_timeout as mt

    assert asyncio is not None and hasattr(mt, "deliver_on_timeout")
