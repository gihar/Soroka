"""TranscriptionService не должен переживать свою задачу (#прод-утечка).

Сквозной регресс на инцидент 2026-07-30: сервис создаётся на каждую задачу, и
если хоть что-то глобальное держит на него ссылку, вместе с ним в RAM остаётся
загруженная модель Whisper. За 22 задачи прод набрал 2 ГБ и встал на 91%.
"""
import gc
import weakref

import pytest

from src.performance.oom_protection import get_oom_protection
from src.services.transcription_service import TranscriptionService


@pytest.fixture(autouse=True)
def clean_registry():
    """Реестр синглтона не должен протекать между тестами."""
    registry = get_oom_protection().cleanup_callbacks
    before = registry.callbacks()
    yield
    for callback in registry.callbacks():
        if callback not in before:
            registry.remove(callback)


def test_service_is_collected_after_use():
    service = TranscriptionService()
    ref = weakref.ref(service)

    del service
    gc.collect()

    assert ref() is None, "TranscriptionService пережил задачу — утечка вернулась"


def test_whisper_model_is_released_with_service():
    """Модель — самый тяжёлый груз сервиса; она обязана уходить вместе с ним."""

    class FakeWhisperModel:
        pass

    service = TranscriptionService()
    service.whisper_model = FakeWhisperModel()
    model_ref = weakref.ref(service.whisper_model)

    del service
    gc.collect()

    assert model_ref() is None, "Модель Whisper осталась в памяти после сервиса"


def test_singleton_registry_does_not_grow_across_tasks():
    protection = get_oom_protection()
    baseline = len(protection.cleanup_callbacks)

    for _ in range(20):
        TranscriptionService()

    gc.collect()

    assert len(protection.cleanup_callbacks) == baseline


def test_live_service_still_receives_aggressive_cleanup():
    """Слабая ссылка не должна отключить саму защиту у живого сервиса."""
    service = TranscriptionService()
    service.whisper_model = object()

    get_oom_protection()._aggressive_cleanup()

    assert service.whisper_model is None
