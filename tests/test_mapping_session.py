"""Сессия сопоставления (#50): типизированная, с атомарным take.

Живые объекты вместо dict-ов со строковыми ключами; двойной take → None;
ленивый TTL.
"""
from datetime import timedelta

import pytest

from src.models.processing import ProcessingRequest, TranscriptionResult


def _session():
    from src.services.mapping_session import MappingSession
    from datetime import datetime

    from src.performance.metrics import ProcessingMetrics

    request = ProcessingRequest(
        user_id=42, file_name="встреча.mp3", template_id=2, llm_provider="openai",
    )
    transcription = TranscriptionResult(
        transcription="текст", diarization={"speakers": ["SPEAKER_0"]},
        speakers_text={"SPEAKER_0": "..."}, formatted_transcript="SPEAKER_0: текст",
        speakers_summary="1 спикер", compression_info=None,
    )
    return MappingSession(
        request=request,
        transcription_result=transcription,
        speaker_mapping={"SPEAKER_0": "Анна"},
        meeting_type="status",
        temp_file_path="/tmp/f.mp3",
        cache_key="processing_result:abc",
        task_id="t-1",
        metrics=ProcessingMetrics(file_name="встреча.mp3", user_id=42, start_time=datetime.now()),
    )


@pytest.fixture
def store():
    from src.services.mapping_session import MappingSessionStore
    return MappingSessionStore(ttl_seconds=3600)


def test_take_returns_live_objects_and_pops(store):
    session = _session()
    store.save(42, session)

    taken = store.take(42)

    assert taken is session                      # тот же живой объект, без регидрации
    assert taken.request.file_name == "встреча.mp3"
    assert taken.transcription_result.transcription == "текст"
    assert store.take(42) is None                # двойной тап «Подтвердить» → None


def test_peek_reads_without_removing(store):
    store.save(42, _session())

    assert store.peek(42) is not None
    assert store.peek(42) is not None            # peek не изымает
    assert store.take(42) is not None


def test_update_mapping_mutates_session(store):
    store.save(42, _session())

    ok = store.update_mapping(42, {"SPEAKER_0": "Борис"})

    assert ok is True
    assert store.peek(42).speaker_mapping == {"SPEAKER_0": "Борис"}
    assert store.update_mapping(99, {}) is False  # нет сессии — False


def test_expired_session_is_not_returned(store, monkeypatch):
    store.save(42, _session())

    # состариваем запись за TTL
    store._timestamps[42] -= timedelta(seconds=3601)

    assert store.peek(42) is None
    assert store.take(42) is None
