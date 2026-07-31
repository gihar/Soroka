"""Критика v11: последний проход по мелочам, которые видит каждый.

Четыре формата длительности жили в одном прогоне, причём два — на одном
экране: «✅ Анализ · 6м 14с» рядом с «Прошло: 380с». Маркер выбора ✅ пережил
чистку v10 в одном админском экране. Корона у организатора несла смысл одна,
без слова. У меню настроек не было выхода, хотя у соседнего админского был.
"""

from pathlib import Path

import pytest

from src.utils.duration import format_duration

_SRC = Path("src")


def _source(*parts) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Один формат длительности
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds,expected", [
    (0, "0 с"),
    (7, "7 с"),
    (59, "59 с"),
    (60, "1 мин"),
    (312, "5 мин 12 с"),
    (374, "6 мин 14 с"),
    (600, "10 мин"),
    (3600, "1 ч"),
    (3900, "1 ч 5 мин"),
    (7380, "2 ч 3 мин"),
])
def test_duration_has_one_shape(seconds, expected):
    assert format_duration(seconds) == expected


def test_duration_rounds_instead_of_truncating():
    assert format_duration(11.6) == "12 с"


def test_duration_survives_nonsense():
    assert format_duration(-5) == "0 с"


def test_progress_tracker_uses_the_shared_formatter():
    """Проверяем пользовательский текст, а не строки логов."""
    import inspect

    from src.ux.progress_tracker import ProgressTracker

    for method in (
        ProgressTracker._format_progress_text, ProgressTracker._stage_duration_text
    ):
        source = inspect.getsource(method)
        assert ":.0f}с" not in source, method.__name__
        assert "{minutes}м" not in source, method.__name__
    assert "format_duration" in _source("ux", "progress_tracker.py")


def test_queue_tracker_uses_the_shared_formatter():
    source = _source("ux", "queue_tracker.py")
    assert "format_duration" in source
    assert 'f"~{hours}ч {minutes}мин"' not in source


def test_message_builder_uses_the_shared_formatter():
    from src.ux.message_builder import MessageBuilder

    assert MessageBuilder._format_duration(312) == "5 мин 12 с"


def test_stage_suffix_reads_like_the_summary():
    """Обе величины стоят на одном экране — они обязаны выглядеть одинаково."""
    from src.ux.progress_tracker import ProgressTracker

    stage = type("S", (), {"started_at": None, "completed_at": None})()
    assert ProgressTracker._stage_duration_text(stage) == ""


# ---------------------------------------------------------------------------
# Один глиф — одно значение
# ---------------------------------------------------------------------------


def test_transcription_mode_uses_the_selection_mark():
    """✅ значит «сделано»; «выбрано» — это ✓ (канон v10)."""
    from src.ux.speaker_mapping_ui import SELECTED_MARK

    source = _source("ux", "admin_views.py")
    assert 'prefix = "✅ "' not in source
    assert "SELECTED_MARK" in source
    assert SELECTED_MARK == "✓"


@pytest.mark.parametrize("glyph", ["📋", "🕐", "👥", "👑"])
def test_meeting_info_has_no_decorative_glyphs(glyph):
    assert glyph not in _source("services", "meeting_info_service.py")


def test_organizer_is_named_by_a_word():
    """Корона несла смысл одна — PRODUCT.md это запрещает."""
    source = _source("services", "meeting_info_service.py")
    assert "организатор" in source.lower()


def test_participants_list_has_no_leftover_glyph():
    assert "📋" not in _source("services", "participants_service.py")


def test_please_is_gone():
    """«Пожалуйста» встречалось ровно один раз на всей поверхности."""
    for module in ("handlers/callbacks/speaker_mapping_callbacks.py",):
        assert "Пожалуйста" not in _source(*module.split("/"))


# ---------------------------------------------------------------------------
# Выход и формулировки
# ---------------------------------------------------------------------------


def test_settings_menu_has_a_way_out():
    from src.ux.quick_actions import QuickActionsUI

    datas = {
        b.callback_data
        for row in QuickActionsUI.create_settings_menu().inline_keyboard
        for b in row
    }
    assert "settings_close" in datas


def test_cancel_button_has_one_wording():
    """«Отменить» и «Отмена» — одно действие, названное двумя словами."""
    for path in (
        ("handlers", "template_handlers.py"),
        ("ux", "queue_tracker.py"),
    ):
        source = _source(*path)
        assert '"Отменить"' not in source, path


def test_cancel_task_button_still_says_what_it_cancels():
    from src.ux.queue_tracker import QueuePositionTracker

    tracker = QueuePositionTracker(object(), 1, "t-1")
    label = tracker.create_cancel_button().inline_keyboard[0][0].text
    assert "задач" in label.lower()


def test_no_untranslated_jargon_in_template_descriptions():
    assert "code review" not in _source("services", "template_library.py")


# ---------------------------------------------------------------------------
# Длина имени участника
# ---------------------------------------------------------------------------


def test_absurdly_long_name_is_refused():
    from src.services.participants_service import participants_service

    long_name = "И" * 300
    assert participants_service.parse_participants_text(long_name) == []


def test_normal_name_still_passes():
    from src.services.participants_service import participants_service

    parsed = participants_service.parse_participants_text("Иван Петров, руководитель")
    assert parsed and parsed[0]["name"] == "Иван Петров"


def test_name_limit_is_a_named_constant():
    from src.services.participants_service import MAX_NAME_LENGTH

    assert 50 <= MAX_NAME_LENGTH <= 200
