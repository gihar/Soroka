"""Критика v10: карточку сопоставления можно выключить в /settings.

ADR-0002 сознательно показывает карточку при любом числе спикеров — покрытие
именования важнее мгновенности. Но у пользователя, который проводит пять встреч
в неделю и каждый раз жмёт «Пропустить», не было способа сказать это один раз.
Выключатель не отменяет решение ADR, а даёт из него выход.

Настройка пользователя перекрывает глобальный флаг; ``None`` (никогда не
трогали) означает «как решил администратор».
"""

from types import SimpleNamespace

from src.services.mapping_preference import should_confirm_mapping


def _user(**over):
    base = dict(speaker_mapping_enabled=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_untouched_preference_follows_global_default_on():
    assert should_confirm_mapping(_user(), global_default=True) is True


def test_untouched_preference_follows_global_default_off():
    assert should_confirm_mapping(_user(), global_default=False) is False


def test_user_can_turn_the_card_off_against_global_default():
    assert should_confirm_mapping(
        _user(speaker_mapping_enabled=False), global_default=True
    ) is False


def test_user_can_turn_the_card_on_against_global_default():
    assert should_confirm_mapping(
        _user(speaker_mapping_enabled=True), global_default=False
    ) is True


def test_sqlite_integer_flags_are_understood():
    """SQLite отдаёт 0/1, а не bool — настройка не должна ломаться об это."""
    assert should_confirm_mapping(_user(speaker_mapping_enabled=0), global_default=True) is False
    assert should_confirm_mapping(_user(speaker_mapping_enabled=1), global_default=False) is True


def test_missing_user_falls_back_to_global_default():
    """Пользователя не нашли — обработка не должна из-за этого менять поведение."""
    assert should_confirm_mapping(None, global_default=True) is True
    assert should_confirm_mapping(None, global_default=False) is False


def test_user_without_the_field_falls_back_to_global_default():
    """Старая запись без колонки — не повод падать."""
    assert should_confirm_mapping(SimpleNamespace(), global_default=True) is True
