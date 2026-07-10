"""Единый фолбэк «форматированная или сырая» — TranscriptionResult.best_transcript (#59).

До #59 выбор «форматированная транскрипция из диаризации либо сырая» жил в
четырёх местах на голых dict-ах. #59 свёл его в одно свойство. Оба плеча:
есть диаризация с непустым форматом → её formatted_transcript; иначе (диаризации
нет либо формат пуст — сегменты без текста) → сырая transcription.
"""

from src.models.diarization import Diarization, Segment
from src.models.processing import TranscriptionResult


def test_uses_diarization_formatted_when_present():
    """Есть диаризация с текстом → best_transcript == её форматированная транскрипция."""
    diarization = Diarization(segments=[
        Segment(speaker="SPEAKER_1", text="привет"),
        Segment(speaker="SPEAKER_2", text="здравствуй"),
    ])
    result = TranscriptionResult(transcription="сырой текст", diarization=diarization)

    assert result.best_transcript == diarization.formatted_transcript
    assert result.best_transcript == "SPEAKER_1: привет\n\nSPEAKER_2: здравствуй"


def test_falls_back_to_raw_when_no_diarization():
    """Диаризации нет → best_transcript == сырая транскрипция."""
    result = TranscriptionResult(transcription="сырой текст", diarization=None)

    assert result.best_transcript == "сырой текст"


def test_falls_back_to_raw_when_formatted_empty():
    """Диаризация есть, но формат пуст (сегменты без текста) → сырая транскрипция."""
    diarization = Diarization(segments=[
        Segment(speaker="SPEAKER_1", text=""),
        Segment(speaker="SPEAKER_2", text=""),
    ])
    result = TranscriptionResult(transcription="сырой текст", diarization=diarization)

    assert diarization.formatted_transcript == ""  # предпосылка плеча
    assert result.best_transcript == "сырой текст"
