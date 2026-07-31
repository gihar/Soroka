"""Критика v10: истечение карточки доставляет протокол, а не выбрасывает работу.

Прод: карточка сопоставления включена, сессия живёт в памяти час. Пользователь,
вернувшийся через 61 минуту, получал «❌ Состояние обработки не найдено или
истекло. Пожалуйста, начните обработку заново» — и готовая расшифровка (самая
дорогая часть конвейера) уходила в мусор.

Протокол — продукт. Несовершенный протокол с «Участник N» лучше, чем
отсутствующий: по таймауту обработка доводится до конца с тем сопоставлением,
которое успел ввести пользователь.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, TranscriptionResult
from src.performance.metrics import ProcessingMetrics
from src.services.mapping_session import MappingSession, MappingSessionStore


def _session(mapping=None, user_id=42) -> MappingSession:
    return MappingSession(
        request=ProcessingRequest(
            user_id=user_id, file_name="встреча.mp3", template_id=2,
            llm_provider="openai",
        ),
        transcription_result=TranscriptionResult(transcription="текст"),
        speaker_mapping=dict(mapping or {}),
        meeting_type="general",
        temp_file_path=None,
        cache_key=None,
        task_id=None,
        metrics=ProcessingMetrics(
            file_name="встреча.mp3", user_id=user_id, start_time=datetime.now()
        ),
    )


# ---------------------------------------------------------------------------
# Хранилище: изъятие без оглядки на TTL
# ---------------------------------------------------------------------------


def test_take_regardless_returns_expired_session():
    """Просроченная сессия всё ещё содержит расшифровку — её нужно доработать."""
    store = MappingSessionStore(ttl_seconds=3600)
    key = store.save(42, _session())
    store._timestamps[(42, key)] = datetime.now() - timedelta(hours=2)

    assert store.take_regardless(42, key) is not None


def test_take_regardless_is_atomic():
    store = MappingSessionStore(ttl_seconds=3600)
    store.save(42, _session())

    assert store.take_regardless(42) is not None
    assert store.take_regardless(42) is None


def test_take_regardless_without_session_is_none():
    assert MappingSessionStore().take_regardless(42) is None


def test_peek_still_evicts_expired_for_the_card():
    """Карточка по-прежнему считает просроченную сессию мёртвой."""
    store = MappingSessionStore(ttl_seconds=3600)
    key = store.save(42, _session())
    # Ключ хранилища — пара «пользователь + запись» (критика v11).
    store._timestamps[(42, key)] = datetime.now() - timedelta(hours=2)

    assert store.peek(42) is None


# ---------------------------------------------------------------------------
# Авто-доставка по таймауту
# ---------------------------------------------------------------------------


class _Service:
    """Сервис с перехваченным возобновлением."""

    def __init__(self):
        self.resumed = []

    async def continue_processing_after_mapping_confirmation(
        self, *, session, confirmed_mapping, bot, chat_id
    ):
        self.resumed.append((session, confirmed_mapping, chat_id))
        return SimpleNamespace(protocol_text="# П")


@pytest.mark.asyncio
async def test_timeout_delivers_with_partial_mapping():
    """Имена, введённые до ухода, не теряются — они и едут в протокол."""
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    store.save(42, _session(mapping={"SPEAKER_1": "Иван"}))
    service = _Service()

    await deliver_on_timeout(
        service, store, user_id=42, bot=AsyncMock(), chat_id=7, delay_seconds=0,
    )

    assert len(service.resumed) == 1
    _, mapping, chat_id = service.resumed[0]
    assert mapping == {"SPEAKER_1": "Иван"}
    assert chat_id == 7


@pytest.mark.asyncio
async def test_timeout_is_noop_when_user_already_confirmed():
    """Пользователь успел подтвердить — сессия изъята, второй доставки нет."""
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    store.save(42, _session())
    store.take(42)  # пользователь подтвердил
    service = _Service()

    await deliver_on_timeout(
        service, store, user_id=42, bot=AsyncMock(), chat_id=7, delay_seconds=0,
    )

    assert service.resumed == []


@pytest.mark.asyncio
async def test_timeout_delivers_even_when_ttl_already_passed():
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore(ttl_seconds=3600)
    store.save(42, _session())
    store._timestamps[42] = datetime.now() - timedelta(hours=2)
    service = _Service()

    await deliver_on_timeout(
        service, store, user_id=42, bot=AsyncMock(), chat_id=7, delay_seconds=0,
    )

    assert len(service.resumed) == 1


@pytest.mark.asyncio
async def test_timeout_warns_the_user_before_delivering():
    """Молчаливая доставка выглядит как сбой: сначала объясняем, почему."""
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    store.save(42, _session())
    bot = AsyncMock()

    await deliver_on_timeout(
        _Service(), store, user_id=42, bot=bot, chat_id=7, delay_seconds=0,
    )

    said = " ".join(
        str(call.kwargs.get("text", "")) for call in bot.send_message.call_args_list
    )
    assert "Участник" in said


@pytest.mark.asyncio
async def test_timeout_survives_resume_failure():
    """Сбой возобновления не должен ронять фоновую задачу молча в трейсбек."""
    from src.services.mapping_timeout import deliver_on_timeout

    class Failing(_Service):
        async def continue_processing_after_mapping_confirmation(self, **kwargs):
            raise RuntimeError("генерация упала")

    store = MappingSessionStore()
    store.save(42, _session())

    await deliver_on_timeout(
        Failing(), store, user_id=42, bot=AsyncMock(), chat_id=7, delay_seconds=0,
    )


@pytest.mark.asyncio
async def test_timeout_waits_the_requested_delay():
    """Доставка не должна случиться раньше срока — иначе она украдёт карточку."""
    from src.services.mapping_timeout import deliver_on_timeout

    store = MappingSessionStore()
    store.save(42, _session())
    service = _Service()

    task = asyncio.create_task(deliver_on_timeout(
        service, store, user_id=42, bot=AsyncMock(), chat_id=7, delay_seconds=30,
    ))
    await asyncio.sleep(0)
    assert service.resumed == []
    task.cancel()


def test_auto_deliver_delay_precedes_store_eviction():
    """Таймер обязан сработать раньше, чем ленивое вытеснение убьёт сессию."""
    from src.services.mapping_timeout import auto_deliver_delay_seconds

    store = MappingSessionStore(ttl_seconds=3600)
    assert auto_deliver_delay_seconds(store) < 3600
