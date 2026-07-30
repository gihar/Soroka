"""«ffmpeg не найден» — только когда ffmpeg действительно нет (#прод-29.07).

29 июля Deepgram отверг битый файл («corrupt or unsupported data»), откат на
локальный Whisper тоже не смог его декодировать, и обработчик по подстроке
"ffmpeg" в тексте ошибки переписал всё в «ffmpeg не найден. Установите ffmpeg».
ffmpeg при этом лежал на месте — /usr/bin/ffmpeg. Диагностика уводила в лес:
сообщение обвиняло сервер там, где был виноват файл.

Канон: подменять причину можно только подтвердив её через shutil.which.
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.exceptions import TranscriptionError
from src.services.transcription_service import TranscriptionService


@pytest.fixture
def service():
    return TranscriptionService()


def _decode_failure():
    return RuntimeError(
        "Failed to load audio: ffmpeg version 4.4.2 ... "
        "Invalid data found when processing input"
    )


@pytest.mark.asyncio
async def test_decode_failure_is_not_blamed_on_missing_ffmpeg(service, tmp_path):
    """ffmpeg на месте — значит виноват файл, а не отсутствие бинаря."""
    audio = tmp_path / "broken.m4a"
    audio.write_bytes(b"not really audio")

    with patch.object(service.oom_protection, "can_process_file", return_value=(True, "OK")), \
         patch.object(service, "_check_ffmpeg", return_value=True), \
         patch.object(service, "_run_with_fallback", AsyncMock(side_effect=_decode_failure())):
        with pytest.raises(TranscriptionError) as excinfo:
            await service.transcribe_with_diarization(str(audio))

    message = str(excinfo.value)
    assert "Установите ffmpeg" not in message
    assert "не найден" not in message


@pytest.mark.asyncio
async def test_decode_failure_names_the_real_cause(service, tmp_path):
    audio = tmp_path / "broken.m4a"
    audio.write_bytes(b"not really audio")

    with patch.object(service.oom_protection, "can_process_file", return_value=(True, "OK")), \
         patch.object(service, "_check_ffmpeg", return_value=True), \
         patch.object(service, "_run_with_fallback", AsyncMock(side_effect=_decode_failure())):
        with pytest.raises(TranscriptionError) as excinfo:
            await service.transcribe_with_diarization(str(audio))

    message = str(excinfo.value).lower()
    assert "декодир" in message or "прочитать" in message or "поврежд" in message


@pytest.mark.asyncio
async def test_missing_ffmpeg_still_reported_when_truly_absent(service, tmp_path):
    """Бинаря действительно нет — прежнее сообщение остаётся верным."""
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"payload")

    with patch.object(service.oom_protection, "can_process_file", return_value=(True, "OK")), \
         patch.object(service, "_check_ffmpeg", return_value=False), \
         patch.object(service, "_run_with_fallback", AsyncMock(side_effect=_decode_failure())):
        with pytest.raises(TranscriptionError) as excinfo:
            await service.transcribe_with_diarization(str(audio))

    assert "ffmpeg" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_unrelated_error_is_passed_through(service, tmp_path):
    """Ошибка без ffmpeg в тексте не должна ни во что переписываться."""
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"payload")

    with patch.object(service.oom_protection, "can_process_file", return_value=(True, "OK")), \
         patch.object(service, "_check_ffmpeg", return_value=True), \
         patch.object(
             service,
             "_run_with_fallback",
             AsyncMock(side_effect=RuntimeError("Deepgram вернул 500")),
         ):
        with pytest.raises(TranscriptionError) as excinfo:
            await service.transcribe_with_diarization(str(audio))

    assert "Deepgram вернул 500" in str(excinfo.value)
