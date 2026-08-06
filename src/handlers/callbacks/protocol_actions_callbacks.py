"""Колбэки действий с готовым протоколом: «PDF», «Word», «Другой шаблон».

history_id приходит из callback_data — принадлежность записи пользователю
проверяется в репозитории (get_result_for_user), чужой id получает отказ.

Рядом с выбором шаблона живёт админский «Другой моделью»: обкаточной фазы у
модели нет (активный пресет один на всех), поэтому единственный способ увидеть
новую модель на реальной записи — перегенерировать ею готовый протокол и
сравнить бок о бок. Глобальный активный пресет при этом не меняется (ADR-0007).
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from loguru import logger

from src.utils.telegram_safe import safe_edit_text
from src.utils.template_sort import template_name_of
from src.ux.html_text import esc
from src.ux.keyboards import build_model_picker, build_template_picker
from src.ux.message_builder import ADMIN_ONLY, PROTOCOL_GONE
from src.ux.protocol_actions_callback_data import ProtoModelGo, ProtoModels

from .helpers import _safe_callback_answer

# Перегенерация без сохранённой транскрипции невозможна: генерировать не из чего.
NO_TRANSCRIPTION = "Расшифровка не сохранена — перегенерация недоступна."


def _history_id_from(data: str) -> int:
    return int(data.rsplit("_", 1)[-1])


async def _admin_or_refuse(callback: CallbackQuery, action: str) -> bool:
    """Пустить дальше только администратора; остальным — видимый отказ.

    Модель — глобальный параметр настроек приложения, а квота подписки общая:
    выбор модели при перегенерации остаётся инструментом обкатки (ADR-0007).
    """
    from src.utils.admin_utils import is_admin

    if is_admin(callback.from_user.id):
        return True
    logger.warning(f"Не-администратор {callback.from_user.id} запросил {action}")
    await _safe_callback_answer(callback, ADMIN_ONLY, show_alert=True)
    return False


def _model_choice_rows(user_id: int, history_id: int) -> list:
    """Вход на экран выбора модели — только в клавиатуре администратора.

    Обкатка живёт рядом с выбором шаблона, потому что это тот же вопрос «чем
    перегенерировать» и та же запись истории. Остальные пользователи кнопки не
    видят: у них модель одна, глобальная.
    """
    from src.utils.admin_utils import is_admin

    if not is_admin(user_id):
        return []
    return [[InlineKeyboardButton(
        text="Другой моделью",
        callback_data=ProtoModels(history_id=history_id).pack(),
    )]]


async def _regeneratable(callback: CallbackQuery, row) -> bool:
    """Годится ли запись истории для перегенерации; отказ объясняется на месте."""
    if not row:
        await _safe_callback_answer(callback, PROTOCOL_GONE)
        return False
    if not (row.get("transcription_text") or "").strip():
        await _safe_callback_answer(callback, NO_TRANSCRIPTION)
        return False
    return True


def setup_protocol_actions_callbacks(user_service, template_service) -> Router:
    """Обработчики кнопок под доставленным протоколом."""
    router = Router()

    @router.callback_query(F.data.startswith("proto_pdf_"))
    async def protocol_pdf_callback(callback: CallbackQuery):
        """PDF из сохранённого текста протокола — без повторной обработки."""
        try:
            from src.database import history_repo

            history_id = _history_id_from(callback.data)
            row = await history_repo.get_result_for_user(
                history_id, callback.from_user.id
            )
            if not row or not (row.get("result_text") or "").strip():
                await _safe_callback_answer(
                    callback, PROTOCOL_GONE
                )
                return

            await _safe_callback_answer(callback, "Готовлю PDF…")

            from src.services.result_sender import send_protocol_file

            sent = await send_protocol_file(
                callback.bot,
                callback.message.chat.id,
                row["result_text"],
                row["file_name"],
                "pdf",
            )
            if not sent:
                await callback.message.answer(
                    "❌ Не удалось отправить PDF. Попробуйте ещё раз."
                )
        except Exception as e:
            logger.error(f"Ошибка в protocol_pdf_callback: {e}")
            await _safe_callback_answer(callback, "❌ Не удалось подготовить PDF")

    @router.callback_query(F.data.startswith("proto_docx_"))
    async def protocol_docx_callback(callback: CallbackQuery):
        """Word (.docx) из сохранённого текста протокола — без повторной обработки."""
        try:
            from src.database import history_repo

            history_id = _history_id_from(callback.data)
            row = await history_repo.get_result_for_user(
                history_id, callback.from_user.id
            )
            if not row or not (row.get("result_text") or "").strip():
                await _safe_callback_answer(
                    callback, PROTOCOL_GONE
                )
                return

            await _safe_callback_answer(callback, "Готовлю Word…")

            from src.services.result_sender import send_protocol_file

            sent = await send_protocol_file(
                callback.bot,
                callback.message.chat.id,
                row["result_text"],
                row["file_name"],
                "docx",
            )
            if not sent:
                await callback.message.answer(
                    "❌ Не удалось отправить Word. Попробуйте ещё раз."
                )
        except Exception as e:
            logger.error(f"Ошибка в protocol_docx_callback: {e}")
            await _safe_callback_answer(callback, "❌ Не удалось подготовить Word")

    # «go» регистрируется раньше общего proto_regen_: startswith пересекаются.
    @router.callback_query(F.data.startswith("proto_regen_go_"))
    async def protocol_regen_go_callback(callback: CallbackQuery):
        """Запуск перегенерации выбранным шаблоном."""
        # callback_data приходит извне: разбираем ровно две числовые части и
        # вежливо отказываем на мусоре, не поднимая исключение и не логируя как
        # серверную ошибку.
        parts = callback.data.removeprefix("proto_regen_go_").split("_")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            logger.warning(f"Перегенерация: неожиданный callback_data «{callback.data}»")
            await _safe_callback_answer(
                callback, "Кнопка устарела — отправьте запись ещё раз."
            )
            return
        history_id, template_id = int(parts[0]), int(parts[1])

        try:
            template = await template_service.get_template_by_id(template_id)
            template_name = template_name_of(template, default="выбранный шаблон")
            await safe_edit_text(
                callback.message,
                f"⏳ Генерирую протокол по шаблону «{template_name}» — "
                "обычно это занимает меньше минуты.",
            )
            await _safe_callback_answer(callback)

            from src.services.protocol_actions import regenerate_protocol

            ok = await regenerate_protocol(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                telegram_user_id=callback.from_user.id,
                history_id=history_id,
                template_id=template_id,
                user_service=user_service,
                template_service=template_service,
            )
            if not ok:
                await safe_edit_text(
                    callback.message,
                    "❌ Не удалось перегенерировать протокол. "
                    "Отправьте запись ещё раз.",
                )
        except Exception as e:
            logger.error(f"Ошибка в protocol_regen_go_callback: {e}")
            await _safe_callback_answer(callback, "❌ Не удалось перегенерировать")

    # Точное совпадение регистрируем раньше общего startswith("proto_regen_").
    @router.callback_query(F.data == "proto_regen_cancel")
    async def protocol_regen_cancel_callback(callback: CallbackQuery):
        """Отмена выбора шаблона: убираем пикер, сообщаем об отмене."""
        try:
            await safe_edit_text(callback.message, "Перегенерация отменена.")
        except Exception as e:
            logger.error(f"Ошибка в protocol_regen_cancel_callback: {e}")
        await _safe_callback_answer(callback)

    @router.callback_query(ProtoModels.filter())
    async def protocol_models_callback(
        callback: CallbackQuery, callback_data: ProtoModels
    ):
        """Выбор модели для перегенерации — экран администратора (ADR-0007).

        Обкаточной фазы у модели нет: активный пресет один на всех, и его смена
        переводит на новую модель сразу всех пользователей. Перегенерация даёт
        сравнение бок о бок на реальной записи — тот же вход, другой провайдер.
        """
        if not await _admin_or_refuse(callback, "экран выбора модели"):
            return

        try:
            from src.database import history_repo, model_preset_repo

            row = await history_repo.get_result_for_user(
                callback_data.history_id, callback.from_user.id
            )
            if not await _regeneratable(callback, row):
                return

            presets = await model_preset_repo.get_enabled()
            if not presets:
                await _safe_callback_answer(
                    callback,
                    "Нет доступных моделей — добавьте модель командой /add_model.",
                    show_alert=True,
                )
                return

            keyboard = build_model_picker(
                presets,
                lambda p: ProtoModelGo(
                    history_id=callback_data.history_id, preset_key=p["key"]
                ).pack(),
                cancel_callback="proto_regen_cancel",
            )
            await safe_edit_text(
                callback.message,
                "<b>Какой моделью перегенерировать протокол?</b>\n\n"
                "Шаблон и расшифровка останутся прежними — сравнить можно "
                "бок о бок.\nАктивная модель бота не изменится.",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            await _safe_callback_answer(callback)
        except Exception as e:
            logger.error(f"Ошибка в protocol_models_callback: {e}")
            await _safe_callback_answer(callback, "❌ Не удалось загрузить список моделей")

    @router.callback_query(ProtoModelGo.filter())
    async def protocol_model_go_callback(
        callback: CallbackQuery, callback_data: ProtoModelGo
    ):
        """Запуск перегенерации выбранной моделью — только администратору.

        Шаблон берётся из самой записи: сравнение бок о бок имеет смысл, только
        когда меняется ровно одно — модель. Активный пресет бота не трогается
        (ADR-0007): обкатка не переводит на новую модель всех разом.
        """
        if not await _admin_or_refuse(callback, "перегенерацию выбранной моделью"):
            return

        try:
            from src.database import history_repo, model_preset_repo

            row = await history_repo.get_result_for_user(
                callback_data.history_id, callback.from_user.id
            )
            if not await _regeneratable(callback, row):
                return

            preset = await model_preset_repo.get_by_key(callback_data.preset_key)
            if not preset or not preset.get("is_enabled"):
                await _safe_callback_answer(
                    callback,
                    "Эта модель больше недоступна — выберите другую.",
                    show_alert=True,
                )
                return

            model_name = preset.get("name") or preset.get("model") or "выбранная модель"
            await safe_edit_text(
                callback.message,
                f"⏳ Генерирую протокол моделью «{esc(model_name)}» — "
                "обычно это занимает меньше минуты.",
                parse_mode="HTML",
            )
            await _safe_callback_answer(callback)

            from src.services.protocol_actions import regenerate_protocol

            ok = await regenerate_protocol(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                telegram_user_id=callback.from_user.id,
                history_id=callback_data.history_id,
                template_id=row["template_id"],
                user_service=user_service,
                template_service=template_service,
                preset=preset,
            )
            if not ok:
                await safe_edit_text(
                    callback.message,
                    "❌ Не удалось перегенерировать протокол. "
                    "Отправьте запись ещё раз.",
                )
        except Exception as e:
            logger.error(f"Ошибка в protocol_model_go_callback: {e}")
            await _safe_callback_answer(callback, "❌ Не удалось перегенерировать")

    @router.callback_query(F.data.startswith("proto_regen_"))
    async def protocol_regen_callback(callback: CallbackQuery):
        """Выбор шаблона для перегенерации готового протокола."""
        try:
            from src.database import history_repo

            history_id = _history_id_from(callback.data)
            row = await history_repo.get_result_for_user(
                history_id, callback.from_user.id
            )
            if not await _regeneratable(callback, row):
                return

            templates = await template_service.get_all_templates()
            keyboard = build_template_picker(
                templates,
                lambda t: f"proto_regen_go_{history_id}_{t.id}",
                bottom_rows=_model_choice_rows(callback.from_user.id, history_id),
                cancel_callback="proto_regen_cancel",
            )
            await callback.message.answer(
                "Каким шаблоном перегенерировать протокол?",
                reply_markup=keyboard,
            )
            await _safe_callback_answer(callback)
        except Exception as e:
            logger.error(f"Ошибка в protocol_regen_callback: {e}")
            await _safe_callback_answer(callback, "Не получилось, попробуйте ещё раз")

    return router
