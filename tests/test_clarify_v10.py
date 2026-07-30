"""Критика v10: интерфейс перестаёт обещать то, чего нет.

Обещание, которого продукт не держит, дороже отсутствующей функции: новичок
идёт весь путь «Настроить» ради выбора модели и не находит его, а тот, кто
сохранил список участников, теряет его именно в «Быстрой обработке», которая
этот список ему обещала.
"""

import ast
import inspect
from pathlib import Path

import pytest

from src.ux.message_builder import MessageBuilder
from src.ux.quick_actions import QuickActionsUI

_SRC = Path(__file__).resolve().parent.parent / "src"


def _user_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    logged: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            owner = getattr(getattr(node.func, "value", None), "id", "")
            if owner in {"logger", "logging"}:
                for arg in ast.walk(node):
                    logged.add(id(arg))
    docstrings = {
        id(n.body[0].value) for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
        and n.body and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in logged and id(n) not in docstrings
    ]


# ---------------------------------------------------------------------------
# Выбор модели: обещание удалено (модель админская, llm_provider захардкожен)
# ---------------------------------------------------------------------------


def test_help_does_not_promise_model_choice():
    assert "модель" not in MessageBuilder.help_message().lower()


def test_record_menu_does_not_promise_model_choice():
    text, _ = QuickActionsUI.create_record_actions_menu()
    assert "модель" not in text.lower()


# ---------------------------------------------------------------------------
# Лимиты: ссылки принимают кратно больше, чем файл в Telegram
# ---------------------------------------------------------------------------


def test_help_distinguishes_file_and_link_limits():
    text = MessageBuilder.help_message()
    assert "20 МБ" in text
    # 2 ГБ по ссылке — иначе «до 20 МБ» читается как общий потолок.
    assert "ГБ" in text


def test_help_mentions_every_delivery_format():
    text = MessageBuilder.help_message().lower()
    for fmt in ("pdf", "word"):
        assert fmt in text, f"формат {fmt} не упомянут в справке"


# ---------------------------------------------------------------------------
# «Быстрая обработка» держит обещание про сохранённые настройки
# ---------------------------------------------------------------------------


def test_quick_path_does_not_discard_saved_participants():
    """participants_list=None выбрасывал сохранённый ростер молча."""
    from src.handlers.callbacks import processing_callbacks

    source = inspect.getsource(processing_callbacks)
    assert "participants_list=None" not in source


# ---------------------------------------------------------------------------
# Машинные метки и несуществующие глифы
# ---------------------------------------------------------------------------


def test_speaker_prompt_shows_human_label():
    """«Здесь ждём одно имя — для SPEAKER_1» — машинный токен в русской фразе."""
    from src.handlers.callbacks import speaker_mapping_callbacks

    assert "SPEAKER" not in "".join(
        _user_strings(_SRC / "handlers" / "callbacks" / "speaker_mapping_callbacks.py")
    )
    assert hasattr(speaker_mapping_callbacks, "receive_speaker_name")


def test_no_text_points_at_a_glyph_that_no_button_carries():
    """Текст звал нажать «◀️ Назад», а кнопка называлась «⬅️ Назад»."""
    strings = _user_strings(
        _SRC / "handlers" / "callbacks" / "speaker_mapping_callbacks.py"
    )
    assert not [s for s in strings if "◀" in s]


# ---------------------------------------------------------------------------
# Ничего пустого: «Не указана» под собственным предупреждением
# ---------------------------------------------------------------------------


def test_missing_topic_is_not_shown_as_fake_data():
    from src.services.participants_service import participants_service
    from src.models.meeting_info import MeetingInfo

    info = MeetingInfo(topic="Не указана", participants=[])
    shown = participants_service.format_meeting_info_for_display(info)
    assert "Не указана" not in shown


def test_present_topic_is_still_shown():
    from src.services.participants_service import participants_service
    from src.models.meeting_info import MeetingInfo

    info = MeetingInfo(topic="Смета проекта", participants=[])
    assert "Смета проекта" in participants_service.format_meeting_info_for_display(info)


# ---------------------------------------------------------------------------
# Тон и язык
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [
    "handlers/message_handlers.py",
    "handlers/callbacks/template_callbacks.py",
    "handlers/template_handlers.py",
])
def test_no_exclamation_marks_left(module):
    """«Нейтральный, надёжный, лаконичный» — последние следы SMM-тона."""
    offenders = [s for s in _user_strings(_SRC / module) if "!" in s]
    assert offenders == []


def test_templates_help_fits_one_readable_bubble():
    """1308 символов — вдвое длиннее следующего сообщения продукта."""
    text = MessageBuilder.templates_help_message()
    assert len(text) < 900, f"справка снова разрослась: {len(text)}"


def test_templates_help_keeps_its_reference_value():
    """Сокращать нужно воду, а не справочник переменных."""
    text = MessageBuilder.templates_help_message()
    for essential in ("{{ meeting_title }}", "{{ decisions }}", "{% if", "<pre>"):
        assert essential in text, f"из справки пропало важное: {essential}"


def test_api_leak_is_translated():
    from src.services import error_presentation

    text = error_presentation.resume_failure_message("connection reset by peer")
    assert "API" not in text
