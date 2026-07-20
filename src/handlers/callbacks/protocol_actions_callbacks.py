"""Колбэки действий с готовым протоколом: «📄 PDF» и «🔁 Другой шаблон».

history_id приходит из callback_data — принадлежность записи пользователю
проверяется в репозитории (get_result_for_user), чужой id получает отказ.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from src.utils.telegram_safe import safe_edit_text
from src.utils.template_sort import template_name_of
from src.ux.keyboards import build_template_picker

from .helpers import _safe_callback_answer


def _history_id_from(data: str) -> int:
    return int(data.rsplit("_", 1)[-1])


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
                    callback, "Протокол не найден — возможно, история очищена."
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

    @router.callback_query(F.data.startswith("proto_regen_"))
    async def protocol_regen_callback(callback: CallbackQuery):
        """Выбор шаблона для перегенерации готового протокола."""
        try:
            from src.database import history_repo

            history_id = _history_id_from(callback.data)
            row = await history_repo.get_result_for_user(
                history_id, callback.from_user.id
            )
            if not row:
                await _safe_callback_answer(
                    callback, "Протокол не найден — возможно, история очищена."
                )
                return
            if not (row.get("transcription_text") or "").strip():
                await _safe_callback_answer(
                    callback, "Расшифровка не сохранена — перегенерация недоступна."
                )
                return

            templates = await template_service.get_all_templates()
            keyboard = build_template_picker(
                templates,
                lambda t: f"proto_regen_go_{history_id}_{t.id}",
                cancel_callback="proto_regen_cancel",
            )
            await callback.message.answer(
                "Каким шаблоном перегенерировать протокол?",
                reply_markup=keyboard,
            )
            await _safe_callback_answer(callback)
        except Exception as e:
            logger.error(f"Ошибка в protocol_regen_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    return router
