"""
Обработчики callback запросов для настроек бота.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.services import ProcessingService, TemplateService, UserService
from src.utils.telegram_safe import safe_edit_text


def setup_settings_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для настроек"""
    router = Router()

    @router.callback_query(F.data == "settings_protocol_output")
    async def settings_protocol_output_callback(callback: CallbackQuery):
        """Обработчик настройки режима вывода протокола"""
        try:
            # Получаем текущую настройку пользователя
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            current = getattr(user, 'protocol_output_mode', None) or 'messages'

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'messages' else ''}💬 В сообщения",
                    callback_data="set_protocol_output_messages"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'file' else ''}📎 В файл md",
                    callback_data="set_protocol_output_file"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'pdf' else ''}📄 В файл pdf",
                    callback_data="set_protocol_output_pdf"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message,
                "📤 **Вывод протокола**\n\n"
                "Выберите, как отправлять готовый протокол:\n"
                "• 💬 В сообщения — протокол приходит текстом в чат (по умолчанию)\n"
                "• 📎 В файл md — протокол отправляется как прикрепленный файл (.md)\n"
                "• 📄 В файл pdf — протокол отправляется как прикрепленный файл (.pdf)",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_protocol_output_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")

    @router.callback_query(F.data.in_({"set_protocol_output_messages", "set_protocol_output_file", "set_protocol_output_pdf"}))
    async def set_protocol_output_mode_callback(callback: CallbackQuery):
        """Установка режима вывода протокола"""
        try:
            if callback.data.endswith('messages'):
                mode = 'messages'
                mode_text = "💬 В сообщения"
            elif callback.data.endswith('pdf'):
                mode = 'pdf'
                mode_text = "📄 В файл pdf"
            else:
                mode = 'file'
                mode_text = "📎 В файл md"

            await user_service.update_user_protocol_output_preference(callback.from_user.id, mode)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message,
                f"✅ Режим вывода протокола изменён на: {mode_text}",
                reply_markup=keyboard
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_protocol_output_mode_callback: {e}")
            await callback.answer("❌ Не удалось изменить режим вывода")

    @router.callback_query(F.data == "settings_reset")
    async def settings_reset_callback(callback: CallbackQuery):
        """Обработчик сброса всех настроек"""
        try:
            # Сбрасываем режим вывода протокола на значение по умолчанию
            try:
                await user_service.update_user_protocol_output_preference(callback.from_user.id, 'messages')
            except Exception:
                pass

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message,
                "🔄 **Настройки сброшены**\n\n"
                "Все ваши настройки восстановлены по умолчанию:\n\n"
                "• Шаблон по умолчанию сброшен\n"
                "• Другие настройки восстановлены\n\n"
                "Теперь бот будет использовать настройки по умолчанию.",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в settings_reset_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")

    @router.callback_query(F.data == "settings_stats")
    async def settings_stats_callback(callback: CallbackQuery):
        """Показ статистики из меню настроек"""
        try:
            from datetime import datetime

            from src.database import history_repo
            from src.reliability.middleware import monitoring_middleware

            user_stats = await history_repo.get_user_stats(callback.from_user.id)
            system_stats = monitoring_middleware.get_stats()

            if user_stats:
                total_files = user_stats.get('total_files', 0)
                active_days = user_stats.get('active_days', 0)
                favorite_templates = user_stats.get('favorite_templates', [])
                llm_providers = user_stats.get('llm_providers', [])

                stats_text = "📊 **Ваша статистика**\n\n"
                stats_text += f"🔄 **Обработано файлов:** {total_files}\n"
                stats_text += f"📅 **Активных дней:** {active_days}\n"

                if user_stats.get('first_file_date'):
                    try:
                        first_date = datetime.fromisoformat(
                            user_stats['first_file_date'].replace('Z', '+00:00')
                        )
                        days_since = (datetime.now() - first_date.replace(tzinfo=None)).days
                        stats_text += f"🎯 **Дней с начала:** {days_since}\n"
                    except Exception:
                        pass

                if favorite_templates:
                    stats_text += "\n📝 **Популярные шаблоны:**\n"
                    for t in favorite_templates[:3]:
                        stats_text += f"• {t['name']}: {t['count']} раз\n"

                if llm_providers:
                    stats_text += "\n🤖 **AI модели:**\n"
                    for p in llm_providers[:3]:
                        name = p['llm_provider'].title() if p['llm_provider'] else '?'
                        stats_text += f"• {name}: {p['count']} раз\n"
            else:
                stats_text = "📊 **Статистика**\n\nОбработано файлов: 0\n🚀 Отправьте файл для обработки!\n"

            # System stats only for admins
            from src.utils.admin_utils import is_admin
            if is_admin(callback.from_user.id):
                stats_text += (
                    f"\n🌐 **Система:**\n"
                    f"• Запросов: {system_stats.get('total_requests', 0)}\n"
                    f"• Пользователей: {system_stats.get('active_users', 0)}\n"
                    f"• Среднее время: {system_stats.get('average_processing_time', 0):.1f}с\n"
                )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
            ])

            await safe_edit_text(callback.message, stats_text,
                                reply_markup=keyboard, parse_mode="Markdown")
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в settings_stats_callback: {e}")
            await callback.answer("❌ Ошибка при загрузке статистики")

    @router.callback_query(F.data == "back_to_settings")
    async def back_to_settings_callback(callback: CallbackQuery):
        """Обработчик возврата к главному меню настроек"""
        try:
            from src.utils.admin_utils import is_admin as _is_admin
            from src.ux.quick_actions import QuickActionsUI

            keyboard = QuickActionsUI.create_settings_menu(
                is_admin=_is_admin(callback.from_user.id)
            )

            await safe_edit_text(callback.message,
                "⚙️ **Настройки бота**\n\n"
                "Настройте бота под ваши предпочтения:",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в back_to_settings_callback: {e}")
            await callback.answer("❌ Произошла ошибка при возврате к настройкам")

    @router.callback_query(F.data == "settings_active_model")
    async def settings_active_model_callback(callback: CallbackQuery):
        """Show the active-model picker (admin only)."""
        from src.utils.admin_utils import is_admin
        if not is_admin(callback.from_user.id):
            logger.warning(
                f"Non-admin {callback.from_user.id} attempted to open settings_active_model"
            )
            await callback.answer(
                "❌ Доступно только администратору", show_alert=True
            )
            return

        try:
            from src.database import app_settings_repo, model_preset_repo

            preset_repo = model_preset_repo

            presets = await preset_repo.get_enabled()
            if not presets:
                await safe_edit_text(
                    callback.message,
                    "❌ Нет доступных моделей.\n\n"
                    "Используйте /add_model чтобы добавить модель.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="⬅️ Назад к настройкам",
                            callback_data="back_to_settings",
                        )]
                    ]),
                )
                await callback.answer()
                return

            active_key = await app_settings_repo.get_active_model_key()
            rows = []
            for p in presets:
                marker = "✅ " if p["key"] == active_key else ""
                rows.append([InlineKeyboardButton(
                    text=f"{marker}{p['name']}",
                    callback_data=f"set_active_model_{p['key']}",
                )])
            rows.append([InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data="back_to_settings",
            )])

            await safe_edit_text(
                callback.message,
                "🤖 **Модель ИИ**\n\n"
                "Выберите модель, которая будет использоваться ботом:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                parse_mode="Markdown",
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_active_model_callback: {e}")
            await callback.answer("❌ Не удалось загрузить список моделей")

    @router.callback_query(F.data.startswith("set_active_model_"))
    async def set_active_model_callback(callback: CallbackQuery):
        """Apply admin's choice of active model (admin only)."""
        from src.utils.admin_utils import is_admin
        if not is_admin(callback.from_user.id):
            logger.warning(
                f"Non-admin {callback.from_user.id} attempted set_active_model"
            )
            await callback.answer(
                "❌ Доступно только администратору", show_alert=True
            )
            return

        try:
            preset_key = callback.data.replace("set_active_model_", "", 1)

            from src.database import app_settings_repo, model_preset_repo
            from src.exceptions.configuration import AdminConfigurationError

            preset_repo = model_preset_repo

            try:
                await app_settings_repo.set_active_model_key(
                    preset_key, admin_id=callback.from_user.id
                )
            except AdminConfigurationError as e:
                await callback.answer(f"❌ {e.message}", show_alert=True)
                return

            preset = await preset_repo.get_by_key(preset_key)
            model_name = preset["name"] if preset else preset_key

            await safe_edit_text(
                callback.message,
                f"✅ Активная модель: **{model_name}**\n\n"
                "Бот будет использовать эту модель для всех обработок.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings",
                    )]
                ]),
                parse_mode="Markdown",
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_active_model_callback: {e}")
            await callback.answer("❌ Не удалось сохранить выбор модели")

    return router
