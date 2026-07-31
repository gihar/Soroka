"""Критика v11: убрано мёртвое и размноженное.

Экраны, до которых нельзя дойти, дороже, чем кажутся: они выглядят рабочей
функциональностью в коде, их правят при рефакторингах и на них ссылаются в
обсуждениях. Размноженная формулировка дороже так же — следующая правка голоса
поправит одну копию из пятнадцати.
"""

import inspect
from pathlib import Path

import pytest

import src.handlers.participants_handlers as ph

_SRC = Path("src")


def _source(*parts) -> str:
    return (_SRC.joinpath(*parts)).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Недостижимые экраны
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "show_protocol_info_menu",   # add_protocol_info никто не шлёт
    "prompt_auto_extraction",    # auto_extract_meeting_info никто не шлёт
    "handle_participants_file",  # media_handler забирает документы раньше
])
def test_unreachable_screen_is_gone(name):
    assert name not in _source("handlers", "participants_handlers.py")


def test_queue_tracker_has_no_uncalled_screen():
    """show_processing_started не вызывался ниоткуда."""
    assert "show_processing_started" not in _source("ux", "queue_tracker.py")


def test_protocol_info_state_is_gone():
    """Состояния жили только ради недостижимого экрана."""
    assert "ProtocolInfoState" not in _source("handlers", "participants_states.py")


def test_reachable_meeting_info_confirmation_survives():
    """Обратная сторона: разбор приглашения текстом — живой путь, он остаётся."""
    source = _source("handlers", "participants_handlers.py")
    assert "confirm_meeting_info" in source


def test_no_orphan_stub_after_configure():
    """«⚙️ Настройка обработки...» навсегда оставался в чате огрызком."""
    assert "Настройка обработки..." not in _source(
        "handlers", "callbacks", "processing_callbacks.py"
    )


def test_configure_still_disarms_the_original_keyboard():
    """Кнопки «Файл получен» обязаны перестать работать после выбора."""
    source = _source("handlers", "callbacks", "processing_callbacks.py")
    assert "edit_reply_markup" in source


def test_empty_keyboard_row_is_gone():
    """Пустая строка в инлайн-клавиатуре Telegram ничего не разделяет."""
    source = _source("ux", "speaker_mapping_ui.py")
    assert "append([])" not in source


# ---------------------------------------------------------------------------
# Одна формулировка — одно место
# ---------------------------------------------------------------------------


def _literal_count(source: str, needle: str) -> int:
    return source.count(f'"{needle}"') + source.count(f"'{needle}'")


def test_access_denied_has_one_home():
    """Константа была заведена ещё в v10, но admin_handlers держал 15 копий."""
    source = _source("handlers", "admin_handlers.py")
    assert _literal_count(source, "❌ Недостаточно прав для выполнения команды.") == 0
    assert "ACCESS_DENIED" in source


def test_back_to_settings_button_has_one_home():
    from src.ux.keyboards import BACK_TO_SETTINGS

    for module in ("settings_callbacks.py", "template_mgmt_callbacks.py"):
        source = _source("handlers", "callbacks", module)
        assert _literal_count(source, "⬅️ Назад к настройкам") == 0, module
    assert BACK_TO_SETTINGS.text == "⬅️ Назад к настройкам"


def test_back_to_settings_button_keeps_working():
    from src.ux.keyboards import BACK_TO_SETTINGS, back_to_settings_keyboard

    assert BACK_TO_SETTINGS.callback_data == "back_to_settings"
    markup = back_to_settings_keyboard()
    assert markup.inline_keyboard[0][0].callback_data == "back_to_settings"


def test_generic_error_has_one_home():
    from src.ux.message_builder import SOMETHING_WENT_WRONG

    for module in ("template_callbacks.py", "template_mgmt_callbacks.py"):
        source = _source("handlers", "callbacks", module)
        assert _literal_count(source, "❌ Произошла ошибка") == 0, module
    assert SOMETHING_WENT_WRONG.startswith("❌")


def test_record_lost_message_names_one_thing():
    """«Запись потерялась. Отправьте файл ещё раз» — два слова об одном объекте."""
    from src.ux.message_builder import RECORD_LOST_FILE, RECORD_LOST_LINK

    assert "файл" not in RECORD_LOST_FILE.lower()
    assert "ссылк" in RECORD_LOST_LINK.lower()


def test_record_lost_messages_have_one_home():
    for module in ("processing_callbacks.py",):
        source = _source("handlers", "callbacks", module)
        assert _literal_count(source, "❌ Запись потерялась.\\nОтправьте файл ещё раз.") == 0
    assert "RECORD_LOST_FILE" in _source("handlers", "message_handlers.py")


def test_shared_texts_are_not_reimported_by_accident():
    """Константы живут в одном модуле — иначе смысл выноса теряется."""
    from src.ux import message_builder

    for name in ("RECORD_LOST_FILE", "RECORD_LOST_LINK", "SOMETHING_WENT_WRONG"):
        assert isinstance(getattr(message_builder, name), str)


def test_handlers_still_have_their_router():
    """Санитарная проверка: удаления не сломали сборку роутера."""
    router = ph.setup_participants_handlers()
    assert router.callback_query.handlers
    assert inspect.isfunction(ph.show_participants_menu.__wrapped__) if hasattr(
        ph.show_participants_menu, "__wrapped__"
    ) else True
