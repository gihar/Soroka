"""Управление пресетами модели: /models, /add_model, /check_model и карточка.

Отдельно от общей админки: пресеты занимали в ней почти половину файла, а общего
с мониторингом и очисткой у них нет ничего, кроме проверки прав. Виды экранов
живут в ``src.ux.admin_views`` — сюда приходят только маршруты и работа с базой.

Пресет модели — полный адрес провайдера (ADR-0007): ключ, base_url, модели всех
шагов. Поэтому карточка называет адрес целиком, а не одно имя модели, а
резервный пресет здесь же назначается адресом автовозврата.

Поверхность (кнопки, подписи, текст карточки) говорит «модель» — старая
конвенция экрана; в глоссарии это «пресет модели» (CONTEXT.md), и комментарии с
докстрингами держатся словаря глоссария.
"""

import re
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.services.admin_alerts import clip_provider_error
from src.utils.admin_utils import is_admin
from src.utils.telegram_safe import safe_answer, safe_edit_text
from src.ux import admin_views
from src.ux.admin_views import ACCESS_DENIED
from src.ux.html_text import esc

# Провайдер отказал в доступе: ключ не принят. Отличается от «не ответил» —
# и то и другое не вердикт зонда о схеме, но чинится по-разному (issue #116).
_KEY_REFUSED_MARKERS = ("error code: 401", "error code: 403", "invalid api key",
                        "incorrect api key", "unauthorized")

_NO_RIGHTS = "❌ Недостаточно прав"

_ADD_MODEL_USAGE = (
    "<b>Использование</b>\n"
    "<code>/add_model model_id \"Название\" base_url [api_key]</code>\n\n"
    "<b>Пример</b>\n"
    '<code>/add_model gpt-4o "GPT-4o" https://api.openai.com/v1 sk-xxx</code>'
)

_ADD_MODEL_BAD_FORMAT = (
    "❌ Неверный формат. Используйте:\n"
    "<code>/add_model model_id Название base_url [api_key]</code>"
)


def _is_key_refused_error(exc: Exception) -> bool:
    """Провайдер отверг ключ (401/403), а не просто не ответил."""
    if getattr(exc, "status_code", None) in (401, 403):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _KEY_REFUSED_MARKERS)


def _probe_failure_reason(exc: Exception) -> str:
    """Причина отказа зонда для админского ответа — коротко, но по существу."""
    return clip_provider_error(" ".join(str(exc).split()) or exc.__class__.__name__)


async def _preset_roles() -> tuple:
    """Активный и резервный ключи — настройки приложения, а не свойства пресета."""
    from src.database import app_settings_repo

    return (
        await app_settings_repo.get_active_model_key(),
        await app_settings_repo.get_fallback_model_key(),
    )


async def _models_list_screen(presets):
    """Экран списка пресетов: текст и клавиатура."""
    active_key, fallback_key = await _preset_roles()
    return admin_views.models_list_view(
        presets, active_key=active_key, fallback_key=fallback_key
    )


async def _model_detail_screen(preset):
    """Экран карточки пресета: текст и клавиатура."""
    active_key, fallback_key = await _preset_roles()
    return admin_views.model_detail_view(
        preset, active_key=active_key, fallback_key=fallback_key
    )


async def _refuse_non_admin(callback: CallbackQuery) -> bool:
    """Не администратор — отказать и сказать об этом. True, если отказано."""
    if is_admin(callback.from_user.id):
        return False
    await callback.answer(_NO_RIGHTS, show_alert=True)
    return True


async def _preset_or_complaint(callback: CallbackQuery, key: str):
    """Пресет по ключу; None — если его нет, и об этом уже сказано на экране."""
    from src.database import model_preset_repo

    preset = await model_preset_repo.get_by_key(key)
    if not preset:
        await safe_edit_text(
            callback.message,
            f"❌ Модель <code>{esc(key)}</code> не найдена.",
            parse_mode="HTML",
        )
        return None
    return preset


def _parse_add_model_args(args_str: str):
    """Разобрать аргументы /add_model. None — формат не опознан.

    Поддерживаются оба написания названия: в кавычках и одним словом.
    """
    pattern_quoted = r'(\S+)\s+"([^"]+)"\s+(\S+)(?:\s+(\S+))?'
    pattern_simple = r'(\S+)\s+(\S+)\s+(https?://\S+)(?:\s+(\S+))?'
    match = re.match(pattern_quoted, args_str) or re.match(pattern_simple, args_str)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3), match.group(4)


def _preset_key_from(model_id: str) -> str:
    """Ключ пресета из идентификатора модели: только безопасные символы."""
    key = re.sub(r'[^a-zA-Z0-9_-]', '_', model_id)
    return key[:40]


