"""Цитата спикера показывается один раз (#55).

Спикеры с доставленным фрагментом записи опознаются подписью фрагмента —
карточка сопоставления не дублирует их цитаты. Спикеры без фрагмента
получают текстовую цитату в карточке, как раньше.

По ADR-0005 карточка — семантическое содержимое (MappingCard): проверяем
строки спикеров и их цитаты, а не разметку/экранирование.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.ux.speaker_mapping_ui import build_mapping_card  # noqa: E402

_DIARIZATION = Diarization(segments=[
    Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="цитата первого"),
    Segment(start=6.0, end=9.0, speaker="SPEAKER_2", text="цитата второго"),
])

_SPEAKERS_TEXT = {
    "SPEAKER_1": "цитата первого",
    "SPEAKER_2": "цитата второго",
}

_PARTICIPANTS = [{"name": "Иван Иванов"}]


def _rows_by_speaker(card):
    return {row.speaker_id: row for row in card.rows}


def test_quotes_rendered_without_fragments():
    """Без фрагментов карточка ведёт себя как раньше: цитаты у всех."""
    card = build_mapping_card(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
    )

    rows = _rows_by_speaker(card)
    assert rows["SPEAKER_1"].quote == "цитата первого"
    assert rows["SPEAKER_2"].quote == "цитата второго"


def test_no_quote_for_speakers_with_fragment():
    """Спикер с фрагментом — без цитаты; спикер без фрагмента — с цитатой."""
    card = build_mapping_card(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
        speakers_with_audio={"SPEAKER_1"},
    )

    rows = _rows_by_speaker(card)
    assert rows["SPEAKER_1"].quote is None  # фрагмент доставлен — без цитаты
    assert rows["SPEAKER_2"].quote == "цитата второго"  # без фрагмента — цитата остаётся
    assert "SPEAKER_1" in rows  # сама строка спикера никуда не девается


def test_no_quote_for_unmapped_speaker_with_fragment():
    """Правило одинаково для несопоставленных спикеров."""
    card = build_mapping_card(
        {"SPEAKER_1": "Иван Иванов"},
        _DIARIZATION,
        _PARTICIPANTS,
        speakers_text=_SPEAKERS_TEXT,
        speakers_with_audio={"SPEAKER_1", "SPEAKER_2"},
    )

    rows = _rows_by_speaker(card)
    assert rows["SPEAKER_1"].quote is None
    assert rows["SPEAKER_2"].quote is None
    assert rows["SPEAKER_2"].display_name is None  # несопоставлен
