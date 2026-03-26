"""
Обработчики callback запросов для выбора LLM провайдера.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.telegram_safe import safe_edit_text
from .helpers import _safe_callback_answer


async def _show_llm_selection(callback: CallbackQuery, state: FSMContext,
                              user_service: UserService, llm_service: EnhancedLLMService,
                              processing_service: ProcessingService):
    """Показать выбор LLM или использовать сохранённые предпочтения"""
    from .processing_callbacks import _process_file

    user = await user_service.get_user_by_telegram_id(callback.from_user.id)
    available_providers = llm_service.get_available_providers()

    if not available_providers:
        await safe_edit_text(callback.message,
            "❌ Нет доступных LLM провайдеров. "
            "Проверьте конфигурацию API ключей."
        )
        return

    # Проверяем, есть ли у пользователя сохранённые предпочтения
    if user and user.preferred_llm is not None:
        preferred_llm = user.preferred_llm
        # Проверяем, что предпочитаемый LLM доступен
        if preferred_llm in available_providers:
            # Сохраняем в состояние и сразу переходим к обработке
            await state.update_data(llm_provider=preferred_llm)
            # Определяем отображаемое имя: для OpenAI используем название модели, без префикса провайдера
            llm_display = available_providers[preferred_llm]
            if preferred_llm == 'openai':
                try:
                    from config import settings as app_settings
                    selected_key = getattr(user, 'preferred_openai_model_key', None)
                    preset = None
                    if selected_key:
                        preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == selected_key), None)
                    if not preset:
                        models = getattr(app_settings, 'openai_models', [])
                        if models:
                            preset = models[0]
                    if preset and getattr(preset, 'name', None):
                        llm_display = preset.name
                except Exception:
                    pass
            await safe_edit_text(callback.message,
                f"🤖 Используется LLM: {llm_display}\n\n"
                "⏳ Начинаю обработку..."
            )
            # Отвечаем на callback перед длительной обработкой
            await _safe_callback_answer(callback)
            await _process_file(callback, state, processing_service)
            return

    # Если предпочтений нет или предпочитаемый LLM недоступен, показываем выбор
    current_llm = user.preferred_llm if user else 'openai'

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅ ' if provider_key == current_llm else ''}{provider_name}",
            callback_data=f"select_llm_{provider_key}"
        )]
        for provider_key, provider_name in available_providers.items()
    ])

    await safe_edit_text(callback.message,
        "🤖 Выберите LLM для обработки:",
        reply_markup=keyboard
    )


def setup_llm_callbacks(user_service: UserService, template_service: TemplateService,
                         llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для LLM"""
    router = Router()

    @router.callback_query(F.data.startswith("set_llm_"))
    async def set_llm_callback(callback: CallbackQuery):
        """Обработчик выбора LLM"""
        try:
            llm_provider = callback.data.replace("set_llm_", "")

            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)

            available_providers = llm_service.get_available_providers()
            provider_name = available_providers.get(llm_provider, llm_provider)

            await safe_edit_text(callback.message,
                f"✅ LLM провайдер изменен на: {provider_name}\n\n"
                f"Теперь этот LLM будет использоваться автоматически для всех обработок."
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в set_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении настроек")

    @router.callback_query(F.data == "reset_llm_preference")
    async def reset_llm_preference_callback(callback: CallbackQuery):
        """Обработчик сброса предпочтений LLM"""
        try:
            await user_service.update_user_llm_preference(callback.from_user.id, None)

            await safe_edit_text(callback.message,
                "🔄 Предпочтения LLM сброшены.\n\n"
                "Теперь бот будет спрашивать выбор LLM при каждой обработке файла."
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в reset_llm_preference_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")

    @router.callback_query(F.data.startswith("select_llm_"))
    async def select_llm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора LLM для обработки"""
        from .processing_callbacks import _process_file

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            llm_provider = callback.data.replace("select_llm_", "")

            # Сохраняем выбор пользователя как предпочтение
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            await state.update_data(llm_provider=llm_provider)

            # Начинаем обработку
            await _process_file(callback, state, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в select_llm_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при выборе LLM")

    return router
