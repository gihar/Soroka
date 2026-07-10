"""Цитата спикера показывается один раз (#55).

Спикеры с доставленным фрагментом записи опознаются подписью фрагмента —
карточка сопоставления не дублирует их цитаты. Спикеры без фрагмента
получают текстовую цитату в карточке, как раньше.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.ux.speaker_mapping_ui import format_mapping_message  # noqa: E402

_DIARIZATION = Diarization(segments=[
    Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="цитата первого"),
    Segment(start=6.0, end=9.0, speaker="SPEAKER_2", text="цитата второго"),
])

_SPEAKERS_TEXT = {
    "SPEAKER_1": "цитата первого",
    "SPEAKER_2": "цитата второго",
}

_PARTICIPANTS = [{"name": "Иван Иванов"}]


def test_quotes_rendered_without_fragments():
    """Без фрагментов карточка ведёт себя как раньше: цитаты у всех."""
    text = format_mapping_message(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
    )

    assert "цитата первого" in text
    assert "цитата второго" in text


def test_no_quote_for_speakers_with_fragment():
    """Спикер с фрагментом — без цитаты; спикер без фрагмента — с цитатой."""
    text = format_mapping_message(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
        speakers_with_audio={"SPEAKER_1"},
    )

    assert "цитата первого" not in text
    assert "цитата второго" in text  # несопоставленный без фрагмента — цитата остаётся
    assert "SPEAKER\\_1" in text  # сама строка спикера никуда не девается


def test_no_quote_for_unmapped_speaker_with_fragment():
    """Правило одинаково для несопоставленных спикеров."""
    text = format_mapping_message(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
        speakers_with_audio={"SPEAKER_1", "SPEAKER_2"},
    )

    assert "цитата первого" not in text
    assert "цитата второго" not in text
    assert "SPEAKER\\_2" in text