async def _probe_target(message: Message, key: str):
    """Пресет, который проверит зонд: названный ключом или активный.

    None означает «проверять нечего» — о причине администратор уже извещён.
    """
    from src.database import app_settings_repo, model_preset_repo
    from src.exceptions.configuration import AdminConfigurationError
    from src.services.processing.llm_generation import resolve_active_preset

    try:
        if not key:
            return await resolve_active_preset(app_settings_repo, model_preset_repo)

        preset = await model_preset_repo.get_by_key(key)
        if preset:
            return preset
        await safe_answer(message,
            f"❌ Модель <code>{esc(key)}</code> не найдена.\n"
            "Список моделей — /models.",
            parse_mode="HTML",
        )
        return None
    except AdminConfigurationError as e:
        await safe_answer(message,
            f"❌ Проверять нечего: {esc(str(e))}.\n"
            "Выберите активную модель в /models или укажите пресет: "
            "<code>/check_model key</code>.",
            parse_mode="HTML",
        )
        return None


async def _probe_report(preset) -> str:
    """Вердикт зонда — или честный отказ: до модели не дошли.

    Вердикт считает зонд, команда его не пересчитывает.
    """
    from src.llm import protocol_generator

    try:
        verdict = await protocol_generator.probe_schema_support(preset=preset)
        return admin_views.model_check_verdict(preset["name"], verdict)
    except Exception as e:
        logger.error(f"Ошибка в check_model_handler [{preset.get('key')}]: {e}")
        return admin_views.model_check_failed(
            preset["name"], preset.get("model"), preset.get("base_url"),
            _probe_failure_reason(e), key_refused=_is_key_refused_error(e),
        )


