"""Порядок спикеров в карточке сопоставления — по появлению (#57 → #59).

Раньше UI четырежды повторял «взять speakers, иначе собрать из segments, затем
ЧИСЛОВАЯ сортировка SPEAKER_N». #59 заменил всё на `diarization.speakers` —
единый порядок ПОЯВЛЕНИЯ спикеров в сегментах. Осознанные следствия смены
(решение дизайн-сессии):

- порядок теперь по появлению, а не по числовому суффиксу;
- квирк «нечисловая метка уходит в конец (999)» исчез — родные метки
  speechmatics (S1/S2) держат порядок появления;
- сортировки in-place больше нет: `diarization.speakers` отдаёт свежий список,
  вход не мутируется.

Проверяем через две публичные функции — `create_mapping_keyboard` (порядок
кнопок) и `build_mapping_card` (порядок строк карточки).
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
# Allow bare `from services import ...` used inside legacy modules transitively
# imported via src/ux/__init__.py.
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.ux.speaker_mapping_ui import build_mapping_card, create_mapping_keyboard  # noqa: E402


def _diar(*speakers):
    """«Диаризация» из сегментов в заданном порядке появления спикеров."""
    return Diarization(
        segments=[Segment(speaker=s, text="реплика") for s in speakers]
    )


def _change_button_speakers(keyboard) -> list:
    """Спикеры в порядке кнопок изменения ('sm_change:<speaker>:<user>')."""
    speakers = []
    for row in keyboard.inline_keyboard:
        for button in row:
            data = button.callback_data or ""
            if data.startswith("sm_change:"):
                speakers.append(data.split(":")[1])
    return speakers


def test_speakers_follow_appearance_order_not_numeric():
    """Порядок — по появлению: SPEAKER_2 раньше SPEAKER_1, если появился первым."""
    diarization = _diar("SPEAKER_2", "SPEAKER_10", "SPEAKER_1")

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    assert _change_button_speakers(keyboard) == ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"]


def test_speakers_are_unique_in_appearance_order():
    """Повторные реплики спикера схлопнуты; порядок — первого появления."""
    diarization = _diar("SPEAKER_3", "SPEAKER_1", "SPEAKER_3", "SPEAKER_1")

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    assert _change_button_speakers(keyboard) == ["SPEAKER_3", "SPEAKER_1"]


def test_native_labels_keep_appearance_order():
    """Родные метки speechmatics (S1/S2) держат порядок появления, не уходят в конец."""
    diarization = _diar("S2", "S1")

    keyboard = create_mapping_keyboard({}, diarization, [], user_id=7)

    assert _change_button_speakers(keyboard) == ["S2", "S1"]


def test_build_mapping_card_orders_speakers_by_appearance():
    """Тот же порядок появления виден и в строках карточки сопоставления.

    По ADR-0005 карточка — семантическое содержимое: проверяем порядок строк
    спикеров, а не экранированный текст.
    """
    diarization = _diar("SPEAKER_2", "SPEAKER_10", "SPEAKER_1")

    card = build_mapping_card({}, diarization, [])

    order = [row.speaker_id for row in card.rows]
    assert order == ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"]


def test_diarization_not_mutated_by_rendering():
    """Отрисовка карточки не мутирует диаризацию: порядок сегментов сохраняется."""
    diarization = _diar("SPEAKER_2", "SPEAKER_10", "SPEAKER_1")

    create_mapping_keyboard({}, diarization, [], user_id=7)

    # Порядок спикеров (по сегментам) не переставлен сортировкой.
    assert diarization.speakers == ["SPEAKER_2", "SPEAKER_10", "SPEAKER_1"]
