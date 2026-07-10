"""Характеризация извлечения списка спикеров в карточке сопоставления (#57).

Паттерн «взять diarization_data['speakers'], иначе собрать из segments, затем
числовая сортировка» повторяется в UI четырежды. Закрепляем его через две
публичные функции — `create_mapping_keyboard` (порядок кнопок, без экранирования)
и `format_mapping_message` (порядок в тексте) — чтобы типизация «Диаризации»
(#58/#59) не сломала ни fallback, ни порядок.

Замеченный при разведке квирк закреплён как «текущее поведение»: числовая
сортировка идёт in-place и МУТИРУЕТ переданный список speakers.
"""

import os
import re
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))

from src.ux.speaker_mapping_ui import create_mapping_keyboard, format_mapping_message  # noqa: E402


def _change_button_speakers(keyboard) -> list:
    """Спикеры в порядке кнопок изменения ('sm_change:<speaker>:<user>')."""
    speakers = []
    for row in keyboard.inline_keyboard:
        for button in row:
            data = button.callback_data or ""
            if data.startswith("sm_change:"):
                speakers.append(data.split(":")[1])
    return speakers


def test_speakers_sorted_numerically_not_lexicographically():
    """SPEAKER_10 идёт ПОСЛЕ SPEAKER_2 — сортировка по числу, не по строке."""
    diarization = {"speakers": ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"], "segments": []}

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    assert _change_button_speakers(keyboard) == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_10"]


def test_speakers_derived_from_segments_when_list_absent():
    """Нет ключа 'speakers' → спикеры собираются из segments (уникально, без None)."""
    diarization = {
        "segments": [
            {"speaker": "SPEAKER_3", "text": "c"},
            {"speaker": "SPEAKER_1", "text": "a"},
            {"speaker": "SPEAKER_3", "text": "c-again"},
            {"speaker": None, "text": "пропустить"},
        ]
    }

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    # Дубликат SPEAKER_3 схлопнут, None отброшен, порядок — числовой.
    assert _change_button_speakers(keyboard) == ["SPEAKER_1", "SPEAKER_3"]


def test_non_numeric_speaker_suffix_sorts_last():
    """Метка без числового суффикса (SPEAKER_UNKNOWN) уходит в конец (ключ 999)."""
    diarization = {
        "speakers": ["SPEAKER_2", "SPEAKER_UNKNOWN", "SPEAKER_1"],
        "segments": [],
    }

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    assert _change_button_speakers(keyboard) == [
        "SPEAKER_1", "SPEAKER_2", "SPEAKER_UNKNOWN",
    ]


def test_format_mapping_message_orders_speakers_numerically():
    """Тот же числовой порядок виден и в тексте карточки сопоставления."""
    diarization = {"speakers": ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"], "segments": []}

    text = format_mapping_message({}, diarization, [])

    # В MarkdownV2 подчёркивание экранировано: SPEAKER\_N.
    order = re.findall(r"SPEAKER\\_\d+", text)
    assert order == ["SPEAKER\\_1", "SPEAKER\\_2", "SPEAKER\\_10"]


def test_speakers_list_is_sorted_in_place():
    """характеризация: текущее поведение — сортировка мутирует переданный список."""
    speakers = ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"]
    diarization = {"speakers": speakers, "segments": []}

    create_mapping_keyboard({}, diarization, [], user_id=7)

    # Тот же объект списка отсортирован на месте — вход изменён вызовом.
    assert speakers == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_10"]