def setup_admin_model_handlers() -> Router:
    """Роутер команд и кнопок управления пресетами модели."""
    router = Router()

    @router.message(Command("add_model"))
    async def add_model_handler(message: Message):
        """Добавление модели: /add_model model_id \"Name\" base_url [api_key]"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return

        from src.database import model_preset_repo

        raw_args = (message.text or "").split(maxsplit=1)
        args_str = raw_args[1].strip() if len(raw_args) > 1 else ""

        if not args_str:
            await safe_answer(message, _ADD_MODEL_USAGE, parse_mode="HTML")
            return

        parsed = _parse_add_model_args(args_str)
        if not parsed:
            await safe_answer(message, _ADD_MODEL_BAD_FORMAT, parse_mode="HTML")
            return

        model_id, name, base_url, api_key = parsed

        if urlparse(base_url).scheme not in ('https', 'http'):
            await message.answer("❌ base_url должен начинаться с https:// или http://")
            return

        key = _preset_key_from(model_id)

        try:
            await model_preset_repo.upsert(key, name, model_id, base_url, api_key)

            api_display = "задан" if api_key else "не задан (используется существующий)"
            await safe_answer(message,
                f"✅ Модель добавлена/обновлена\n\n"
                f"Key: <code>{esc(key)}</code>\n"
                f"Название: {esc(name)}\n"
                f"Model ID: <code>{esc(model_id)}</code>\n"
                f"Base URL: <code>{esc(base_url)}</code>\n"
                f"API Key: {api_display}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка в add_model_handler: {e}")
            await message.answer(f"❌ Ошибка при добавлении модели: {e}")

    @router.message(Command("check_model"))
    async def check_model_handler(message: Message):
        """Зонд строгих схем: /check_model [key] — применяет ли модель схему.

        Тонкая обёртка над операцией модуля генерации: разобрать пресет, позвать
        зонд, показать вердикт.
        """
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return

        raw_args = (message.text or "").split(maxsplit=1)
        key = raw_args[1].strip() if len(raw_args) > 1 else ""

        preset = await _probe_target(message, key)
        if preset is None:
            return

        status_msg = await safe_answer(message, "⏳ Проверяю модель")
        await safe_edit_text(status_msg, await _probe_report(preset), parse_mode="HTML")

    @router.message(Command("models"))
    async def models_handler(message: Message):
        """Список всех моделей с inline-кнопками."""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return

        try:
            from src.database import model_preset_repo

            presets = await model_preset_repo.get_all()
            text, keyboard = await _models_list_screen(presets)
            await safe_answer(message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в models_handler: {e}")
            await message.answer(f"❌ Ошибка при получении списка моделей: {e}")

    @router.callback_query(F.data.startswith("admin_model_toggle_"))
    async def admin_model_toggle_callback(callback: CallbackQuery):
        """Переключить is_enabled для модели."""
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import model_preset_repo
            from src.exceptions.configuration import ActivePresetDeletionError

            await callback.answer()
            key = callback.data.replace("admin_model_toggle_", "", 1)
            preset = await _preset_or_complaint(callback, key)
            if not preset:
                return

            new_value = 0 if preset.get("is_enabled") else 1
            try:
                await model_preset_repo.update_field(key, "is_enabled", new_value)
            except ActivePresetDeletionError as e:
                await safe_edit_text(callback.message, f"❌ {e.message}")
                return

            updated = await model_preset_repo.get_by_key(key)
            text, keyboard = await _model_detail_screen(updated)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_toggle_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_access_"))
    async def admin_model_access_callback(callback: CallbackQuery):
        """Переключить admin_only для модели."""
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import model_preset_repo

            await callback.answer()
            key = callback.data.replace("admin_model_access_", "", 1)
            preset = await _preset_or_complaint(callback, key)
            if not preset:
                return

            new_value = 0 if preset.get("admin_only") else 1
            await model_preset_repo.update_field(key, "admin_only", new_value)

            updated = await model_preset_repo.get_by_key(key)
            text, keyboard = await _model_detail_screen(updated)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_access_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_reserve_"))
    async def admin_model_reserve_callback(callback: CallbackQuery):
        """Назначить пресет резервным или снять этот признак.

        Резервный пресет — адрес автовозврата: на него бот сам переключается,
        упёршись в квотную стену подписки (ADR-0007). Незаданный резерв —
        законная настройка: тогда автовозврата нет, остаётся уведомление.
        """
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import app_settings_repo
            from src.exceptions.configuration import AdminConfigurationError

            await callback.answer()
            key = callback.data.replace("admin_model_reserve_", "", 1)
            preset = await _preset_or_complaint(callback, key)
            if not preset:
                return

            was_fallback = key == await app_settings_repo.get_fallback_model_key()
            try:
                if was_fallback:
                    await app_settings_repo.clear_fallback_model_key(
                        admin_id=callback.from_user.id
                    )
                else:
                    await app_settings_repo.set_fallback_model_key(
                        key, admin_id=callback.from_user.id
                    )
            except AdminConfigurationError as e:
                await safe_edit_text(callback.message, f"❌ {e.message}")
                return

            text, keyboard = await _model_detail_screen(preset)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_reserve_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_delete_"))
    async def admin_model_delete_callback(callback: CallbackQuery):
        """Удалить модель и вернуться к списку."""
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import model_preset_repo
            from src.exceptions.configuration import ActivePresetDeletionError

            await callback.answer()
            key = callback.data.replace("admin_model_delete_", "", 1)

            try:
                deleted = await model_preset_repo.delete(key)
            except ActivePresetDeletionError as e:
                await safe_edit_text(callback.message, f"❌ {e.message}")
                return

            if not deleted:
                await safe_edit_text(callback.message, f"❌ Модель <code>{esc(key)}</code> не найдена.", parse_mode="HTML")
                return

            presets = await model_preset_repo.get_all()
            text, keyboard = await _models_list_screen(presets)
            text = f"Модель <code>{esc(key)}</code> удалена.\n\n{text}"
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_delete_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data == "admin_models_sync")
    async def admin_models_sync_callback(callback: CallbackQuery):
        """Синхронизировать модели из .env конфига."""
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import model_preset_repo

            await callback.answer()
            count = await model_preset_repo.sync_from_config()

            presets = await model_preset_repo.get_all()
            text, keyboard = await _models_list_screen(presets)
            text = f"Синхронизировано моделей: {count}\n\n{text}"
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_models_sync_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка синхронизации: {e}")

    @router.callback_query(F.data == "admin_models_list")
    async def admin_models_list_callback(callback: CallbackQuery):
        """Вернуться к списку моделей (inline)."""
        if await _refuse_non_admin(callback):
            return

        try:
            from src.database import model_preset_repo

            await callback.answer()
            presets = await model_preset_repo.get_all()
            text, keyboard = await _models_list_screen(presets)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_models_list_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    # Ловушка на префикс — последней: она перехватывает всё, что не разобрали
    # уточнения выше (`admin_model_toggle_` и прочие).
    @router.callback_query(F.data.startswith("admin_model_"))
    async def admin_model_detail_callback(callback: CallbackQuery):
        """Карточка модели (детальный просмотр)."""
        if await _refuse_non_admin(callback):
            return

        try:
            await callback.answer()
            key = callback.data.replace("admin_model_", "", 1)
            preset = await _preset_or_complaint(callback, key)
            if not preset:
                return

            text, keyboard = await _model_detail_screen(preset)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_detail_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    return router
