"""Контракт wire-формата фабрик Карточки сопоставления.

Кнопки уже отправленных карточек несут callback-строки старого формата
(``sm_select:SPEAKER_1:none:42`` и т.п.). Типизированные фабрики CallbackData
обязаны паковать байт-в-байт эти же строки и распаковывать сгенерированные
старым кодом — иначе после деплоя старые кнопки перестанут работать.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402

from src.ux.speaker_mapping_callback_data import (  # noqa: E402
    SmCancel,
    SmChange,
    SmConfirm,
    SmCustom,
    SmSelect,
    SmSkip,
)


def test_sm_change_wire_format_roundtrip():
    """``sm_change:{speaker_id}:{user_id}`` пакуется и распаковывается без сдвига."""
    assert (
        SmChange(speaker_id="SPEAKER_2", user_id=42).pack()
        == "sm_change:SPEAKER_2:42"
    )
    data = SmChange.unpack("sm_change:SPEAKER_2:42")
    assert data.speaker_id == "SPEAKER_2"
    assert data.user_id == 42


def test_sm_select_packs_none_wire_format():
    """«Оставить без имени» пакуется как ``sm_select:{speaker}:none:{user}``."""
    packed = SmSelect(
        speaker_id="SPEAKER_1", participant_idx="none", user_id=42
    ).pack()
    assert packed == "sm_select:SPEAKER_1:none:42"


def test_sm_select_unpacks_none_from_old_code():
    """Строка старого кода с «none» распаковывается, «none» сохраняется как есть."""
    data = SmSelect.unpack("sm_select:SPEAKER_1:none:42")
    assert data.speaker_id == "SPEAKER_1"
    assert data.participant_idx == "none"
    assert data.user_id == 42


def test_sm_select_wire_format_roundtrip_with_index():
    """Числовой индекс участника проходит round-trip как строка."""
    assert (
        SmSelect(speaker_id="SPEAKER_1", participant_idx="3", user_id=42).pack()
        == "sm_select:SPEAKER_1:3:42"
    )
    data = SmSelect.unpack("sm_select:SPEAKER_1:3:42")
    assert data.participant_idx == "3"


def test_sm_custom_wire_format_roundtrip():
    """``sm_custom:{speaker_id}:{user_id}`` — переход к ручному вводу имени."""
    assert (
        SmCustom(speaker_id="SPEAKER_1", user_id=42).pack()
        == "sm_custom:SPEAKER_1:42"
    )
    data = SmCustom.unpack("sm_custom:SPEAKER_1:42")
    assert data.speaker_id == "SPEAKER_1"
    assert data.user_id == 42


def test_sm_cancel_wire_format_roundtrip():
    """``sm_cancel:{user_id}`` — возврат к основному виду карточки."""
    assert SmCancel(user_id=42).pack() == "sm_cancel:42"
    assert SmCancel.unpack("sm_cancel:42").user_id == 42


def test_sm_confirm_wire_format_roundtrip():
    """``sm_confirm:{user_id}`` — подтверждение и продолжение обработки."""
    assert SmConfirm(user_id=42).pack() == "sm_confirm:42"
    assert SmConfirm.unpack("sm_confirm:42").user_id == 42


def test_sm_skip_wire_format_roundtrip():
    """``sm_skip:{user_id}`` — пропуск сопоставления."""
    assert SmSkip(user_id=42).pack() == "sm_skip:42"
    assert SmSkip.unpack("sm_skip:42").user_id == 42
