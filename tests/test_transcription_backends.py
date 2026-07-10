"""Характеризация адаптеров бэкендов транскрипции (#43).

Эталон поведения — ветки старого transcribe_with_diarization.
Мок — на границе бэкенд-сервисов (groq_client, speechmatics_service, ...).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.diarization import Diarization, Segment
from src.models.processing import TranscriptionResult


@pytest.fixture
def service():
    """TranscriptionService без тяжёлой инициализации."""
    from src.services.transcription_service import TranscriptionService

    svc = TranscriptionService.__new__(TranscriptionService)
    svc.whisper_model = None
    svc.groq_client = None
    return svc


def test_registry_covers_all_six_modes(service):
    from src.services import transcription_backends as tb

    backends = tb.build_backends(service)

    assert set(backends) == {"local", "cloud", "hybrid", "speechmatics", "deepgram", "leopard"}
    assert backends["cloud"] is backends["hybrid"]  # cloud ≡ hybrid: один groq-адаптер
    assert type(backends["local"]).__name__ == "WhisperBackend"


async def test_whisper_backend_transcribes_and_strips(service):
    from src.services import transcription_backends as tb

    service._load_whisper_model = MagicMock()
    service._transcribe_with_progress = AsyncMock(return_value={"text": "  привет мир  "})

    result = await tb.WhisperBackend(service).transcribe("f.mp3", "ru")

    assert isinstance(result, TranscriptionResult)
    assert result.transcription == "привет мир"
    assert result.diarization is None                    # диаризацию применит сервис
    assert result.compression_info["compressed"] is False
    assert tb.WhisperBackend(service).is_available() is True  # всегда доступен


async def test_groq_backend_delegates_and_threads_compression(service, tmp_path):
    from src.services import transcription_backends as tb

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 100)
    compression = {"compressed": True, "original_size_mb": 10, "compressed_size_mb": 2,
                   "compression_ratio": 80, "compression_saved_mb": 8}
    service._preprocess_audio = AsyncMock(return_value=(str(audio), compression))
    service.oom_protection = MagicMock()
    service.oom_protection.can_process_file.return_value = (True, "ok")
    backend = tb.GroqBackend(service)

    assert backend.is_available() is False  # groq_client = None

    service.groq_client = MagicMock()
    service.groq_client.audio.transcriptions.create.return_value = MagicMock(text="текст groq")
    assert backend.is_available() is True

    result = await backend.transcribe(str(audio), "ru")
    assert result.transcription == "текст groq"
    assert result.compression_info == compression


async def test_leopard_backend_delegates_and_checks_key(service, monkeypatch):
    import src.services.transcription_service as ts_module
    from src.services import transcription_backends as tb

    backend = tb.LeopardBackend(service)
    monkeypatch.setattr(ts_module, "LEOPARD_AVAILABLE", True)
    monkeypatch.setattr(tb.settings, "picovoice_access_key", "key")
    assert backend.is_available() is True

    backend._prepare_file = lambda path: path
    monkeypatch.setattr(backend, "_run_leopard_sync", staticmethod(lambda path: "текст leopard"))
    result = await backend.transcribe("f.mp3", "ru")
    assert result.transcription == "текст leopard"

    monkeypatch.setattr(tb.settings, "picovoice_access_key", None)
    assert backend.is_available() is False


def _native_result(text="текст с диаризацией"):
    return TranscriptionResult(
        transcription=text,
        diarization=Diarization(segments=[Segment(speaker="SPEAKER_0", text=text)]),
        compression_info=None,
    )


async def test_speechmatics_backend_returns_native_diarization(service, monkeypatch):
    from src.services import transcription_backends as tb

    compression = {"compressed": True, "original_size_mb": 5, "compressed_size_mb": 1,
                   "compression_ratio": 80, "compression_saved_mb": 4}
    service._preprocess_audio = AsyncMock(return_value=("f.mp3", compression))
    stub = MagicMock()
    stub.is_available.return_value = True
    stub.transcribe_file = AsyncMock(return_value=_native_result())
    monkeypatch.setattr(tb, "speechmatics_service", stub)
    monkeypatch.setattr(tb.settings, "enable_diarization", True)

    backend = tb.SpeechmaticsBackend(service)
    assert backend.is_available() is True

    result = await backend.transcribe("f.mp3", "ru")

    assert isinstance(result.diarization, Diarization)   # родная диаризация внутри
    assert result.diarization.speakers == ["SPEAKER_0"]
    assert result.compression_info == compression        # compression протянут
    assert stub.transcribe_file.call_args.kwargs["enable_diarization"] is True


async def test_deepgram_backend_native_diarization_and_error_passthrough(service, monkeypatch):
    from src.exceptions.processing import DeepgramAPIError
    from src.services import transcription_backends as tb

    service._preprocess_audio = AsyncMock(return_value=("f.mp3", dict()))
    stub = MagicMock()
    stub.is_available.return_value = True
    stub.transcribe_file = AsyncMock(return_value=_native_result("deepgram текст"))
    monkeypatch.setattr(tb, "deepgram_service", stub)

    backend = tb.DeepgramBackend(service)
    result = await backend.transcribe("f.mp3", "ru")
    assert result.transcription == "deepgram текст"
    assert result.diarization is not None

    # типизированная ошибка пролетает наверх — политика fallback живёт в сервисе
    stub.transcribe_file = AsyncMock(side_effect=DeepgramAPIError("боом", "f.mp3", "болванка"))
    with pytest.raises(DeepgramAPIError):
        await backend.transcribe("f.mp3", "ru")
