"""Виды карточки и списка пресетов модели — чистые билдеры (ADR-0005).

Экран /models собирался прямо в хендлере, поэтому проверить его можно было
только через роутер. Здесь он проверяется как вид: на вход пресеты и две
настройки приложения (активный и резервный ключи), на выход текст и клавиатура.

Словарь глоссария на кнопках и в тексте карточки — старая конвенция «модель»
(CONTEXT.md называет понятие «пресет модели»); виды её сохраняют, менять
поверхность здесь не задача.
"""

import pytest

from src.ux import admin_views

QWEN = {
    "key": "qwen_plus",
    "name": "Qwen: plus",
    "model": "qwen3.7-plus",
    "base_url": "https://token-plan.example/compatible-mode/v1",
    "api_key": "sk-sp-xxx",
    "is_enabled": 1,
    "admin_only": 0,
}
OPENROUTER = {
    "key": "openrouter",
    "name": "OpenRouter: gpt-5-mini",
    "model": "gpt-5-mini",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key": None,
    "is_enabled": 1,
    "admin_only": 0,
}


def _buttons(markup) -> list[str]:
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _callbacks(markup) -> list[str]:
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


class TestModelDetail:
    """Карточка одного пресета."""

    def test_card_names_the_address_of_the_preset(self):
        """Пресет — полный адрес провайдера (ADR-0007): карточка называет его целиком."""
        text, _ = admin_views.model_detail_view(
            QWEN, active_key="openrouter", fallback_key=None
        )

        assert "Qwen: plus" in text
        assert "qwen3.7-plus" in text
        assert "https://token-plan.example/compatible-mode/v1" in text
        assert "задан" in text  # ключ есть, но в карточку не попадает

    def test_card_does_not_leak_the_api_key(self):
        """Ключ провайдера в чат не уходит — только «задан»/«не задан»."""
        text, _ = admin_views.model_detail_view(
            QWEN, active_key=None, fallback_key=None
        )

        assert "sk-sp-xxx" not in text

    def test_active_preset_is_not_offered_to_become_active(self):
        """Активной уже нельзя стать: кнопка, которая ничего не делает, лишняя."""
        _, keyboard = admin_views.model_detail_view(
            QWEN, active_key="qwen_plus", fallback_key=None
        )

        assert "Сделать активной" not in _buttons(keyboard)

    def test_disabled_preset_is_not_offered_to_become_active(self):
        """Выключенный пресет активным не назначают — репозиторий это и не даст."""
        _, keyboard = admin_views.model_detail_view(
            {**QWEN, "is_enabled": 0}, active_key="openrouter", fallback_key=None
        )

        assert "Сделать активной" not in _buttons(keyboard)
        assert "Включить" in _buttons(keyboard)

    def test_reserve_button_offers_the_opposite_of_the_current_role(self):
        """Кнопка резерва называет то, что произойдёт, а не то, что уже есть."""
        _, not_reserve = admin_views.model_detail_view(
            QWEN, active_key=None, fallback_key=None
        )
        _, reserve = admin_views.model_detail_view(
            QWEN, active_key=None, fallback_key="qwen_plus"
        )

        assert "Сделать резервной" in _buttons(not_reserve)
        assert "Убрать из резервных" in _buttons(reserve)

    def test_reserve_equal_to_active_says_there_will_be_no_failover(self):
        """Резерв, совпавший с активным, переключать некуда — карточка не обещает.

        Сюда приводит сам автовозврат (ADR-0007), состояние законное; молчание
        о нём означало бы обещание автовозврата, которого не будет.
        """
        text, _ = admin_views.model_detail_view(
            QWEN, active_key="qwen_plus", fallback_key="qwen_plus"
        )

        assert "автовозврата не будет" in text

    def test_a_plain_reserve_says_just_yes(self):
        """Резерв, отличный от активного, работает — оговорка тут ни к чему."""
        text, _ = admin_views.model_detail_view(
            QWEN, active_key="openrouter", fallback_key="qwen_plus"
        )

        assert "Резервная: да" in text
        assert "автовозврата не будет" not in text


class TestModelsList:
    """Список пресетов: кто активен, кто в резерве, кто выключен."""

    def test_active_preset_is_marked_and_the_reserve_is_named(self):
        """Маркер выбора один: резерв называем словом, иначе «активный» теряется.

        Маркер — ✓ («выбрано»), а не ✅ («сделано»): канон v10, общий со всеми
        остальными списками бота.
        """
        from src.ux.speaker_mapping_ui import SELECTED_MARK

        text, keyboard = admin_views.models_list_view(
            [QWEN, OPENROUTER], active_key="qwen_plus", fallback_key="openrouter"
        )

        assert f"{SELECTED_MARK} Qwen: plus" in text
        assert "OpenRouter: gpt-5-mini · резерв" in text
        assert text.count(SELECTED_MARK) == 1
        assert _callbacks(keyboard)[:2] == ["admin_model_qwen_plus", "admin_model_openrouter"]

    def test_disabled_preset_is_named_disabled(self):
        """Выключенный пресет виден как выключенный, а не пропадает из списка."""
        text, _ = admin_views.models_list_view(
            [{**QWEN, "is_enabled": 0}], active_key=None, fallback_key=None
        )

        assert "Qwen: plus · выкл" in text

    def test_admin_only_preset_is_named(self):
        text, _ = admin_views.models_list_view(
            [{**QWEN, "admin_only": 1}], active_key=None, fallback_key=None
        )

        assert "Qwen: plus · админы" in text

    def test_empty_list_still_offers_the_way_out(self):
        """Пресетов нет — экран говорит, чем это чинится, и даёт синхронизацию."""
        text, keyboard = admin_views.models_list_view(
            [], active_key=None, fallback_key=None
        )

        assert "/add_model" in text
        assert _callbacks(keyboard) == ["admin_models_sync"]

    def test_every_list_offers_sync_from_env(self):
        _, keyboard = admin_views.models_list_view(
            [QWEN], active_key=None, fallback_key=None
        )

        assert _callbacks(keyboard)[-1] == "admin_models_sync"
