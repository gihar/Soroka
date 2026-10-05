"""Критика v10: истечение карточки доставляет протокол, а не выбрасывает работу.

Прод: карточка сопоставления включена, сессия живёт в памяти час. Пользователь,
вернувшийся через 61 минуту, получал «❌ Состояние обработки не найдено или
истекло. Пожалуйста, начните обработку заново» — и готовая расшифровка (самая
дорогая часть конвейера) уходила в мусор.

Протокол — продукт. Несовершенный протокол с «Участник N» лучше, чем
отсутствующий: по таймауту обработка доводится до конца с тем сопоставлением,
которое успел ввести пользователь.
"""

from datetime import datetime, timedelta

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


# Авто-доставка по таймауту — поведение паузы на карточке, а не хранилища:
# tests/test_mapping_pause.py (раздел «Истёк срок»).
