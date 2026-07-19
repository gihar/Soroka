"""Критика v4, distill: мёртвый UI и схемы выпилены, категории не лгут."""

import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))


# ---------------------------------------------------------------------------
# Мёртвые меню и фиктивные профили удалены
# ---------------------------------------------------------------------------

def test_stub_quick_menus_removed():
    import src.ux.quick_actions as qa

    src_text = inspect.getsource(qa)
    assert "create_template_quick_menu" not in src_text
    assert "quick_process_default" not in src_text
    assert "quick_template_" not in src_text
    assert "create_file_actions_menu" not in src_text


def test_fake_quick_profiles_removed():
    import src.ux.quick_actions as qa

    src_text = inspect.getsource(qa)
    assert 'Command("quick")' not in src_text
    assert "Профиль: Деловая встреча" not in src_text


def test_user_guidance_removed():
    import src.ux as ux

    assert not hasattr(ux, "UserGuidance")


def test_dead_llm_schemas_removed():
    import src.models.llm_schemas as schemas

    src_text = inspect.getsource(schemas)
    for dead in (
        "class ExtractionSchema",
        "class ConsolidatedProtocolSchema",
        "class UnifiedProtocolSchema",
        "class TwoStageExtractionSchema",
        "class ODProtocolSchema",
        "def get_schema_by_type",
    ):
        assert dead not in src_text, dead


def test_live_schemas_survive():
    from src.models.llm_schemas import (
        MEETING_ANALYSIS_SCHEMA,
        PROTOCOL_DATA_SCHEMA,
        SPEAKER_MAPPING_SCHEMA,
    )

    for schema in (MEETING_ANALYSIS_SCHEMA, PROTOCOL_DATA_SCHEMA, SPEAKER_MAPPING_SCHEMA):
        assert schema["strict"] is True


# ---------------------------------------------------------------------------
# Кнопки категорий фильтруют по-настоящему
# ---------------------------------------------------------------------------

def _mgmt_router(templates):
    import src.handlers.callbacks.template_mgmt_callbacks as tmc

    service = MagicMock()
    service.get_all_templates = AsyncMock(return_value=templates)
    router = tmc.setup_template_mgmt_callbacks(MagicMock(), service, MagicMock())
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "view_template_category_callback"
    )
    return handler


def _template(tid, name, category):
    return SimpleNamespace(id=tid, name=name, category=category, is_default=True)


def _make_callback(data):
    callback = MagicMock()
    callback.data = data
    callback.from_user = SimpleNamespace(id=1)
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_category_button_shows_only_its_templates(monkeypatch):
    import src.handlers.callbacks.template_mgmt_callbacks as tmc

    sent = {}

    async def fake_edit(message, text, **kwargs):
        sent["text"] = text
        sent["markup"] = kwargs.get("reply_markup")
        return object()

    monkeypatch.setattr(tmc, "safe_edit_text", fake_edit)

    handler = _mgmt_router([
        _template(1, "Протокол ОД (Поручения)", "management"),
        _template(2, "Дейли", "general"),
        _template(3, "Лекция и презентация", "educational"),
    ])

    await handler(_make_callback("view_template_category_management"))

    button_texts = [
        btn.text for row in sent["markup"].inline_keyboard for btn in row
    ]
    assert any("ОД" in t for t in button_texts)
    assert not any("Дейли" in t for t in button_texts)
    assert not any("Лекция" in t for t in button_texts)


@pytest.mark.asyncio
async def test_category_all_shows_everything(monkeypatch):
    import src.handlers.callbacks.template_mgmt_callbacks as tmc

    sent = {}

    async def fake_edit(message, text, **kwargs):
        sent["markup"] = kwargs.get("reply_markup")
        return object()

    monkeypatch.setattr(tmc, "safe_edit_text", fake_edit)

    handler = _mgmt_router([
        _template(1, "Протокол ОД (Поручения)", "management"),
        _template(2, "Дейли", "general"),
    ])

    await handler(_make_callback("view_template_category_all"))

    button_texts = [
        btn.text for row in sent["markup"].inline_keyboard for btn in row
    ]
    assert any("ОД" in t for t in button_texts)
    assert any("Дейли" in t for t in button_texts)


# ---------------------------------------------------------------------------
# Шаг создания шаблона: компактная подсказка вместо 1.5 экранов справки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_creation_step_hint_is_compact(monkeypatch):
    import src.handlers.template_handlers as th

    sent = {}

    async def fake_answer(message, text, **kwargs):
        sent["text"] = text
        return object()

    monkeypatch.setattr(th, "safe_answer", fake_answer)

    router = th.setup_template_handlers(MagicMock())
    handler = next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "template_name_handler"
    )

    message = MagicMock()
    message.text = "Мой шаблон планёрки"
    message.answer = AsyncMock()
    state = MagicMock()
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await handler(message, state)

    text = sent["text"]
    assert len(text) < 900  # компактно, не 1.5 экрана
    assert "{% if" in text  # главный приём упомянут
    assert "/templates" in text  # полная справка достижима
