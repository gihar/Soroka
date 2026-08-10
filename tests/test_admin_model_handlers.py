"""Управление пресетами модели переехало в свой модуль — маршруты уцелели.

Хендлеры и колбэки пресетов (`/models`, `/add_model`, `/check_model` и
inline-кнопки карточки) живут отдельно от общей админки: там они занимали почти
половину файла. Переезд обязан быть незаметным снаружи — команду и кнопку
по-прежнему находит тот же роутер администратора.

Отдельно закрепляется порядок фильтров: разбор `admin_model_<key>` — ловушка на
префикс, и встань она раньше своих же уточнений (`_toggle_`, `_access_`,
`_reserve_`, `_delete_`), нажатие «Выключить» открывало бы карточку пресета с
ключом «toggle_qwen».
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.filters import Command


def _admin_router() -> Router:
    from src.handlers.admin_handlers import setup_admin_handlers

    return setup_admin_handlers(processing_service=MagicMock())


def _all_routers(router: Router):
    """Роутер и всё, что в него вложено."""
    yield router
    for sub in router.sub_routers:
        yield from _all_routers(sub)


def _commands(router: Router) -> set[str]:
    """Команды, которые роутер (со вложенными) принимает."""
    found = set()
    for current in _all_routers(router):
        for handler in current.message.handlers:
            for flt in handler.filters or ():
                if isinstance(flt.callback, Command):
                    found.update(str(cmd) for cmd in flt.callback.commands)
    return found


def _callback_handler_names(router: Router) -> list[str]:
    return [
        handler.callback.__name__
        for current in _all_routers(router)
        for handler in current.callback_query.handlers
    ]


@pytest.mark.parametrize("command", ["models", "add_model", "check_model"])
def test_admin_router_still_answers_the_preset_commands(command):
    """Команда осталась на месте: переезд модуля пользователю не виден."""
    assert command in _commands(_admin_router())


@pytest.mark.parametrize(
    "handler_name",
    [
        "admin_model_toggle_callback",
        "admin_model_access_callback",
        "admin_model_reserve_callback",
        "admin_model_delete_callback",
        "admin_model_detail_callback",
        "admin_models_sync_callback",
        "admin_models_list_callback",
    ],
)
def test_admin_router_still_carries_the_preset_callbacks(handler_name):
    """Кнопки карточки и списка по-прежнему находят свой обработчик."""
    assert handler_name in _callback_handler_names(_admin_router())


def test_the_prefix_catch_all_stays_behind_its_own_refinements():
    """Ловушка `admin_model_` идёт последней — иначе она перехватит уточнения."""
    names = _callback_handler_names(_admin_router())
    catch_all = names.index("admin_model_detail_callback")

    for refinement in ("admin_model_toggle_callback", "admin_model_access_callback",
                       "admin_model_reserve_callback", "admin_model_delete_callback"):
        assert names.index(refinement) < catch_all


async def test_models_screen_survives_the_move_end_to_end(monkeypatch, test_db,
                                                          app_settings_repo):
    """Живой /models: база → экран. Ловит разрыв шва между хендлером и видом.

    Проверка маршрутов молчит о том, дошли ли до вида активный и резервный
    ключи: их читает хендлер, а рисует вид.
    """
    import src.database as database
    from src.database.model_preset_repo import ModelPresetRepository
    from src.handlers import admin_model_handlers as amh

    preset_repo = ModelPresetRepository(test_db)
    await preset_repo.upsert(key="qwen_plus", name="Qwen: plus",
                             model="qwen3.7-plus", base_url="https://q.example/v1")
    await preset_repo.upsert(key="openrouter", name="OpenRouter: gpt-5-mini",
                             model="gpt-5-mini", base_url="https://o.example/v1")
    await app_settings_repo.set_active_model_key("qwen_plus", admin_id=42)
    await app_settings_repo.set_fallback_model_key("openrouter", admin_id=42)
    monkeypatch.setattr(database, "app_settings_repo", app_settings_repo)
    monkeypatch.setattr(database, "model_preset_repo", preset_repo)
    monkeypatch.setattr(amh, "is_admin", lambda _uid: True)

    shown = {}

    async def fake_answer(_message, text, **kwargs):
        shown["text"] = text

    monkeypatch.setattr(amh, "safe_answer", fake_answer)

    router = amh.setup_admin_model_handlers()
    handler = next(h.callback for h in router.message.handlers
                   if h.callback.__name__ == "models_handler")
    await handler(SimpleNamespace(text="/models", from_user=SimpleNamespace(id=1),
                                  answer=AsyncMock()))

    from src.ux.speaker_mapping_ui import SELECTED_MARK

    assert f"{SELECTED_MARK} Qwen: plus" in shown["text"]
    assert "OpenRouter: gpt-5-mini · резерв" in shown["text"]


def test_general_admin_commands_did_not_move_with_the_presets():
    """Переехали только пресеты: мониторинг и очистка остались в общей админке."""
    from src.handlers import admin_handlers

    router = admin_handlers.setup_admin_handlers(processing_service=MagicMock())
    own_commands = _commands(Router()) | {
        str(cmd)
        for handler in router.message.handlers
        for flt in handler.filters or ()
        if isinstance(flt.callback, Command)
        for cmd in flt.callback.commands
    }

    assert {"status", "health", "stats", "cleanup"} <= own_commands
    assert "models" not in own_commands
