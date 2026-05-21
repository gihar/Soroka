"""Tests for the is_admin-aware settings menu."""
import os
import sys

# Add src to path so `from services import ...` inside quick_actions resolves
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from src.ux.quick_actions import QuickActionsUI  # noqa: E402


def _callback_data_set(keyboard):
    return {
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data
    }


def test_admin_sees_active_model_button():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=True)
    data = _callback_data_set(keyboard)
    assert "settings_active_model" in data
    # Old per-user buttons are gone
    assert "settings_preferred_llm" not in data
    assert "settings_openai_model" not in data


def test_non_admin_does_not_see_active_model_button():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=False)
    data = _callback_data_set(keyboard)
    assert "settings_active_model" not in data
    assert "settings_preferred_llm" not in data
    assert "settings_openai_model" not in data


def test_non_admin_still_sees_other_settings():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=False)
    data = _callback_data_set(keyboard)
    assert "settings_protocol_output" in data
    assert "settings_default_template" in data
    assert "settings_stats" in data
    assert "settings_reset" in data
