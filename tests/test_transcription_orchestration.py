"""Характеризация оркестрации transcribe_with_diarization (#44).

Мок — на границе адаптеров (реестр _backends); поведение веток старого
метода зафиксировано как канон: роутинг, единый fallback, диаризация-один-раз.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.processing import TranscriptionResult


def _partial(text="текст", diarization=None, compression=None):
    return TranscriptionResult(
        transcription=text,
        diarization=diarization,
        speakers_text={},
        formatted_transcript="",
        speakers_summary="",
        compression_info=compression,
    )


class FakeBackend:
    def __init__(self, name, result=None, error=None, available=True):
        self.name = name
        self._result = result
        self._error = error
        self._available = available
        self.calls = 0

    def is_available(self):
        return self._available

    async def transcribe(self, file_path, language):
        self.calls += 1
        if self._error:
            raise self._error
        return self._result


@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "встреча.mp3"
    f.write_bytes(b"fake audio")
    return str(f)


@pytest.fixture
def service():
    from src.services.transcription_service import TranscriptionService

    svc = TranscriptionService.__new__(TranscriptionService)
    svc.whisper_model = None
    svc.groq_client = None
    svc.oom_protection = MagicMock()
    svc.oom_protection.can_process_file.return_value = (True, "ok")
    svc._check_ffmpeg = lambda: True  # environment-guard, не поведение под тестом
    return svc


def _wire(service, mode, backends, monkeypatch, diarization_enabled=False):
    import src.services.transcription_service as ts_module

    service._backends = backends
    monkeypatch.setattr(ts_module.settings, "transcription_mode", mode)
    monkeypatch.setattr(ts_module.settings, "enable_diarization", diarization_enabled)


async def test_mode_routes_to_its_backend(service, audio_file, monkeypatch):
    deepgram = FakeBackend("deepgram", result=_partial("из deepgram"))
    whisper = FakeBackend("whisper", result=_partial("из whisper"))
    _wire(service, "deepgram", {"deepgram": deepgram, "local": whisper}, monkeypatch)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.transcription == "из deepgram"
    assert deepgram.calls == 1
    assert whisper.calls == 0
    assert result.formatted_transcript == "из deepgram"  # дефолт без диаризации
    assert result.compression_info["compressed"] is False  # заполнен дефолтом


async def test_unavailable_backend_falls_back_to_whisper(service, audio_file, monkeypatch):
    deepgram = FakeBackend("deepgram", result=_partial("не должно"), available=False)
    whisper = FakeBackend("whisper", result=_partial("из whisper"))
    _wire(service, "deepgram", {"deepgram": deepgram, "local": whisper}, monkeypatch)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.transcription == "из whisper"
    assert deepgram.calls == 0


async def test_typed_backend_error_falls_back_to_whisper(service, audio_file, monkeypatch):
    from src.exceptions.processing import DeepgramAPIError

    deepgram = FakeBackend("deepgram", error=DeepgramAPIError("боом", "f", "d"))
    whisper = FakeBackend("whisper", result=_partial("из whisper"))
    _wire(service, "deepgram", {"deepgram": deepgram, "local": whisper}, monkeypatch)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.transcription == "из whisper"
    assert deepgram.calls == 1


async def test_leopard_now_gets_fallback_too(service, audio_file, monkeypatch):
    """Нормализация: leopard раньше падал без отката — теперь единая политика."""
    from src.exceptions.processing import TranscriptionError

    leopard = FakeBackend("leopard", error=TranscriptionError("leopard сломался", "f"))
    whisper = FakeBackend("whisper", result=_partial("из whisper"))
    _wire(service, "leopard", {"leopard": leopard, "local": whisper}, monkeypatch)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.transcription == "из whisper"


async def test_whisper_failure_raises_without_self_fallback(service, audio_file, monkeypatch):
    from src.exceptions.processing import TranscriptionError

    whisper = FakeBackend("whisper", error=TranscriptionError("модель не загрузилась", "f"))
    _wire(service, "local", {"local": whisper}, monkeypatch)

    with pytest.raises(TranscriptionError):
        await service.transcribe_with_diarization(audio_file, "ru")
    assert whisper.calls == 1


async def test_local_diarization_applied_once_when_backend_lacks_it(service, audio_file, monkeypatch):
    import src.services.transcription_service as ts_module

    whisper = FakeBackend("whisper", result=_partial("текст без спикеров"))
    _wire(service, "local", {"local": whisper}, monkeypatch, diarization_enabled=True)

    d = MagicMock()
    d.to_dict.return_value = {"segments": [1]}
    d.get_speakers_text.return_value = {"SPEAKER_0": "..."}
    d.get_formatted_transcript.return_value = "SPEAKER_0: текст без спикеров"
    d.speakers = ["SPEAKER_0"]
    stub = MagicMock()
    stub.diarize_file = AsyncMock(return_value=d)
    stub.get_speakers_summary.return_value = "1 спикер"
    monkeypatch.setattr(ts_module, "diarization_service", stub)
    monkeypatch.setattr(ts_module, "DIARIZATION_AVAILABLE", True)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.diarization == {"segments": [1]}
    assert result.formatted_transcript == "SPEAKER_0: текст без спикеров"
    assert stub.diarize_file.await_count == 1  # ровно один раз


async def test_native_diarization_not_redone(service, audio_file, monkeypatch):
    """Нормализация: у Deepgram/Speechmatics своя диаризация — локальная не гоняется."""
    import src.services.transcription_service as ts_module

    deepgram = FakeBackend("deepgram", result=_partial(
        "текст", diarization={"segments": [2]},
    ))
    _wire(service, "deepgram", {"deepgram": deepgram, "local": FakeBackend("whisper")},
          monkeypatch, diarization_enabled=True)

    stub = MagicMock()
    stub.diarize_file = AsyncMock()
    monkeypatch.setattr(ts_module, "diarization_service", stub)
    monkeypatch.setattr(ts_module, "DIARIZATION_AVAILABLE", True)

    result = await service.transcribe_with_diarization(audio_file, "ru")

    assert result.diarization == {"segments": [2]}
    stub.diarize_file.assert_not_awaited()


async def test_oom_rejection_raises(service, audio_file, monkeypatch):
    from src.exceptions.processing import TranscriptionError

    service.oom_protection.can_process_file.return_value = (False, "мало памяти")
    _wire(service, "local", {"local": FakeBackend("whisper")}, monkeypatch)

    with pytest.raises(TranscriptionError):
        await service.transcribe_with_diarization(audio_file, "ru")
