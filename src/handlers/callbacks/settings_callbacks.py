"""
Обработчики callback запросов для настроек бота.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.telegram_safe import safe_edit_text


def setup_settings_callbacks(user_service: UserService, template_service: TemplateService,
                              llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для настроек"""
    router = Router()

    @router.callback_query(F.data == "settings_preferred_llm")
    async def settings_preferred_llm_callback(callback: CallbackQuery):
        """Обработчик настройки предпочитаемого ИИ"""
        try:
            available_providers = llm_service.get_available_providers()

            # Создаем клавиатуру для выбора LLM
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🤖 {provider_name}",
                    callback_data=f"set_llm_{provider_key}"
                )] for provider_key, provider_name in available_providers.items()
            ] + [
                [InlineKeyboardButton(
                    text="🔄 Сбросить предпочтение",
                    callback_data="reset_llm_preference"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message,
                "🤖 **Выберите предпочитаемый ИИ**\n\n"
                "Этот ИИ будет использоваться автоматически для всех обработок:",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в settings_preferred_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")

    @router.callback_query(F.data == "settings_openai_model")
    async def settings_openai_model_callback(callback: CallbackQuery):
        """Обработчик меню выбора модели OpenAI"""
        try:
            from src.database.model_preset_repo import ModelPresetRepository
            from database import db as app_db
            repo = ModelPresetRepository(app_db)
            presets = await repo.get_available_for_user(callback.from_user.id)
            if not presets:
                await safe_edit_text(callback.message,
                    "❌ Нет доступных моделей.\n\n"
                    "Используйте /add_model чтобы добавить модель.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                    ])
                )
                await callback.answer()
                return
            # Получаем текущего пользователя и его выбор
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None

            keyboard_rows = []
            for p in presets:
                label = f"{'✅ ' if selected_key == p['key'] else ''}{p['name']}"
                keyboard_rows.append([InlineKeyboardButton(text=label, callback_data=f"set_openai_model_{p['key']}")])
            keyboard_rows.append([InlineKeyboardButton(text="🔄 Сбросить выбор модели", callback_data="reset_openai_model_preference")])
            keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")])

            await safe_edit_text(callback.message,
                "🧠 **Модель OpenAI**\n\n"
                "Выберите модель, которая будет использоваться при провайдере OpenAI:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось загрузить модели OpenAI")

    @router.callback_query(F.data.startswith("set_openai_model_"))
    async def set_openai_model_callback(callback: CallbackQuery):
        """Устанавливает предпочитаемую модель OpenAI"""
        try:
            model_key = callback.data.replace("set_openai_model_", "")
            await user_service.update_user_openai_model_preference(callback.from_user.id, model_key)
            # Находим человекочитаемое имя модели из БД
            try:
                from src.database.model_preset_repo import ModelPresetRepository
                from database import db as app_db
                repo = ModelPresetRepository(app_db)
                preset = await repo.get_by_key(model_key)
                model_name = preset['name'] if preset else model_key
            except Exception:
                model_name = model_key
            await safe_edit_text(callback.message,
                f"✅ Модель OpenAI обновлена: {model_name}.\n\n"
                "Она будет использоваться при выборе провайдера OpenAI.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                ])
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось сохранить выбор модели")

    @router.callback_query(F.data == "reset_openai_model_preference")
    async def reset_openai_model_preference_callback(callback: CallbackQuery):
        """Сбрасывает предпочитаемую модель OpenAI"""
        try:
            await user_service.update_user_openai_model_preference(callback.from_user.id, None)
            await safe_edit_text(callback.message,
                "🔄 Выбор модели OpenAI сброшен.\n\n"
                "Будет использован пресет по умолчанию.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                ])
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в reset_openai_model_preference_callback: {e}")
            await callback.answer("❌ Не удалось сбросить выбор модели")

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
            # Сбрасываем все настройки пользователя
            await user_service.update_user_llm_preference(callback.from_user.id, None)
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
                "• Предпочтения ИИ сброшены\n"
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
            from database import db
            from reliability.middleware import monitoring_middleware
            from datetime import datetime

            user_stats = await db.get_user_stats(callback.from_user.id)
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
            from ux.quick_actions import QuickActionsUI

            keyboard = QuickActionsUI.create_settings_menu()

            await safe_edit_text(callback.message,
                "⚙️ **Настройки бота**\n\n"
                "Настройте бота под ваши предпочтения:",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в back_to_settings_callback: {e}")
            await callback.answer("❌ Произошла ошибка при возврате к настройкам")

    return router
