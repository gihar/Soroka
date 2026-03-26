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
            from config import settings as app_settings
            models = getattr(app_settings, 'openai_models', [])
            if not models or len(models) == 0:
                await safe_edit_text(callback.message,
                    "❌ Не настроены модели OpenAI.\n\n"
                    "Добавьте переменную окружения `OPENAI_MODELS` с перечнем пресетов.",
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
            for p in models:
                label = f"{'✅ ' if selected_key == p.key else ''}{p.name}"
                keyboard_rows.append([InlineKeyboardButton(text=label, callback_data=f"set_openai_model_{p.key}")])
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
            # Находим человекочитаемое имя модели из настроек
            try:
                from config import settings as app_settings
                preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == model_key), None)
                model_name = preset.name if preset else model_key
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
